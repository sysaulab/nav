"""app/main.py — FastAPI entrypoint + CLI.

Two modes, selected by argv:

    python -m app.main                       -> serve on 127.0.0.1:8000
    python -m app.main FILE                  -> process FILE to stdout,
                                                logs to stderr
    python -m app.main --host 0.0.0.0 --port 9000
                                             -> serve on 0.0.0.0:9000
    python -m app.main --help                -> usage + exit codes

Only ONE positional FILE is processed. If several are given, the first is
used and the rest are logged to stderr and ignored. Run the command once
per file (`python -m app.main a.pdf; python -m app.main b.docx`) — this is
deliberate, matching the single-ingest lock semantics of server mode.

Exit codes (file mode):
    0     quality.status == "pass"
    1     quarantined (see quality.reasons)
    2     exceeded SANITIZER_MAX_UPLOAD_BYTES
    3-999 reserved for future use
    1000  any other error (unreadable, handler exception, invalid args)

Concurrency model: single-user, single-process, one ingest at a time.

    - Sync `def` endpoints — FastAPI dispatches them to anyio's threadpool,
      so the event loop never blocks on OCR.
    - A module-level lock serializes the *pipeline* (/ingest). Without it,
      two concurrent uploads would run two RapidOCR inferences in two
      threadpool workers — the exact CPU/memory contention we are avoiding.
    - /health and /ready are intentionally outside the lock so a hung
      ingest doesn't make the liveness probe hang with it.

Blank pages are valid output: a document with zero blocks and
quality.status == "pass" means the sanitizer looked and found nothing.
See router.route_bytes() docstring.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.router import route_bytes
from app.settings import MAX_UPLOAD_BYTES


# --------------------------------------------------------------------------
# Exit codes (CLI contract — do not renumber)
# --------------------------------------------------------------------------

EXIT_PASS = 0
EXIT_QUARANTINE = 1
EXIT_TOO_LARGE = 2
# 3-999 reserved for future use.
EXIT_OTHER_ERROR = 1000


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

log = logging.getLogger("sanitizer.cli")


def _setup_logging() -> None:
    """Attach a stderr handler to the `sanitizer` logger tree.

    Called at import time so both `uvicorn app.main:app` and
    `python -m app.main` produce logs. Required because the Dockerfile
    imports `app.main:app` rather than executing `__main__` — without
    import-time setup, router.route_bytes's INFO records are dropped by
    logging.lastResort (WARNING+ only) and ingest.start / ingest.finish
    never reach a handler.

    Idempotent: guarded by `root.handlers`, so re-import or a second call
    from a test harness is a no-op.

    `propagate=False` prevents our records from leaking into uvicorn's
    handler tree (which has a different format and would double-print).

    Set SANITIZER_LOG_LEVEL=DEBUG for per-file detail. Structured `extra`
    fields (req_id, elapsed_ms, route, ...) are attached to each LogRecord
    but not in the default format — swap the Formatter for a JSON one when
    you need them.
    """
    root = logging.getLogger("sanitizer")
    if root.handlers:
        return
    level = os.getenv("SANITIZER_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    ))
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


_setup_logging()


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = FastAPI(title="Document Sanitizer")

# Serializes ingest. Plain Lock: no handler re-enters route(), and /ocr —
# the only former second caller — has been removed. Switch to RLock if a
# handler ever calls back into route().
_ingest_lock = threading.Lock()


class ContentLengthLimit(BaseHTTPMiddleware):
    """Reject oversized uploads by declared Content-Length before the body
    is read. Does not apply to chunked transfers (no Content-Length header);
    those fall through to _read_bounded's limit+1 read as a second guard.
    """

    def __init__(self, app, *, limit: int, paths: frozenset[str]):
        super().__init__(app)
        self.limit = limit
        self.paths = paths

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.paths:
            declared = request.headers.get("content-length")
            if declared is not None:
                try:
                    n = int(declared)
                except ValueError:
                    return JSONResponse(
                        {"detail": "invalid Content-Length header"},
                        status_code=400,
                    )
                if n < 0:
                    return JSONResponse(
                        {"detail": "invalid Content-Length header"},
                        status_code=400,
                    )
                if n > self.limit:
                    return JSONResponse(
                        {"detail": f"upload exceeds {self.limit} bytes"},
                        status_code=413,
                    )
        return await call_next(request)


def _read_bounded(upload: UploadFile, limit: int) -> bytes:
    """Read the upload with a hard size cap — second line of defense.

    The primary guard is `ContentLengthLimit` middleware, which rejects
    oversize requests before Starlette reads the body. This read catches
    chunked transfers that omit Content-Length: reading limit+1 bytes
    aborts the read rather than buffering an arbitrarily large body.
    """
    raw = upload.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {limit} bytes",
        )
    return raw


app.add_middleware(
    ContentLengthLimit,
    limit=MAX_UPLOAD_BYTES,
    paths=frozenset({"/ingest"}),
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    # The OCR engine is a module-level singleton in app.ocr.engine. If this
    # module imported successfully, the ONNX models are in memory. Docling is
    # imported lazily inside its handler and is not checked here.
    return {"status": "ready", "ocr_engine": "loaded"}


@app.post("/ingest")
def ingest(file: UploadFile = File(...)):
    raw = _read_bounded(file, MAX_UPLOAD_BYTES)
    name = file.filename or "upload"
    with _ingest_lock:
        doc = route_bytes(name, raw)
    return doc.to_dict()


# --------------------------------------------------------------------------
# CLI argument parsing
# --------------------------------------------------------------------------

class _CliParser(argparse.ArgumentParser):
    """ArgumentParser that exits with EXIT_OTHER_ERROR (1000) on usage errors.

    argparse's default error exit code is 2, which collides with our
    EXIT_TOO_LARGE — a typo'd flag must not look like an oversize file.
    `--help` is unaffected: it goes through argparse's _HelpAction, which
    calls `exit(0)` directly without touching `error()`.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_OTHER_ERROR, f"{self.prog}: error: {message}\n")


