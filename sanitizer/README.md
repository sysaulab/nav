
# Document Sanitizer

Turns documents and images into a single canonical JSON shape — per-page
text blocks with bounding boxes, per-block and per-document confidence, and
a quality verdict. Same input always produces the same output (modulo OCR
model nondeterminism), and every routing decision is recorded in
`source.route` / `source.converter`.

Sized for a **single-user workstation**: one process, one ingest at a time,
no auth, no tenant isolation. See [Known limits](#known-limits).

---

## Quick start

```bash
# 1. System deps (Debian/Ubuntu — libmagic for MIME sniffing, GL for OCR)
sudo apt-get install -y libmagic1 libgl1 libglib2.0-0 libgomp1

# 2. Python deps
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # or -r requirements.lock if present

# 3. Try it — one file to stdout, logs to stderr
python -m app.main ./examples/kraken_bw_example.png

# 4. Or start the server
python -m app.main
# listening on http://127.0.0.1:8000
```

First run downloads RapidOCR + Docling models into `~/.cache`. Set
`XDG_CACHE_HOME=/opt/models` (as the Dockerfile does) to relocate.

---

## Usage

### Server mode

```bash
python -m app.main                                  # 127.0.0.1:8000 (default)
python -m app.main --host 0.0.0.0 --port 9000       # expose on all ifaces
```

| Endpoint | Method | Purpose |
|---|---|---|
| `/ingest` | POST (multipart `file`) | Route and process one upload |
| `/health` | GET | Liveness — never blocked by ingest |
| `/ready`  | GET | Readiness — OCR engine loaded |

`/ingest` is serialized by a module-level lock. Two concurrent uploads will
queue, not race. `/health` and `/ready` are deliberately outside that lock.

```bash
curl -sS -F file=@scan.pdf http://127.0.0.1:8000/ingest | jq .
```

### CLI mode

```bash
python -m app.main FILE                     # JSON to stdout, logs to stderr
python -m app.main --help                   # full usage + exit codes
```

**One file per invocation.** If you pass multiple positionals, only the
first is processed; extras are logged to stderr and ignored. Run once per
file:

```bash
for f in docs/*.pdf; do
    python -m app.main "$f" > "${f}.json" || echo "FAILED: $f" >&2
done
```

`--host` / `--port` have no effect in file mode; passing them logs a
warning and proceeds.

### Docker

```bash
docker build -t sanitizer .
docker run --rm -v "$PWD:/data" sanitizer \
    python -m app.main /data/scan.pdf

docker run --rm -p 8000:8000 sanitizer        # server mode
```

The Dockerfile runs **one uvicorn worker** by design (matching the
`_ingest_lock` contract). Do not raise `--workers` or run multiple replicas
without replacing the lock with a distributed primitive.

---

## Output format

Every route returns the same top-level shape, whether it succeeded, was
quarantined, or found nothing:

```json
{
  "schema_version": "1.0",
  "document_id": "sha256:…",
  "source": {
    "filename": "scan.pdf",
    "mime_type_declared": "application/pdf",
    "mime_type_sniffed": "application/pdf",
    "route": "pdf_scanned_ocr",
    "converter": "rapidocr",
    "page_count": 3
  },
  "text": "…full concatenated text…",
  "metadata": {},
  "pages": [
    {
      "page_number": 1,
      "width": 2480.0,
      "height": 3508.0,
      "blocks": [
        {
          "type": "heading",
          "text": "CHAPTER ONE",
          "bbox": [120.0, 210.0, 1800.0, 260.0],
          "confidence": {"min": 0.94, "mean": 0.97, "max": 0.99, "lines": 1},
          "table_data": null,
          "block_id": "p1_b0",
          "reading_order": 0
        }
      ]
    }
  ],
  "rollup": {
    "confidence": {"min": 0.62, "mean": 0.91, "max": 0.99},
    "block_count": 42,
    "low_confidence_block_count": 1,
    "low_confidence_block_ids": ["p2_b7"]
  },
  "quality": {"status": "pass", "reasons": []}
}
```

### Invariants downstream consumers can rely on

- **Key order** is fixed per schema version: `schema_version`, `document_id`,
  `source`, `text`, `metadata`, `pages`, `rollup`, `quality`.
- **`None` is emitted as JSON `null`, never omitted.** A consumer can
  distinguish "field not present in this schema version" (missing key) from
  "present but null".
- **`confidence` shape** when non-null: `{min, mean, max, lines}` — floats
  except `lines` (int). When no block reported confidence (e.g., text
  handler, empty OCR), `rollup.confidence` is `{min: null, mean: null, max: null}`.
- **`rollup.confidence.mean`** is a *mean-of-block-means*, not a
  line-weighted mean. A low-confidence line in a short block weighs more
  than the same line inside a long paragraph. `min` / `max` are true global
  extrema.
- **Blank pages are valid output.** Zero blocks + `quality.status == "pass"`
  means the sanitizer looked and found nothing. It is not an error.

---

## Routing

Selected by extension, sniffed MIME, and declared MIME, checked in this
order. First match wins.

| Priority | Route | Extensions | Converter | Notes |
|---|---|---|---|---|
| 1 | `docling_office` | `.odt .ods .odp .doc .xls .ppt .rtf` | docling | ODF + legacy binary + RTF |
| 2 | `office` | `.docx .xlsx .pptx` | officemd | OOXML, no LibreOffice |
| 3 | `pdf_native` | `.pdf` with text layer | docling | Digital-born PDF |
| 3 | `pdf_scanned_ocr` | `.pdf` without text layer | rapidocr | Rasterize at 200 DPI → OCR |
| 4 | `image_ocr` | `.png .jpg .jpeg .tif .tiff .bmp .webp .gif` | rapidocr | In-process ONNX |
| 5 | `text` | `.txt .md .csv .tsv .json .xml .html .htm .log .yaml .yml` | plaintext | UTF-8 decode, lossy |
| 6 | `quarantine` | anything else | none | `quality.status = "quarantine"` |

**PDF text-layer detection** samples the first 3 pages for ≥20 extractable
characters. If `pypdf` is missing, every PDF goes to the scanned route
(slower, costlier) — install it.

**Sniffed MIME is used for routing but the extension wins on ties.** A PDF
renamed to `.docx` will hit the office route and quarantine on failure
rather than falling back to the PDF route. Rename files correctly.

---

## Quality and quarantine

Two states, deliberately simple:

- `"pass"` — the pipeline ran end-to-end. **Includes** documents with zero
  blocks. Absence of text is a property of the input, not a failure.
- `"quarantine"` — the pipeline could not produce a trustworthy result.
  `quality.reasons` explains why. `pages` is empty and `text` is `""`.
  `source.route` / `source.converter` record which handler attempted it.

Nothing is ever "partially processed." A document with a missing page is
quarantined, not returned with pages 1–N. A silently-partial document is
worse than a rejected one.

Common quarantine reasons:

| Reason | Meaning |
|---|---|
| `too_many_pages: N > MAX` | Exceeded `SANITIZER_MAX_PAGES` |
| `docling_not_installed` / `pymupdf_not_installed` | Optional dep missing |
| `docling_error: …` / `officemd_error: …` | Converter raised |
| `pdf_rasterize_error: page=N …` | pymupdf failed on a page |
| `ocr_engine_error: page=N …` | OCR inference failed |
| `image_decode_error: …` | Bytes were not a decodable image |
| `unsupported_format: ext=… sniffed=…` | No route matched |

---

## Exit codes (CLI mode)

Contract — scripts may depend on these. **Do not renumber.**

| Code | Meaning |
|---|---|
| `0` | `quality.status == "pass"` |
| `1` | Quarantined (see `quality.reasons`) |
| `2` | Exceeded `SANITIZER_MAX_UPLOAD_BYTES` |
| `3`–`999` | Reserved for future use |
| `1000` | Any other error (unreadable, handler exception, invalid args) |

Argument parser errors also return `1000`, not argparse's default `2` —
otherwise a typo'd flag would be indistinguishable from an oversize file.
`--help` exits `0`.

---

## Configuration

All values are env vars. Defaults are sized for a single-user workstation;
raise them if you have headroom.

| Env var | Default | Meaning |
|---|---|---|
| `SANITIZER_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) | Hard cap on any single ingest, enforced on both HTTP and CLI paths |
| `SANITIZER_MAX_PAGES` | `500` | Cap on page count for paginated routes; exceeding it quarantines |
| `SANITIZER_LOW_CONFIDENCE_THRESHOLD` | `0.65` | Blocks with `confidence.min` below this are listed in `rollup.low_confidence_block_ids` (never dropped) |
| `SANITIZER_LOG_LEVEL` | `INFO` | `DEBUG` for per-file detail |
| `XDG_CACHE_HOME` / `HF_HOME` | `~/.cache` | Model cache location (RapidOCR, Docling) |

The upload cap is enforced in two places so it can't drift:

1. HTTP: `ContentLengthLimit` middleware (declared `Content-Length`) +
   `_read_bounded` (`limit + 1` read, covers chunked transfers).
2. CLI: `stat().st_size` before read + `len(raw)` after read.

> **Note:** the HTTP size guard limits *memory*, not *disk*. Starlette's
> multipart parser has already spooled the body to a temporary file by the
> time `_read_bounded` runs, so a 10 GB chunked upload will fill `/tmp`
> before the 413 fires. Acceptable for a workstation; revisit if this ever
> moves behind an untrusted client.

---

## Logging

All logs go to **stderr** in both modes. Structured `extra` fields
(`req_id`, `elapsed_ms`, `route`, `bytes`, `quality`, `blocks`, `low_conf`)
are attached to each record — the default formatter doesn't print them, but
a JSON formatter (swap the `Formatter` in `_setup_logging`) will.

Per-ingest lifecycle:

```
ingest.start    req_id=… upload_name=… bytes=…
ingest.finish   req_id=… route=… converter=… quality=… pages=… blocks=… low_conf=… elapsed_ms=…
ingest.error    req_id=… upload_name=… (with traceback)
```

CLI additionally emits:

```
cli.too_large         path=… bytes=… limit=…   (exit 2)
cli.stat_failed       path=… err=…             (exit 1000)
cli.read_failed       path=… err=…             (exit 1000)
cli.process_failed    path=… exc=… exit=…      (exit 1000)
cli.extra_files_ignored kept=… ignored=…       (warning)
cli.host_port_ignored                          (warning)
```

The `cli.process_failed` record is a one-line summary only — the full
traceback for handler exceptions comes from the preceding `ingest.error`.

---

## Known limits

Explicit non-goals and current constraints. Not bugs — deliberate scope.

- **Single worker, single process.** `/ingest` is serialized by a
  `threading.Lock`. Two concurrent uploads queue; the second sees no
  progress until the first finishes. Do not scale with `--workers` or
  replicas without replacing the lock.
- **Single user.** No auth, no tenant isolation, no per-tenant limits. Bind
  to `127.0.0.1` (the default) unless you know what you're exposing.
- **Synchronous HTTP handler.** `/ingest` is a `def` (not `async def`), so
  FastAPI runs it in the threadpool. Do not convert it — that would block
  the event loop for the duration of the ingest.
- **OCR is CPU-bound.** ONNX inference dominates ingest time for scanned
  documents. `CPU-only torch` is installed via the Dockerfile to avoid
  pulling the ~2.5 GB CUDA wheel.
- **PDF page limit is post-conversion** on the native route (docling offers
  no pre-flight page count). On the scanned route it's pre-rasterization
  (`len(pdf)`) — much cheaper.
- **Text decoding is UTF-8 only, `errors="replace"`.** UTF-16 / CP-1252
  will produce garbled text without warning. Fine for our use; not a
  general-purpose text normalizer.
- **`officemd` and `odfdo` are not version-pinned** in `requirements.txt`.
  `requirements.lock` (if present) is the source of truth. A fresh
  `pip install` without the lock may pull a breaking major of either.
- **Extension wins over sniffed MIME on ties.** Renamed files can be
  misrouted. Deliberate: prefer "obvious intent" (`.docx`) over "content
  sniff" when they disagree, so a corrupt `.docx` quarantines rather than
  silently landing on the wrong handler.
- **No streaming / no incremental output.** The full `Document` is
  materialized before serialization. Peak memory is roughly 2–3× the upload
  size (request body + temp file + Python object). Not a concern below the
  100 MiB cap.
- **`rollup.low_confidence_block_ids` omits blocks without a `block_id`.**
  All current OCR routes set `block_id`; a future handler that doesn't will
  be counted inconsistently between `low_confidence_block_count` and
  `low_confidence_block_ids`. Known, deferred.

---

## Layout

```
app/
  main.py              FastAPI app + CLI entry point
  router.py            Extension/MIME dispatch; route() and route_bytes()
  settings.py          Env-driven config (all limits are safety valves)
  models.py            Pydantic Document / Page / Block + rollup()
  handlers/
    __init__.py        "Blank pages are valid output."
    quarantine.py      Shared empty-document constructor
    office.py          OOXML via officemd
    docling.py         ODF / legacy Office / RTF via docling
    pdf.py             Native (docling) vs scanned (pymupdf + OCR)
    image.py           In-process RapidOCR
    text.py            Plain text (UTF-8, lossy)
  ocr/
    engine.py          RapidOCR wrapper (lazy singleton)
    reconcile.py       OCR lines → reading-ordered blocks
Dockerfile             Pinned Python, CPU-only torch, one worker
```

### Design notes worth preserving

- **`Block` uses `extra="forbid"`.** The dict shapes feeding `Block(**d)`
  are a contract between `reconcile.py` and the handlers. A silent extra
  field is a bug, not a forward-compatibility win.
- **`Document.to_dict()` is the contract.** `schema_version` is emitted
  there; page serialization goes through Pydantic recursion. Do not
  serialize `Document` directly.
- **Every failure path returns the same empty-document shape.** Callers
  branch on `quality.status`, not on each handler's error model.
- **Handlers are pure functions** of `(path, raw, doc_id, declared, sniffed)`
  → `Document`. They never raise; they return a quarantined `Document`.
- **`route_bytes()` spools to a temp file** so `route()`'s path-based
  handlers (officemd, docling, pymupdf) see the same on-disk shape as a
  real upload. `display_name` carries the original filename through to
  `source.filename`.

---

## Development

```bash
pytest                                     # if tests/ exists
python -m app.main --help                  # usage + exit codes
python -m app.main examples/*.pdf 2>&1     # logs to stderr, JSON to stdout
SANITIZER_LOG_LEVEL=DEBUG python -m app.main examples/scan.png
```

When debugging a misroute, the `source.route` / `source.converter` pair in
the output tells you exactly which handler ran. When debugging a
quarantine, `quality.reasons[0]` is the summary and the `ingest.error`
traceback (if any) is on stderr.

