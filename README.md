# Local Resource Navigator — README

Two services that help a caseworker connect a client to local services. The **sanitizer** turns documents into canonical JSON. The **navigator** runs the interview, keeps per-visitor state, and orchestrates the LLM. A React front end sits on top of the navigator, and a separate React admin UI manages the directory and model registry.

```
browser ──► nav-ui (nginx :80) ──► nav (FastAPI :8001) ──► Postgres (postgres:5432)
                                        │
                                        ├──► sanitizer (FastAPI :8000)  ← document uploads
                                        ├──► photon (:2322)             ← address → lat/lng
                                        └──► Ollama                     ← chat + finalize

operator ──► nav-admin (nginx :8008) ──► nav /admin-api/* (bearer token)
```

The sanitizer is stateless — no sessions, no cookies, no LLM. The navigator is stateful — it owns the directory DB, sessions, uploaded-document metadata, and the model registry. Postgres is the single durable store.

---

## INSTALL — what you need first

On the host:

- **Docker Engine + Compose v2.**
- **Ollama** running on the host, reachable at `host.docker.internal:11434`. Pull the models the running stack will actually ask for. The effective model is chosen by the model registry, not by env vars, so the right pair depends on how you start:

  ```bash
  # Under `docker compose up` (compose.yaml seeds the registry):
  #   default chat     = ollama-gemma4-cloud  → gemma4:cloud
  #   default finalize = ollama-gemma4-cloud  → gemma4:cloud
  ollama pull gemma4:cloud

  # Running `python -m navigator` standalone (hardcoded defaults in ai/registry.py):
  #   default chat     = ollama-local  → gemma2:2b
  #   default finalize = ollama-local  → gemma2:2b
  ollama pull gemma2:2b
  ```

  To use a different model, edit it in **nav-admin** (:8008 → Models) or seed it via `NAVIGATOR_DEFAULT_CHAT_MODEL_ID` / `NAVIGATOR_DEFAULT_FINALIZE_MODEL_ID` / `NAVIGATOR_MODELS_JSON`. `NAVIGATOR_OLLAMA_MODEL` and `NAVIGATOR_FINAL_MODEL` are vestigial — they only appear in the informational `/api/health` payload and do not affect which model the chat and finalize paths dial.

- **A Photon instance.** `compose.yaml` includes one (`rtuszik/photon-docker` with a prebuilt Canada index on first boot — allow time and disk; the planet index is ~60 GB, "canada" is far smaller). If you're bringing your own, point `NAVIGATOR_PHOTON_ENDPOINT` at it. Photon is the only geocoder; Nominatim is not part of the stack.
- **~4 GB RAM** on first ingest, for the sanitizer's OCR + docling model caches. Steady-state is much lower.

No host Python, no host Node, no host pandoc.

---

## INSTALL — bring it up

```bash
git clone <repo> && cd <repo>
docker compose up --build -d
```

First build takes several minutes:

- `sanitizer` installs CPU-only torch, then warms RapidOCR + Docling model caches into `/opt/models` (a few hundred MB). The named volume `sanitizer-model-cache` is mounted there so the weights survive a rebuild.
- `nav-ui` runs a Vite build, then copies `dist/` into nginx.
- `nav-admin` runs a Vite build, then copies `dist/` into nginx (published on :8008).
- `nav` is a small install. It **will not start** without `NAVIGATOR_DATABASE_URL`, which `compose.yaml` sets; running the image standalone requires you to supply it.

Check status:

```bash
docker compose ps                       # all services "running"
docker compose logs -f nav              # follow the navigator
docker compose logs -f postgres         # if nav fails to connect
```

Open **`http://localhost`** — that's the public UI. Open **`http://localhost:8008`** for the admin UI; sign in with the `NAVIGATOR_ADMIN_TOKEN` set in your `.env` (compose default: `dev-admin-token-change-me`). The status pills at the bottom of the welcome page should turn green for `nav`, `doc`, `geo`, `llm`, and `sql`. A pill that stays red names the endpoint it failed to reach; that's the fastest way to spot a mis-set environment variable.

