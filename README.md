# Local Resource Navigator

Two cooperating services for turning a person's documents and location into concrete, actionable referrals to nearby social services. Built for **single-tenant, single-user workstation** deployments — no auth, no multi-tenancy, no horizontal scaling. Bind to `127.0.0.1` unless you know what you're exposing.

```
┌──────────────┐    upload     ┌───────────────────┐    sanitized    ┌──────────────┐
│   browser    │ ────────────▶ │   nav-server      │ ──────────────▶ │ ingest-server│
│  (caseworker │               │   (port 8001)     │      JSON       │  (port 8000) │
│   / client)  │ ◀──────────── │   FastAPI+SQLite  │ ◀────────────── │  FastAPI+OCR │
└──────────────┘  NDJSON chat  └─────────┬─────────┘                 └──────────────┘
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
                ┌────────────┐     ┌────────────┐     ┌────────────┐
                │  Nominatim │     │   Ollama   │     │  local DB  │
                │ (geocoding)│     │  (LLM chat │     │  (SQLite)  │
                │  port 8080 │     │  + plan)   │     │            │
                └────────────┘     └────────────┘     └────────────┘
```

## What's in here

| Directory | Service | Port | Role |
|---|---|---|---|
| [`ingest-server/`](ingest-server/) | **Document Sanitizer** | 8000 | Turns PDFs, Office docs, images, and plain text into one canonical JSON shape — per-page blocks, bounding boxes, confidence, quality verdict. OCR runs in-process (RapidOCR). |
| [`nav-server/`](nav-server/) | **Navigator** | 8001 | Interview orchestration. Manages ephemeral sessions, forwards uploads to the sanitizer, budgets documents against an LLM context window, streams chat and a final action plan from Ollama, and localizes nearby services via Nominatim. |

Each service is independently runnable. The navigator treats the sanitizer as an opaque HTTP dependency — you can swap it for anything that returns the same JSON shape (see `ingest-server/REDME.md` § *Output format*).

> **Note:** the sanitizer's README lives at [`ingest-server/REDME.md`](ingest-server/REDME.md) (filename typo — worth renaming to `README.md`). It is the authoritative reference for the canonical output schema and exit codes.

---

## Quick start

### 1. System dependencies (host, not container)

```bash
# Debian / Ubuntu
sudo apt-get install -y libmagic1 libgl1 libglib2.0-0 libgomp1
# macOS
brew install libmagic
```

`libmagic` is required for MIME sniffing in the sanitizer. Without it the router falls back to extension-based guessing and silently misroutes renamed files. The GL/GLib/Gomp libs back OCR (RapidOCR → ONNX Runtime → OpenCV-headless).

### 2. Sanitizer

```bash
cd ingest-server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m app.main                       # 127.0.0.1:8000
```

First run downloads RapidOCR + Docling model caches into `~/.cache` (~500 MB, several minutes). Set `XDG_CACHE_HOME=/opt/models` to relocate.

### 3. Navigator

```bash
cd nav-server
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[tokenizer]"            # tokenizer extra = accurate prompt budgeting
python -m navigator                      # 127.0.0.1:8001
```

Point it at the running sanitizer, a Nominatim instance, and Ollama:

```bash
NAVIGATOR_SANITIZER_ENDPOINT=http://127.0.0.1:8000/ingest \
NAVIGATOR_NOMINATIM_ENDPOINT=http://127.0.0.1:8080 \
NAVIGATOR_OLLAMA_ENDPOINT=http://127.0.0.1:11434 \
python -m navigator
```

Nominatim and Ollama are not part of this repo — run them yourself (`mediagis/nominatim` and `ollama/ollama` are good starting points) or use hosted instances.

### 4. Docker

Each service has its own Dockerfile.

```bash
docker build -t sanitizer  ingest-server/
docker build -t navigator  nav-server/
```

The navigator Dockerfile expects the sanitizer, Nominatim, and Ollama to be reachable at hostnames `sanitizer`, `nominatim`, and `ollama` — either via a compose file or a shared Docker network:

```yaml
# illustrative — you'll need to supply the Nominatim + Ollama services
services:
  sanitizer:
    build: ./ingest-server
    ports: ["8000:8000"]
  navigator:
    build: ./nav-server
    ports: ["8001:8001"]
    volumes: ["./data:/data"]
    depends_on: [sanitizer]
```

**Do not** run multiple replicas of the sanitizer without replacing its `_ingest_lock` with a distributed primitive — it serializes OCR per process by design, and the Dockerfile pins `--workers 1` to match.

---

## Data flow

1. **`POST /api/interviews`** — the navigator mints a session, sets an HttpOnly `nav_session` cookie, and starts a 15-minute idle TTL.
2. **`POST /api/interviews/{sid}/location`** — the caseworker submits a postal code (or picks an autocomplete candidate from `/api/geocode/search`). The navigator geocodes it via Nominatim and stores `origin_lat/lng`. **Chat and finalize refuse to run until this is set.**
3. **`POST /api/interviews/{sid}/documents`** — the navigator forwards the upload to the sanitizer's `/ingest`, then keeps only the fields the LLM needs (`sanitize.filter_sanitizer_output`): filename, page count, quality, per-page blocks with `block_id`, `text`, `table_data`, `min_confidence`. Bounding boxes, MIME provenance, and rollup confidence are dropped. Nothing is written to disk; only the filtered JSON is stored in `session_document.payload_json`.
4. **`POST /api/interviews/{sid}/chat`** — the navigator assembles a system prompt (base instructions + rendered documents + nearby services) and proxies to Ollama's `/api/chat`, streaming NDJSON back to the client unmodified.
5. **`POST /api/interviews/{sid}/finalize`** — same context, different system prompt and model (`NAVIGATOR_FINAL_MODEL`, default `beam:cloud`). Streams the final prioritized action plan.

Sessions are wiped on `DELETE /api/interviews/{sid}` and on a background 30-second TTL sweep. Deleting a session cascades to its documents.

### Prompt budgeting

The context budget is **220,000 tokens** (configurable) — sized for a 256 K context window with room for generation and base prompt. Documents are consumed oldest-first; a document that would exceed the budget is **skipped, not truncated**, so a large early upload doesn't block a smaller later one. Skipped documents are reported back to the user via `context-prompt` and the system prompt itself.

Token estimation uses a real Gemma tokenizer when available (`transformers` extra), falling back to a conservative `chars/3.5` heuristic. The Dockerfile bakes the tokenizer into the image so the first request doesn't hit the network.

---

## Configuration

Both services are pure env-var driven. Defaults assume `127.0.0.1` co-location.

### Sanitizer (`SANITIZER_*`)

| Variable | Default | Meaning |
|---|---|---|
| `SANITIZER_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) | Hard cap on any single ingest |
| `SANITIZER_MAX_PAGES` | `500` | Page cap; exceeding it quarantines (never truncates) |
| `SANITIZER_LOW_CONFIDENCE_THRESHOLD` | `0.65` | Blocks below this are listed in `rollup.low_confidence_block_ids` |
| `SANITIZER_LOG_LEVEL` | `INFO` | `DEBUG` for per-file detail |
| `XDG_CACHE_HOME` / `HF_HOME` | `~/.cache` | Model cache location |

### Navigator (`NAVIGATOR_*`)

| Variable | Default | Meaning |
|---|---|---|
| `NAVIGATOR_DATABASE_URL` | `sqlite+aiosqlite:///./navigator.db` | SQLAlchemy URL; Docker uses `…:////data/navigator.db` |
| `NAVIGATOR_SANITIZER_ENDPOINT` | `http://127.0.0.1:8000/ingest` | Where uploads are forwarded |
| `NAVIGATOR_NOMINATIM_ENDPOINT` | `http://127.0.0.1:8080` | Geocoder base URL |
| `NAVIGATOR_OLLAMA_ENDPOINT` | `http://127.0.0.1:11434` | LLM base URL |
| `NAVIGATOR_OLLAMA_MODEL` | `gemma4:cloud` | Chat model |
| `NAVIGATOR_FINAL_MODEL` | `beam:cloud` | Finalize model |
| `NAVIGATOR_DOCUMENT_BUDGET_TOKENS` | `220000` | Prompt token budget |
| `NAVIGATOR_MAX_DOCUMENTS_PER_SESSION` | `50` | Upload cap |
| `NAVIGATOR_SESSION_IDLE_MINUTES` | `15` | Sliding TTL |
| `NAVIGATOR_POSTCODE_RADIUS_KM` | `25.0` | Nearby-services search radius |
| `NAVIGATOR_NEARBY_SERVICES_LIMIT` | `20` | Cap on services injected into prompt |
| `NAVIGATOR_TOKENIZER_MODEL` | `google/gemma-2-2b-it` | HF tokenizer used for estimation |