def _parse_port(s: str) -> int:
    try:
        n = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {s!r}")
    if not (1 <= n <= 65535):
        raise argparse.ArgumentTypeError(f"port out of range 1-65535: {n}")
    return n


_EPILOG = textwrap.dedent("""\
    exit codes (file mode):
        0       file processed, quality.status == "pass"
        1       file quarantined (see quality.reasons in the JSON)
        2       file exceeded SANITIZER_MAX_UPLOAD_BYTES
        3-999   reserved for future use
        1000    any other error (unreadable, handler exception, invalid args)

    File mode processes exactly ONE file. If more than one positional
    argument is given, only the first is processed; the rest are logged
    to stderr and ignored. Invoke once per file:

        python -m app.main a.pdf
        python -m app.main b.docx

    --host and --port have no effect in file mode; passing them alongside
    a FILE logs a warning and proceeds.
""")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _CliParser(
        prog="python -m app.main",
        description=(
            "Document sanitizer. With no FILE, starts the HTTP server. "
            "With FILE, processes that one file to stdout (logs to stderr)."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help=(
            "File to process. Only the FIRST positional is used; extras are "
            "ignored. Omit to start the HTTP server instead."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        metavar="ADDR",
        help="Bind address for server mode (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        default=None,
        metavar="N",
        type=_parse_port,
        help="Bind port for server mode, 1-65535 (default: 8000).",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------
# CLI execution
# --------------------------------------------------------------------------

def _cli(path: str) -> int:
    """Process a single file to stdout. Returns the file's exit code.

    Mirrors the HTTP ingest path exactly — same route_bytes dispatch, same
    MAX_UPLOAD_BYTES limit. Size is checked twice, matching the two HTTP
    guards:

      1. stat().st_size before reading (mirrors ContentLengthLimit) —
         rejects a multi-GB path without pulling it into memory.
      2. len(raw) after read (mirrors _read_bounded's limit+1) — covers
         the file growing between stat and read.
    """
    p = Path(path)

    try:
        size = p.stat().st_size
    except OSError as e:
        log.error("cli.stat_failed path=%s err=%s", path, e)
        return EXIT_OTHER_ERROR

    if size > MAX_UPLOAD_BYTES:
        log.error(
            "cli.too_large path=%s bytes=%d limit=%d",
            path, size, MAX_UPLOAD_BYTES,
        )
        return EXIT_TOO_LARGE

    try:
        raw = p.read_bytes()
    except OSError as e:
        log.error("cli.read_failed path=%s err=%s", path, e)
        return EXIT_OTHER_ERROR

    if len(raw) > MAX_UPLOAD_BYTES:
        log.error(
            "cli.too_large path=%s bytes=%d limit=%d",
            path, len(raw), MAX_UPLOAD_BYTES,
        )
        return EXIT_TOO_LARGE

    try:
        doc = route_bytes(path, raw)
    except Exception:
        log.exception("cli.process_failed path=%s", path)
        return EXIT_OTHER_ERROR

    json.dump(doc.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()

    if doc.quality["status"] != "pass":
        return EXIT_QUARANTINE
    return EXIT_PASS


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

def _serve(*, host: str, port: int) -> None:
    import uvicorn
    log.info("server.start host=%s port=%d", host, port)
    uvicorn.run(
        app,
        host=host,
        port=port,
        workers=1,                          # see _ingest_lock above
        timeout_graceful_shutdown=120,
        server_header=False,
    )


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])

    if args.files:
        target, extras = args.files[0], args.files[1:]
        if extras:
            log.warning(
                "cli.extra_files_ignored: kept=%s ignored=%s",
                target, extras,
            )
        if args.host is not None or args.port is not None:
            log.warning(
                "cli.host_port_ignored: --host / --port have no effect "
                "in file mode"
            )
        sys.exit(_cli(target))

    _serve(
        host=args.host if args.host is not None else "127.0.0.1",
        port=args.port if args.port is not None else 8000,
    )
    sys.exit(EXIT_PASS)