---

## INSTALL — smoke test

1. **Welcome page.** Five green pills. If `doc` is red, the sanitizer isn't up — `docker compose logs sanitizer`. If `llm` is red, Ollama on the host isn't reachable — `docker compose logs nav | grep ollama`. The `sql` pill's detail shows the backend name; on the compose stack it reads `postgresql`.
2. **`/interview`.** You should land on the location gate ("Where are you located?"). Type a postal code — the autocomplete should populate from `geo`. Pick one.
3. **Upload a PDF.** Any small one. It should appear in the Documents panel with a token count, and the "context budget" bar should move.
4. **Send a chat turn.** The assistant should respond. If it hangs, `llm` is unreachable or the model name in the registry is wrong.
5. **Finish.** The plan renders in the green box; **"📄 Office"** produces a valid `.docx` (exercises the pandoc subprocess on the nav host). "📄 Markdown" downloads the raw plan.
6. **Close the tab, reopen.** The same session is resumed from the `nav_session` cookie, provided the row is still `active` and hasn't crossed its `expires_at` deadline. A fresh session is only minted if the cookie is missing or the row is gone/expired. To force a fresh session, clear the cookie; the purger deletes the orphaned row within ~30 s of expiry.
7. **Admin UI.** `http://localhost:8008` → sign in with your admin token. Models tab should list `ollama-gemma4-cloud` (marked as the chat and finalize default) and `ollama-local`. Directory tab should list whatever organizations exist in the DB (empty on a fresh install). Backup tab should download a JSON snapshot.

If all seven pass, you have a working install. If any fail, the failure names the layer.

---

## INSTALL — dev mode (no Docker)

When you're editing the code and want hot reload. **Note the Python versions differ**: the navigator runs on 3.11+, but the sanitizer's `officemd==0.1.8` requires **3.12** wheels. Use separate virtualenvs.

**Postgres** (port 5432), easiest as a container:
```bash
docker run -d --name nav-postgres -p 127.0.0.1:5432:5432 \
    -e POSTGRES_USER=navigator \
    -e POSTGRES_PASSWORD=dev-only-change-me \
    -e POSTGRES_DB=navigator \
    -v nav-pgdata:/var/lib/postgresql/data \
    postgres:16-alpine
```

**Sanitizer** (port 8000):
```bash
cd sanitizer
python3.12 -m venv .venv && . .venv/bin/activate
sudo apt-get install -y libmagic1 libgl1 libglib2.0-0 libgomp1 libreoffice-nogui fonts-liberation
pip install -r requirements.txt
python -m app.main --host 127.0.0.1 --port 8000
```

**Navigator** (port 8001):
```bash
cd nav
python3.11 -m venv .venv && . .venv/bin/activate
sudo apt-get install -y pandoc                                   # for DOCX export
pip install -e .
NAVIGATOR_DATABASE_URL=postgresql+asyncpg://navigator:dev-only-change-me@127.0.0.1:5432/navigator \
NAVIGATOR_SANITIZER_ENDPOINT=http://127.0.0.1:8000/ingest \
NAVIGATOR_PHOTON_ENDPOINT=http://127.0.0.1:2322 \
NAVIGATOR_OLLAMA_ENDPOINT=http://127.0.0.1:11434 \
python -m navigator --host 127.0.0.1 --port 8001
```

