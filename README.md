
# Local Resource Navigator

Two services that help a caseworker connect a client to local services. The **sanitizer** turns documents into canonical JSON. The **navigator** runs the interview, keeps per-visitor state, and orchestrates the LLM. A React front end sits on top of the navigator.

```
browser ──► nav-ui (nginx :80) ──► nav (FastAPI :8001) ──► SQLite (nav.db)
                                        │
                                        ├──► sanitizer (FastAPI :8000)  ← document uploads
                                        ├──► photon (:2322)             ← address → lat/lng
                                        └──► Ollama                     ← chat + finalize
```

The sanitizer is stateless — no sessions, no cookies, no LLM. The navigator is stateful — it owns the directory DB, sessions, and uploaded-document metadata.

---

## INSTALL — what you need first

On the host:

- **Docker Engine + Compose v2.**
- **Ollama** running on the host, reachable at `host.docker.internal:11434`. Pull the models the running stack will actually ask for:
  ```bash
  # Under `docker compose up`: chat=gemma4:cloud, finalize=nemotron-3-ultra:cloud
  ollama pull gemma4:cloud
  ollama pull nemotron-3-ultra:cloud

  # If you run the navigator standalone (no compose), the finalize model
  # defaults to `beam:cloud` — pull that instead:
  # ollama pull beam:cloud
  ```
  Override with `NAVIGATOR_OLLAMA_MODEL` / `NAVIGATOR_FINAL_MODEL`. Note that `compose.yaml` already overrides the finalize model to `nemotron-3-ultra:cloud`, so if you're running under compose you only need the first two.
- **A Photon instance.** `compose.yaml` includes one (`rtuszik/photon-docker` with a prebuilt Canada index on first boot — allow time and disk; the planet index is ~60 GB, "canada" is far smaller). If you're bringing your own, point `NAVIGATOR_PHOTON_ENDPOINT` at it. **Nominatim is not part of the pilot stack** — `NAVIGATOR_NOMINATIM_ENDPOINT` exists as a setting but is only echoed in `/api/health`; the actual geocoder is Photon.
- **~4 GB RAM** on first ingest, for the sanitizer's OCR + docling model caches. Steady-state is much lower.

No host Python, no host Node, no host pandoc.

---

## INSTALL — bring it up

```bash
git clone <repo> && cd <repo>
docker compose up --build -d
```

First build takes several minutes:

- `sanitizer` installs CPU-only torch, then warms RapidOCR + Docling model caches into `/opt/models` (a few hundred MB). **Note:** `compose.yaml` currently mounts the sanitizer's cache volumes at `/home/app/.cache/{rapidocr,docling}`, not `/opt/models` — see [Known issues in the current tree](#known-issues-in-the-current-tree). The image still works; the caches just won't survive a rebuild until the mount paths are aligned.
- `nav-ui` runs a Vite build, then copies `dist/` into nginx.
- `nav` is a small install.

Check status:

```bash
docker compose ps                       # all services "running"
docker compose logs -f nav              # follow the navigator
```

Open **`http://localhost`** (the UI is published on port 80) — that's the UI. The status pills at the bottom of the welcome page should turn green for `nav`, `doc`, `geo`, and `llm`. A pill that stays red names the endpoint it failed to reach; that's the fastest way to spot a mis-set environment variable.

---

## INSTALL — smoke test

1. **Welcome page.** Four green pills. If `doc` is red, the sanitizer isn't up — `docker compose logs sanitizer`. If `llm` is red, Ollama on the host isn't reachable — check `docker compose logs nav | grep ollama`.
2. **`/interview`.** You should land on the location gate ("Where are you located?"). Type a postal code — the autocomplete should populate from `geo`. Pick one.
3. **Upload a PDF.** Any small one. It should appear in the Documents panel with a token count, and the "context budget" bar should move.
4. **Send a chat turn.** The assistant should respond. If it hangs, `llm` is unreachable or the model name is wrong.
5. **Finish.** The plan renders in the green box; **"📄 Office"** produces a valid `.docx` (exercises the pandoc subprocess). "📄 Markdown" downloads the raw plan.
6. **Close the tab, reopen.** The same session is resumed from the `nav_session` cookie, provided the row is still `active` and hasn't crossed its `expires_at` deadline. A fresh session is only minted if the cookie is missing or the row is gone/expired. To force a fresh session, wait out the 15-minute idle TTL or clear the cookie; the purger sweeps orphaned rows in ~15 min.

