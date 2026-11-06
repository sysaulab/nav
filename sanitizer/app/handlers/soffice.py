"""app/handlers/soffice.py — LibreOffice headless handler.

Handles ODF (.odt/.ods/.odp), legacy binary Office (.doc/.xls/.ppt), and
RTF. Uses `soffice --headless --convert-to` directly rather than docling's
LibreOffice backend: no shared profile lock, explicit per-invocation
timeout, and no hidden model-load cost.

Target format per source extension:

    .odt .doc .rtf  -> txt:Text       (Writer plain text)
    .ods .xls       -> csv:Text - txt - csv (StarCalc)   (first sheet)
    .odp .ppt       -> txt:Text       (Impress plain text via notes)

`soffice` exits 0 even on failure and silently delegates to a running
instance, so the return code is ignored; the output file's existence and
non-emptiness are the real success signal.

Each invocation gets a unique `-env:UserInstallation` profile under
/tmp. Without it, concurrent conversions serialize on LibreOffice's
singleton profile lock and the second one fails intermittently. The
sanitizer's _ingest_lock already serializes ingest, but the per-profile
isolation is cheap insurance and required if the lock ever changes.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from app.handlers.quarantine import quarantine
from app.models import Block, Document, Page, rollup


SOFFICE_TIMEOUT_S = 60.0
_SOFFICE = shutil.which("soffice")


# (source extensions, target format spec, output extension)
# First match wins. Order matters: `.doc` must hit this handler before
# the legacy-block check in router.py if you want it converted rather
# than quarantined.
_ROUTES: tuple[tuple[frozenset[str], str, str], ...] = (
    (frozenset({".odt", ".doc", ".rtf"}), "txt:Text", "txt"),
    (
        frozenset({".ods", ".xls"}),
        # Token 1: field separator 44 (comma)
        # Token 2: text delimiter 34 (double quote)
        # Token 3: charset 76 (UTF-8)
        # Token 12: -1 = export all sheets to separate files
        'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1',
        "csv",
    ),
    (frozenset({".odp", ".ppt"}), "txt:Text", "txt"),
)


def _route_for(ext: str) -> tuple[str, str] | None:
    for exts, fmt, out_ext in _ROUTES:
        if ext in exts:
            return fmt, out_ext
    return None


def handle_soffice(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
    *,
    route_name: str = "soffice",
) -> Document:
    if _SOFFICE is None:
        return quarantine(
            doc_id, path, declared, sniffed,
            route=route_name, converter="soffice",
            reason="soffice_not_installed — install libreoffice-nogui",
        )

    route = _route_for(path.suffix.lower())
    if route is None:
        # Should not happen: router.py only dispatches matching extensions.
        # Defensive: quarantine rather than silently drop.
        return quarantine(
            doc_id, path, declared, sniffed,
            route=route_name, converter="soffice",
            reason=f"unsupported_soffice_extension: {path.suffix!r}",
        )
    fmt_spec, out_ext = route

    try:
        text = _soffice_convert(path, fmt_spec, out_ext)
    except RuntimeError as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route=route_name, converter="soffice",
            reason=f"soffice_error: {e}",
        )

    blocks = [Block(
        type="text", text=text, confidence=None,
        block_id="b0", reading_order=0,
    )]
    page = Page(page_number=1, blocks=blocks)

    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": route_name,
            "converter": "soffice",
            "page_count": 1,
        },
        text=text,
        pages=[page],
        metadata={},
        rollup=rollup([page]),
        quality={"status": "pass", "reasons": []},
    )


def _soffice_convert(path: Path, fmt_spec: str, out_ext: str) -> str:
    """Run soffice over `path`, return decoded output text.

    Raises RuntimeError on timeout, missing output, or empty output.
    The caller turns that into a quarantine.
    """
    with tempfile.TemporaryDirectory(prefix="soffice_") as td:
        td_path = Path(td)
        profile = td_path / "profile"
        outdir = td_path / "out"
        outdir.mkdir()

        # Copy input into the tempdir so soffice's cwd/output behaviour
        # cannot escape into the caller's cwd, and so the input name is
        # sanitized to something soffice won't reject.
        safe_input = td_path / f"input{path.suffix.lower()}"
        safe_input.write_bytes(path.read_bytes())

        cmd = [
            _SOFFICE,
            "--headless",
            "--nologo",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to", fmt_spec,
            "--outdir", str(outdir),
            str(safe_input),
        ]

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=SOFFICE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"soffice timed out after {SOFFICE_TIMEOUT_S}s"
            ) from e
        except (FileNotFoundError, OSError) as e:
            raise RuntimeError(f"soffice unavailable: {e}") from e

        # soffice exits 0 even on failure. Verify the output exists.
        # For CSV with token 12 = -1, soffice writes one file per sheet
        # named `<input-stem>-<sheetname>.csv`; for other targets it
        # writes `<input-stem>.<out_ext>`. Glob handles both.
        produced = sorted(outdir.glob(f"input*.{out_ext}"))
        if not produced:
            detail = proc.stderr.decode("utf-8", "replace")[:300]
            raise RuntimeError(detail or "soffice produced no output")

        # CSV: concatenate all sheets, separated by a blank line. This
        # loses sheet boundaries, but the sanitizer's Block model is
        # text-only — a consumer that needs sheet structure reads the
        # CSV itself. For non-CSV targets there is exactly one file.
        chunks: list[str] = []
        for f in produced:
            body = f.read_text(encoding="utf-8", errors="replace").strip()
            if body:
                chunks.append(body)
        if not chunks:
            raise RuntimeError("soffice output was empty")
        return "\n\n".join(chunks)