`NAVIGATOR_DATABASE_URL` is **required**. There is no SQLite fallback — `Settings()` raises at construction if the env var is unset (or `--db-url` isn't passed), which is what makes the failure mode loud instead of silent.

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

**Admin UI** (port 5174, hot reload):
```bash
cd nav-admin
npm install
npm run dev
# Vite proxies /admin-api → http://127.0.0.1:8001 (see vite.config.ts)
```

Open `http://localhost:5173` for the public UI and `http://localhost:5174` for the admin. Same smoke test applies. On macOS the `apt-get` lines don't apply — `brew install libmagic pandoc` covers both.

---

## The navigator is multi-session by design

Every visitor gets their own `InterviewSession` row, created on demand and identified by an httpOnly cookie (`nav_session`). The session ID is a UUID; it acts as a bearer token, and every authenticated endpoint re-checks that the request's cookie matches the row it's about to touch.

Each session owns, independently: its origin (postal code, lat/lng, short display name), its **fixed, distance-ordered nearby-services index** (`nearby_service_ids`), its set of expanded service entries (`revealed_service_indices`), its uploaded documents (FK with `ondelete="CASCADE"`), and its sliding `expires_at` deadline.

Nothing is global except the service directory itself and the model registry — and the registry is read-only per chat turn, mutated only by admin routes.

---

## Session lifecycle

**Create or resume.** `POST /interviews` looks for the cookie. If the row exists, is `active`, and hasn't expired, it slides the deadline forward and returns it. If the cookie points at a dead row, that row is deleted and a fresh one is minted.

**Location gate.** Chat and finalize refuse to run until a postal code has been resolved to lat/lng. Setting the location rebuilds the nearby-services index in one transaction — both `nearby_service_ids` and `revealed_service_indices` are reset together, so `[07]` never means a different service before and after a move.

**Sliding TTL.** Every authenticated request extends `expires_at` by `session_idle_minutes` (default 15). A session goes `expired` when the deadline has passed *and* a request arrives — but the purge loop sweeps it independently.

**Background purge.** A startup task loops every `session_purge_interval_s` (default 30 s) and deletes rows whose `expires_at` is in the past. Deletion cascades away the session's documents. Each tick uses Postgres advisory lock `920111` (`pg_try_advisory_xact_lock`) so that only one replica purges per interval when the navigator is scaled.

**End.** `DELETE /interviews/{sid}` deletes the row (and its documents) immediately, provided the cookie matches.

---

## Isolation guarantees

- **No cross-session reads.** Every endpoint that takes a `{sid}` path parameter compares it against the request's cookie *before* loading the row. A guess at another visitor's UUID returns 404, not a leak.
- **No cross-session writes.** Document uploads are scoped by `session_id` on the row; chat and finalize re-derive context from the row identified by the cookie, not from client-supplied state.
- **Documents die with their session.** `ondelete="CASCADE"` on `SessionDocument.session_id` is enforced natively by Postgres.
- **Prompt context is per-session.** `_build_chat_context` re-queries documents, origin, and nearby services fresh for every chat turn. There is no shared prompt state.
- **Admin routes are bearer-gated.** Everything under `/admin-api/*` requires `Authorization: Bearer <NAVIGATOR_ADMIN_TOKEN>`. If `NAVIGATOR_ADMIN_TOKEN` is unset, every admin call returns 503 — the admin surface is unavailable, not open.

---

## Concurrency model

The navigator handles many sessions concurrently in **one event loop, one process**. `uvicorn.run(create_app(...), ...)` in `nav/navigator/main.py` passes no `workers` argument, so it defaults to 1. Concurrency comes from asyncio, not from multiple processes.

That's the correct shape for this workload: almost everything blocking lives off-process — Postgres via asyncpg, the sanitizer via httpx, Photon via httpx, Ollama via httpx, pandoc via `asyncio.create_subprocess_exec`. The event loop stays responsive because no handler holds the GIL for long.

Three intentional serialization points:

**1. Postgres connections.** `create_async_engine` is configured with `pool_size=5`, `max_overflow=5`, `pool_recycle=1800`, `pool_timeout=30`, `pool_pre_ping=True`. Each navigator process holds at most 10 connections. If you scale the `nav` service to N replicas, ensure `N × 10 < postgres.max_connections` (Postgres's default is 100). `pool_recycle=1800` runs before Postgres's idle timeout can drop a connection under us; `pool_pre_ping` catches stale connections after a Postgres restart.

**2. Sanitizer ingest.** `_ingest_lock = threading.Lock()` in `sanitizer/app/main.py` serializes `/ingest` across the process. Two concurrent uploads from two sessions queue. Deliberate: it bounds peak memory to one ingest's working set. The cost is real — one caseworker uploading while another uploads waits. `/health` and `/ready` are intentionally outside the lock so a hung ingest can't make liveness hang with it.

**3. Ollama inference.** Ollama serves one generation at a time per model. Two sessions chatting simultaneously queue at Ollama. The navigator doesn't try to serialize this itself — Ollama is the source of truth for that constraint.

Three Postgres advisory locks coordinate across replicas if the `nav` service is scaled:

| Key | Purpose | Location |
|---|---|---|
| `920110` | Schema creation (`CREATE TABLE IF NOT EXISTS …`) | `main.py` at startup |
| `920111` | Session purge (one replica purges per tick) | `main.py` `_purge_expired_sessions` |
| `920112` | Directory import (serializes concurrent backup restores) | `routers/exports.py`, `routers/admin.py` |

---

## What is per-session vs shared

| | Per-session | Shared |
|---|---|---|
| Database | `InterviewSession` row, `SessionDocument` rows | `Organization`, `Location`, `Service`, `ServiceAtLocation`, `AppSetting` |
| Coordinates | `origin_lat`, `origin_lng` | (address → coords lookup is stateless) |
| Nearby services | `nearby_service_ids`, `revealed_service_indices` | Service rows themselves |
| Document payloads | `SessionDocument.payload_json` | (sanitizer has no retained state) |
| LLM context | Built fresh per request from the session row | (Ollama is stateless per request) |
| Model registry | (read-only snapshot, refreshed on admin writes) | `AppSetting` rows `model.*`, `default.chat`, `default.finalize` |
| Cookie | `nav_session` per browser | (n/a) |

---

## The interview flow, end to end

1. Browser loads `/`, sees status pills populated from `/api/health*` — each pill reports the actual endpoint the backend dialed (the `sql` pill shows the backend name, currently `postgresql`).
2. Opens `/interview`. `POST /interviews` creates a session and sets the cookie.
3. Location gate: debounced autocomplete against `/api/geocode/search` (Photon); the chosen candidate is posted to `/interviews/{sid}/location`, which geocodes (or trusts the candidate), builds the nearby-services index, and resets `revealed_service_indices`.
4. Uploads: multipart POST to `/interviews/{sid}/documents`, forwarded to the sanitizer, filtered, token-estimated, stored. Per-document status (`ready`, `skipped_too_large`, `quarantine`) is surfaced in the UI alongside a live token-budget bar.
5. Chat: `POST /interviews/{sid}/chat` streams NDJSON from the registry's default chat model with a `get_service_details(index)` tool. Tool results stay server-side; expanded services are also promoted into the next turn's system prompt so the model doesn't re-request them.
6. Finalize: `POST /interviews/{sid}/finalize` reuses the same context assembly against a different base prompt and the registry's default finalize model. The plan streams back the same way.
7. Export: `/api/export/docx` pipes the plan's Markdown through pandoc (stdin → stdout, `-o -`, no temp files) for a `.docx` download.
8. Admin: `http://localhost:8008` hits `/admin-api/*` with `Authorization: Bearer <NAVIGATOR_ADMIN_TOKEN>`. Its Models tab reads and writes the model registry (`AppSetting` rows); its Directory tab drives the org/location/service/phone CRUD endpoints; its Backup tab drives `/admin-api/database/export` and `/admin-api/database/import`. Any admin write to a model or default calls `reload_registry` so the next chat turn sees the change without a restart.

Any step that 404s/409s/410s a session (cookie missing, expired, ended, purged) drives the front end to the "session expired" modal rather than a generic error.

---

## Model registry

Chat and finalize models are **not** chosen by env vars anymore. The active model is resolved at startup and refreshed on every admin write via `nav/navigator/ai/registry.py`.

Resolution order, per model id:
1. **Hardcoded** (`_HARDCODED_SPECS` in `ai/registry.py`): `ollama-local` (gemma2:2b) and `ollama-gemma4-cloud` (gemma4:cloud).
2. **Env seed** (`NAVIGATOR_MODELS_JSON`): overrides any hardcoded id, adds new ids.
3. **Database** (`AppSetting` rows `model.<id>`): overrides any env or hardcoded id per-id.

Defaults resolve similarly: hardcoded → env (`NAVIGATOR_DEFAULT_CHAT_MODEL_ID` / `NAVIGATOR_DEFAULT_FINALIZE_MODEL_ID`) → DB (`AppSetting` `default.chat` / `default.finalize`). A default that doesn't point at a registered model falls back to the hardcoded default with a warning.

Admin writes go through `set_app_setting` (which JSON-encodes the value and commits immediately) then call `reload_registry` so the next request uses the new state. This means the effective model is whatever the operator last set in nav-admin — the env vars only seed the initial state.

`NAVIGATOR_OLLAMA_MODEL` and `NAVIGATOR_FINAL_MODEL` are legacy. They only surface in the informational `/api/health` response; nothing on the chat or finalize hot path reads them.

The model spec carries the two numbers every prompt-budget calculation derives from:

```python
@dataclass(frozen=True)
class ModelSpec:
    id: str
    module: str                      # "ollama" | "openai"
    endpoint: str
    model: str
    context_window: int
    max_output_tokens: int
    label: str
    api_key_env: str | None = None
    enabled: bool = True

    @property
    def budget_tokens(self) -> int:
        return max(0, self.context_window - self.max_output_tokens)
```

The chat prompt budget (`NAVIGATOR_DOCUMENT_BUDGET_TOKENS`) is a ceiling on the document portion; the actual prompt is the assembled base + documents + session context + nearby-services block, and the model spec's `budget_tokens` is what the context bar's "reserved for reply" segment shows.

---

## Configuration

Everything env-driven; `NAVIGATOR_` prefix on the navigator, `SANITIZER_` prefix on the sanitizer. `compose.yaml` is the source of truth for what's actually set in the container; the table below lists what the code *reads* and what happens if it's absent.

Navigator defaults worth knowing (from `nav/navigator/config.py`):

| Setting | Default | Meaning |
|---|---|---|
| `NAVIGATOR_DATABASE_URL` | **required** | Postgres DSN. No default — `Settings()` raises at construction if unset. Example: `postgresql+asyncpg://navigator:pw@postgres:5432/navigator` |
| `NAVIGATOR_SANITIZER_ENDPOINT` | `http://127.0.0.1:8000/ingest` | Sanitizer POST target |
| `NAVIGATOR_SANITIZER_TIMEOUT_S` | `600` | Per-upload timeout |
| `NAVIGATOR_PHOTON_ENDPOINT` | `http://127.0.0.1:2322` | Geocoder base URL |
| `NAVIGATOR_OLLAMA_ENDPOINT` | `http://127.0.0.1:11434` | Ollama base URL (used when the model spec's endpoint is empty) |
| `NAVIGATOR_OLLAMA_MODEL` | `gemma4:e4b` | **Legacy.** Informational only — appears in `/api/health`, never consulted by chat. |
| `NAVIGATOR_OLLAMA_TIMEOUT_S` | `600` | **Legacy.** Unused by the model registry. |
| `NAVIGATOR_FINAL_MODEL` | `gemma4:e4b` | **Legacy.** Informational only — appears in `/api/health`, never consulted by finalize. |
| `NAVIGATOR_FINAL_TIMEOUT_S` | `600` | **Legacy.** Unused by the model registry. |
| `NAVIGATOR_SESSION_IDLE_MINUTES` | `15` | Sliding TTL per session |
| `NAVIGATOR_SESSION_PURGE_INTERVAL_S` | `30` | Background sweep cadence |
| `NAVIGATOR_MAX_DOCUMENTS_PER_SESSION` | `50` | Per-session upload cap |
| `NAVIGATOR_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) | Per-upload cap, checked before contacting the sanitizer |
| `NAVIGATOR_DOCUMENT_BUDGET_TOKENS` | `220000` | Prompt budget per chat turn |
| `NAVIGATOR_POSTCODE_RADIUS_KM` | `25.0` | Nearby-services radius |
| `NAVIGATOR_NEARBY_LOCATION_LIMIT` | `20` | Locations listed in the system prompt |
| `NAVIGATOR_NEARBY_INDEX_LIMIT` | `100` | Total services in the per-session index |
| `NAVIGATOR_TOKENIZER_MODEL` | `google/gemma-2-2b-it` | Tokenizer used for prompt-budget estimation. Falls back to `chars/3.5` if `transformers` is missing or the model isn't cached. |
| `NAVIGATOR_ADMIN_TOKEN` | `None` | Bearer token for `/admin-api/*`. Unset = admin unavailable (all calls 503). Rotation = change env, restart. |
| `NAVIGATOR_MODELS_JSON` | `None` | JSON array of `ModelSpec` objects to seed the registry |
| `NAVIGATOR_DEFAULT_CHAT_MODEL_ID` | `None` | Seed default chat model id |
| `NAVIGATOR_DEFAULT_FINALIZE_MODEL_ID` | `None` | Seed default finalize model id |

Sanitizer defaults (see `sanitizer/README.md`): `SANITIZER_MAX_UPLOAD_BYTES = 100 MiB`, `SANITIZER_MAX_PAGES = 500`, `SANITIZER_LOW_CONFIDENCE_THRESHOLD = 0.65`. All safety valves, not functional constraints.

CLI flags for `python -m navigator` (`nav/navigator/main.py`): `--host`, `--port`, `--db-url`, `--ingest-server-endpoint`, `--photon-endpoint`. Each `--*` flag is an override on top of the env-derived `Settings()`. `--db-url` is how a dev run can supply a database URL without setting the env var.

---

## Known limits

- **One navigator process is the current deployment shape.** `uvicorn.run` in `create_app` doesn't pass `workers`, so it defaults to 1. Postgres makes horizontal scaling possible (advisory locks handle the two cross-replica concerns: schema creation and the purge loop), but scaling needs `N × 10 < postgres.max_connections` and hasn't been load-tested.
- **Uploads serialize.** Two concurrent uploads from different sessions queue at the sanitizer. This is the main user-facing cost of the current architecture.
- **No auth on the sanitizer.** It's intended to be reachable only by the navigator. Never publish it on a public interface.
- **Sessions die hard.** No "recover an ended session" — the cascade is real, and the UI has no affordance for it.
- **The tokenizer heuristic is conservative.** Falls back to `chars / 3.5` if `transformers` is unavailable or the model isn't cached. Over-estimation excludes a document early; under-estimation would truncate output, so the heuristic under-divides on purpose.
- **The provider plugin system isn't wired in yet.** The code under `nav/navigator/providers/` (registry, base, regions, local, c211) exists and is importable, but `load_builtin_providers()` is never called by `create_app`, and the chat flow still resolves services directly against the local DB via `_nearby_services`. The `providers/c211.py` skeleton references `settings.c211_base_url`, which is not a field on `Settings` — that provider would fail on first use. This is deliberate: the plugin surface is stable, the connector is unfinished. See `TODO-211-plugin.md`.

---

## Where things live

```
compose.yaml   service wiring — the source of truth for container config
sanitizer/     document pipeline, stateless, CLI + HTTP
nav/           navigator FastAPI backend (session state, model registry, admin API)
nav-ui/        public React front end (Vite + Tailwind, served by nginx :80)
nav-admin/     admin React front end (Vite + Tailwind, served by nginx :8008)
```

Durable state is **Postgres** (`pgdata` volume). The `photon-data` volume holds Photon's index. The `sanitizer-model-cache` volume holds the sanitizer's OCR and docling weights. Losing Postgres means losing the directory, the sessions, and the model registry — everything else can be rebuilt from the images. Back up `pgdata`, or use `/admin-api/database/export` (or nav-admin → Backup) to snapshot the directory alone.