---

## Development

```bash
# Sanitizer — CLI mode (one file per invocation; exits 0/1/2/1000)
cd ingest-server
python -m app.main examples/scan.pdf 2>/dev/null | jq .
python -m app.main --help             # exit-code contract

# Navigator
cd nav-server
pytest                                 # if tests/ exists
python -m navigator --db-url sqlite+aiosqlite:///./dev.db
```

When a document misbehaves end-to-end, work backwards:

1. `source.route` / `source.converter` in the sanitizer's response tells you which handler ran.
2. `quality.status == "quarantine"` → `quality.reasons[0]` is the summary; the `ingest.error` traceback is on the sanitizer's stderr.
3. `GET /api/interviews/{sid}/context-prompt` on the navigator shows exactly what the LLM will see — including which documents were skipped and why.

## Layout

```
.
├── ingest-server/           Document Sanitizer (port 8000)
│   ├── app/
│   │   ├── main.py          FastAPI app + CLI entry point
│   │   ├── router.py        Extension/MIME dispatch
│   │   ├── settings.py      Env-driven config
│   │   ├── models.py        Pydantic Document / Page / Block
│   │   ├── handlers/        Per-format handlers (office, docling, pdf, image, text, quarantine)
│   │   └── ocr/             RapidOCR wrapper + reading-order reconciliation
│   ├── Dockerfile           Pinned Python, CPU-only torch, one worker
│   └── REDME.md             Sanitizer reference (schema, routes, exit codes)
│
└── nav-server/              Navigator (port 8001)
    ├── navigator/
    │   ├── main.py          FastAPI factory, startup migrations, purge loop, health, geocode
    │   ├── config.py        Pydantic settings (NAVIGATOR_* prefix)
    │   ├── db.py            Async SQLAlchemy engine + session
    │   ├── models.py        HSDS-style ORM (org / location / service / …)
    │   ├── schemas.py       Request/response models
    │   ├── prompt.py        System prompt assembly + document rendering
    │   ├── sanitize.py      Prune sanitizer output to LLM-relevant fields
    │   ├── tokens.py        Tokenizer-or-heuristic token counting
    │   ├── geocode.py       Short display-name derivation
    │   └── routers/         organizations, locations, services,
    │                        service_at_location, nested, interviews
    ├── pyproject.toml
    └── Dockerfile           Bakes HF tokenizer; expects sanitizer/nominatim/ollama on the network
```

---

## Where to read next

- **Sanitizer contract** — [`ingest-server/REDME.md`](ingest-server/README.md): output schema, routing rules, quarantine reasons, CLI exit codes, upload-size enforcement.
- **Interview flow** — [`nav-server/navigator/routers/interviews.py`](nav-server/navigator/routers/interviews.py): the sole orchestrator, documented endpoint-by-endpoint at the top of the file.
- **Prompt shape** — [`nav-server/navigator/prompt.py`](nav-server/navigator/prompt.py) and [`sanitize.py`](nav-server/navigator/sanitize.py): exactly which fields survive the round-trip into the LLM.
- **Data model** — [`nav-server/navigator/models.py`](nav-server/navigator/models.py): HSDS-aligned `Organization` → `Location` → `Service` → `ServiceAtLocation`, plus the `LiveOccupancy` extension and `InterviewSession` / `SessionDocument` tables.