If all six pass, you have a working install. If any fail, the failure names the layer.

---

## INSTALL — dev mode (no Docker)

When you're editing the code and want hot reload. **Note the Python versions differ**: the navigator runs on 3.11+, but the sanitizer's `officemd==0.1.8` requires **3.12** wheels. Use separate virtualenvs.

**Sanitizer** (port 8000):
```bash
cd sanitizer
python3.12 -m venv .venv && . .venv/bin/activate
sudo apt-get install -y libmagic1 libgl1 libglib2.0-0 libgomp1   # Debian/Ubuntu
pip install -r requirements.txt
python -m app.main --host 127.0.0.1 --port 8000
```

**Navigator** (port 8001):
```bash
cd nav
python3.11 -m venv .venv && . .venv/bin/activate
sudo apt-get install -y pandoc                                   # for DOCX export
pip install -e .
NAVIGATOR_SANITIZER_ENDPOINT=http://127.0.0.1:8000/ingest \
NAVIGATOR_PHOTON_ENDPOINT=http://127.0.0.1:2322 \
NAVIGATOR_OLLAMA_ENDPOINT=http://127.0.0.1:11434 \
python -m navigator --host 127.0.0.1 --port 8001
```

**Photon** (port 2322, if you're not using the compose stack):
```bash
docker run -d --name photon -p 2322:2322 \
    -e REGION=canada -e UPDATE_STRATEGY=DISABLED \
    -v photon-data:/photon/data \
    rtuszik/photon-docker:latest
```

**UI** (port 5173, hot reload):
```bash
cd nav-ui
npm ci
npm run dev
# Vite proxies /api → http://127.0.0.1:8001 (see vite.config.ts)
```

Open `http://localhost:5173`. Same smoke test applies. On macOS the `apt-get` lines don't apply — `brew install libmagic pandoc` covers both.

---

## The navigator is multi-session by design

Every visitor gets their own `InterviewSession` row, created on demand and identified by an httpOnly cookie (`nav_session`). The session ID is a UUID; it acts as a bearer token, and every authenticated endpoint re-checks that the request's cookie matches the row it's about to touch.

Each session owns, independently: its origin (postal code, lat/lng, short display name), its **fixed, distance-ordered nearby-services index** (`nearby_service_ids`), its set of expanded service entries (`revealed_service_indices`), its uploaded documents (FK with `ondelete="CASCADE"`), and its sliding `expires_at` deadline.

Nothing is global except the service directory itself.

---

## Session lifecycle

**Create or resume.** `POST /interviews` looks for the cookie. If the row exists, is `active`, and hasn't expired, it slides the deadline forward and returns it. If the cookie points at a dead row, that row is deleted and a fresh one is minted.

**Location gate.** Chat and finalize refuse to run until a postal code has been resolved to lat/lng. Setting the location rebuilds the nearby-services index in one transaction — both `nearby_service_ids` and `revealed_service_indices` are reset together, so `[07]` never means a different service before and after a move.

**Sliding TTL.** Every authenticated request extends `expires_at` by `session_idle_minutes` (default 15). A session goes `expired` when the deadline has passed *and* a request arrives — but the purge loop sweeps it independently.

**Background purge.** A startup task loops every `session_purge_interval_s` (default 30s) and deletes rows whose `expires_at` is in the past. Deleting a session cascades away its documents.

**End.** `DELETE /interviews/{sid}` deletes the row (and its documents) immediately, provided the cookie matches.

---

## Isolation guarantees

- **No cross-session reads.** Every endpoint that takes a `{sid}` path parameter compares it against the request's cookie *before* loading the row. A guess at another visitor's UUID returns 404, not a leak.
- **No cross-session writes.** Document uploads are scoped by `session_id` on the row; chat and finalize re-derive context from the row identified by the cookie, not from client-supplied state.
- **Documents die with their session.** `ondelete="CASCADE"` on `SessionDocument.session_id` is only effective because `PRAGMA foreign_keys=ON` is set at connect time (`nav/navigator/db.py`). Without it, session deletes would orphan documents silently.
- **Prompt context is per-session.** `_build_chat_context` re-queries documents, origin, and nearby services fresh for every chat turn. There is no shared prompt state.

---

## Concurrency model

The navigator handles many sessions concurrently in **one event loop, one process**. `uvicorn.run(create_app(...), ...)` in `nav/navigator/main.py` passes no `workers` argument, so it defaults to 1. Concurrency comes from asyncio, not from multiple processes.

That's the correct shape for this workload: almost everything blocking lives off-process — SQLite via aiosqlite, the sanitizer via httpx, Photon via httpx, Ollama via httpx, pandoc via `asyncio.create_subprocess_exec`. The event loop stays responsive because no handler holds the GIL for long.

Three intentional serialization points:

**1. SQLite writes.** WAL is enabled (`PRAGMA journal_mode=WAL`), so reads do not block writes and vice versa. SQLite still serializes writers — two concurrent inserts queue. With per-visitor sessions, writes are short and infrequent; this is why the navigator is single-process rather than multi-worker. `workers > 1` on the same SQLite file would need a `busy_timeout` the current code doesn't set. Reads — the vast majority of traffic — scale freely under WAL.

**2. Sanitizer ingest.** `_ingest_lock = threading.Lock()` in `sanitizer/app/main.py` serializes `/ingest` across the process. Two concurrent uploads from two sessions queue. Deliberate: it bounds peak memory to one ingest's working set. The cost is real — one caseworker uploading while another uploads waits. `/health` and `/ready` are intentionally outside the lock so a hung ingest can't make liveness hang with it.

**3. Ollama inference.** Ollama serves one generation at a time per model. Two sessions chatting simultaneously queue at Ollama. The navigator doesn't try to serialize this itself — Ollama is the source of truth for that constraint.

---

## What is per-session vs shared

| | Per-session | Shared |
|---|---|---|
| Database | `InterviewSession` row, `SessionDocument` rows | `Organization`, `Location`, `Service`, `ServiceAtLocation` |
| Coordinates | `origin_lat`, `origin_lng` | (address → coords lookup is stateless) |
| Nearby services | `nearby_service_ids`, `revealed_service_indices` | Service rows themselves |
| Document payloads | `SessionDocument.payload_json` | (sanitizer has no retained state) |
| LLM context | Built fresh per request from the session row | (Ollama is stateless per request) |
| Cookie | `nav_session` per browser | (n/a) |

---

## The interview flow, end to end

1. Browser loads `/`, sees status pills populated from `/api/health*` — each pill reports the actual endpoint the backend dialed.
2. Opens `/interview`. `POST /interviews` creates a session and sets the cookie.
3. Location gate: debounced autocomplete against `/api/geocode/search` (Photon); the chosen candidate is posted to `/interviews/{sid}/location`, which geocodes (or trusts the candidate), builds the nearby-services index, and resets `revealed_service_indices`.
4. Uploads: multipart POST to `/interviews/{sid}/documents`, forwarded to the sanitizer, filtered, token-estimated, stored. Per-document status (`ready`, `skipped_too_large`, `quarantine`) is surfaced in the UI alongside a live token-budget bar.
5. Chat: `POST /interviews/{sid}/chat` streams NDJSON from Ollama with a `get_service_details(index)` tool. Tool results stay server-side; expanded services are also promoted into the next turn's system prompt so the model doesn't re-request them.
6. Finalize: `POST /interviews/{sid}/finalize` reuses the same context assembly against a different base prompt and a different model. The plan streams back the same way.
7. Export: `/api/export/docx` pipes the plan's Markdown through pandoc (stdin → stdout, `-o -`, no temp files) for a `.docx` download.

Any step that 404s/409s/410s a session (cookie missing, expired, ended, purged) drives the front end to the "session expired" modal rather than a generic error.

---

## Configuration

Everything env-driven; `NAVIGATOR_` prefix on the navigator, `SANITIZER_` prefix on the sanitizer. `compose.yaml` is the source of truth for what's actually set in the container; the table below lists what the code *reads* and what happens if it's absent.

Navigator defaults worth knowing:

| Setting | Default | Meaning |
|---|---|---|
| `NAVIGATOR_DATABASE_URL` | `sqlite+aiosqlite:///./navigator.db` | SQLite via aiosqlite |
| `NAVIGATOR_SANITIZER_ENDPOINT` | `http://127.0.0.1:8000/ingest` | Sanitizer POST target |
| `NAVIGATOR_SANITIZER_TIMEOUT_S` | `600` | Per-upload timeout |
| `NAVIGATOR_PHOTON_ENDPOINT` | `http://127.0.0.1:2322` | Geocoder base URL |
| `NAVIGATOR_OLLAMA_ENDPOINT` | `http://127.0.0.1:11434` | Ollama base URL |
| `NAVIGATOR_OLLAMA_MODEL` | `gemma4:cloud` | Chat model |
| `NAVIGATOR_OLLAMA_TIMEOUT_S` | `600` | Per-chat-turn timeout |
| `NAVIGATOR_FINAL_MODEL` | `beam:cloud` | Finalize model. **Overridden to `nemotron-3-ultra:cloud` by `compose.yaml`** |
| `NAVIGATOR_FINAL_TIMEOUT_S` | `600` | Finalize timeout |
| `NAVIGATOR_SESSION_IDLE_MINUTES` | `15` | Sliding TTL per session |
| `NAVIGATOR_SESSION_PURGE_INTERVAL_S` | `30` | Background sweep cadence |
| `NAVIGATOR_MAX_DOCUMENTS_PER_SESSION` | `50` | Per-session upload cap |
| `NAVIGATOR_DOCUMENT_BUDGET_TOKENS` | `220_000` | Prompt budget per chat turn |
| `NAVIGATOR_POSTCODE_RADIUS_KM` | `25.0` | Nearby-services radius |
| `NAVIGATOR_NEARBY_LOCATION_LIMIT` | `20` | Locations listed in the system prompt |
| `NAVIGATOR_NEARBY_INDEX_LIMIT` | `100` | Total services in the per-session index |
| `NAVIGATOR_TOKENIZER_MODEL` | `google/gemma-2-2b-it` | Tokenizer used for prompt-budget estimation. Falls back to `chars/3.5` if `transformers` is missing or the model isn't cached |

Vestigial / unused settings — present in `config.py` but not consulted on the hot path:

| Setting | Notes |
|---|---|
| `NAVIGATOR_NOMINATIM_ENDPOINT` | No longer used for geocoding. `/api/health` still echoes it in the payload, but nothing dials it. Photon is the geocoder. |
| `NAVIGATOR_POSTCODE_RADIUS_DEG` | Defined but unused; `_nearby_services` and `_build_chat_context` read `postcode_radius_km` only. |

Sanitizer defaults (see `sanitizer/README.md`): `SANITIZER_MAX_UPLOAD_BYTES = 100 MiB`, `SANITIZER_MAX_PAGES = 500`, `SANITIZER_LOW_CONFIDENCE_THRESHOLD = 0.65`. All safety valves, not functional constraints.

---

## Known limits

- **One navigator process, one sanitizer worker.** Multi-worker on SQLite would need `busy_timeout`; multi-worker on the sanitizer would need to replace `_ingest_lock`.
- **Uploads serialize.** Two concurrent uploads from different sessions queue at the sanitizer. This is the main user-facing cost of the current architecture.
- **No auth on the sanitizer.** It's intended to be reachable only by the navigator. Never publish it on a public interface.
- **SQLite writes serialize.** WAL makes reads concurrent; writes still queue. Fine at this workload, not a starting point for high-write use.
- **Sessions die hard.** No "recover an ended session" — the cascade is real, and the UI has no affordance for it.
- **The tokenizer heuristic is conservative.** Falls back to `chars / 3.5` if `transformers` is unavailable or the model isn't cached. Over-estimation excludes a document early; under-estimation would truncate output, so the heuristic under-divides on purpose.

---

## Known issues in the current tree

These are known defects in `compose.yaml`, the Dockerfiles, and a couple of stray references — none block a working install, but they will bite under specific conditions. Worth fixing rather than documenting around; listed here so anyone triaging a failure knows where to look.

- **`nav/dockerfile` HEALTHCHECK dials the wrong host.** The CMD is `curl -sf http://host.docker.internal:8001/api/health`. From *inside* the `nav` container, `host.docker.internal` points at the Docker host, not the container itself — so the healthcheck will report unhealthy even when the app is fine. Should be `http://127.0.0.1:8001/api/health`.
- **`nav/dockerfile` sets a dead `NAVIGATOR_NOMINATIM_ENDPOINT`.** It bakes in `NAVIGATOR_NOMINATIM_ENDPOINT="http://nominatim-bc:8080"`, but `nominatim-bc` is not a service in `compose.yaml`. Under `docker compose up` this is harmless (compose overrides it via env), but anyone running the Dockerfile standalone will see `/api/health` report a phantom Nominatim, and if they also forget to set `NAVIGATOR_PHOTON_ENDPOINT`, geocoding silently falls back to the in-container default `http://127.0.0.1:2322` — which is the container's own loopback, not the host's Photon.
- **`compose.yaml` mounts sanitizer caches at the wrong path.** The sanitizer image warms RapidOCR and Docling model caches into `/opt/models` (`XDG_CACHE_HOME` / `HF_HOME`), but `compose.yaml` mounts `sanitizer-rapidocr-cache` at `/home/app/.cache/rapidocr` and `sanitizer-docling-cache` at `/home/app/.cache/docling`. Nothing is written to either volume, so a rebuild re-downloads several hundred MB of model weights. Fix is to remount at `/opt/models` (or split per-library cache dirs and align the Dockerfile).
- **`/api/health` echoes a dead geocoder field.** `nav/navigator/main.py` returns `"geocoder": settings.nominatim_endpoint` in the `/api/health` payload. That field is cosmetic (the UI derives pill text from `window.location.host` and `/api/health/geocoder`), but it's the last remaining reference to Nominatim and will mislead anyone reading a raw `/api/health` response. Rename or drop.
- **`postcode_radius_deg` is dead code.** `nav/navigator/config.py` defines `postcode_radius_deg: float = 0.5`, but no code reads it — `_nearby_services` and `_build_chat_context` compute the SQL bbox from `postcode_radius_km / 111.0`. Safe to delete, or to repurpose if a future caller wants the raw padding.

---

## Where things live

```
compose.yaml   service wiring — the source of truth for container config
sanitizer/     document pipeline, stateless, CLI + HTTP
nav/           navigator FastAPI backend
nav-ui/        React front end (Vite + Tailwind)
```

The Photon service (`rtuszik/photon-docker:latest`) is defined in `compose.yaml` and its index lives in the `photon-data` volume. It is the only geocoder — Nominatim is not part of the stack.

The sanitizer container should be built with `--secret id=hf_token` only if `INSTALL_TOKENIZER=1` — the tokenizer is not needed for correctness, only for tight prompt budgets.

The navigator's SQLite file lives at `/data/navigator.db` in the container (`NAVIGATOR_DATABASE_URL`). It is the only durable state in the whole system — back it up, or accept that the directory is disposable.

