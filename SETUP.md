# Services

Five processes, in roughly this order. The first three are independent;
navigator depends on all of them; the web UI depends on navigator.

  11434  ollama         (LLM inference — chat + final plan)
   8000  sanitizer      (upload → structured text)
   2322  photon         (postal code / address → lat,lng)
   8001  navigator      (API + session state)
   5173  nav-ui         (dev server, proxies /api → 8001)

> **`docker compose up` is the canonical install.** This document covers
> running the services by hand for development — hot reload, per-service
> logs, editing without a rebuild. If you just want a working stack,
> follow the INSTALL section of `README.md` instead. Everything below
> produces the same process topology as `compose.yaml`, just without the
> container boundary around each service.

> **Privacy note.** The default models the navigator dials
> (`gemma4:cloud`, `beam:cloud` standalone; `gemma4:cloud`,
> `nemotron-3-ultra:cloud` under compose) are Ollama Cloud tags — inference
> happens on Ollama's servers, not on this machine. If you need prompts to
> stay on-device, override `NAVIGATOR_OLLAMA_MODEL` and
> `NAVIGATOR_FINAL_MODEL` with a locally-runnable model (e.g. `gemma3:4b`,
> `granite3.2:8b`, or an MLX quant on Apple Silicon) and accept the
> quality/latency trade-off.

---

# ollama

Used directly by navigator for two models. Which two depends on how you
start the navigator:

| Startup path | Chat model | Final-plan model |
|---|---|---|
| `docker compose up` | `gemma4:cloud` | `nemotron-3-ultra:cloud` (compose overrides the config default) |
| Standalone (`python -m navigator`) | `gemma4:cloud` | `beam:cloud` (config default) |

Pull the pair that matches how you'll run it:

```bash
# For `docker compose up`:
ollama pull gemma4:cloud
ollama pull nemotron-3-ultra:cloud

# For standalone dev mode:
ollama pull gemma4:cloud
ollama pull beam:cloud
```

Note that the `:cloud` suffix routes inference to Ollama Cloud — a real
account is required and prompts leave this machine. `ollama ps` during a
chat will show a "remote" model with no local VRAM footprint. For fully
local inference, pull any non-cloud Gemma-family model for chat and any
instruction-tuned model for the final plan, then override at launch:

```bash
NAVIGATOR_OLLAMA_MODEL=gemma3:4b \
NAVIGATOR_FINAL_MODEL=granite3.2:8b \
    python3 -m navigator --port 8001
```

(Or the equivalent `NAVIGATOR_OLLAMA_MODEL` / `NAVIGATOR_FINAL_MODEL`
entries in `compose.yaml` if you're on the compose path.)

Start the server if it's not already running:

```bash
ollama serve            # or launch the app
```

---

# sanitizer

Stateless document pipeline: upload → text + layout + confidence → canonical
JSON. Its port must match `sanitizer_endpoint` in
`nav/navigator/config.py` (default `http://127.0.0.1:8000/ingest`).

```bash
python3 -m app.main                     # server on :8000
python3 -m app.main <file>              # one-shot: sanitize a file, JSON to stdout
```

The `--help` output documents the CLI contract — exit codes, the
"one FILE per invocation" rule, and the warnings emitted when extra
positionals or `--host`/`--port` are passed in file mode. The `file` mode
is useful for debugging uploads without the navigator in the loop — same
code path, same output shape.

Note the sanitizer requires **Python 3.12** (`officemd==0.1.8` ships
cp312 wheels only). If your default `python3` is 3.11, create a 3.12
virtualenv specifically for this service — the navigator can stay on 3.11.

---

# photon

Fuzzy geocoder. Handles the postal-code gate in the UI and
`/api/geocode` / `/api/geocode/search`. **Nominatim is not part of the
stack** — the navigator's default geocoder is Photon at
`http://127.0.0.1:2322`.

Photon runs from a community image (`rtuszik/photon-docker`), which
downloads a prebuilt regional index on first boot. Docker is the path of
least resistance.

First run (downloads the index, tens of minutes for `canada`, much longer
for `planet`):

```bash
docker run -d \
  --name photon \
  -p 2322:2322 \
  -e REGION=canada \
  -e UPDATE_STRATEGY=DISABLED \
  -v photon-data:/photon/data \
  rtuszik/photon-docker:latest
```

Subsequent runs:

```bash
docker start photon
```

`REGION=canada` uses a prebuilt country index (~few GB) instead of the
planet index (~60 GB). If `canada` isn't offered in your release of the
image, substitute `north-america` — either is far smaller than planet.

`UPDATE_STRATEGY=DISABLED` stops the container from silently re-downloading
the index behind your back; the index is rebuilt only when you ask for it.

Health check once it's up:

```bash
curl 'http://127.0.0.1:2322/api?q=V6B&limit=5'
```

Override the endpoint with `NAVIGATOR_PHOTON_ENDPOINT` if not on 2322.
There is no CLI flag for it — env var only.

---

# navigator

FastAPI app. SQLite in WAL mode. Session state, document metadata, and
the two streaming proxies (chat + finalize) live here.

Install (from `nav/`):

```bash
python3 -m pip install -e .
```

That installs every runtime dependency from `pyproject.toml` — fastapi,
uvicorn, sqlalchemy, aiosqlite, pydantic, pydantic-settings, httpx,
python-multipart. Add `[tokenizer]` to get the real HF tokenizer for
prompt-budget estimation instead of the chars/3.5 fallback:

```bash
python3 -m pip install -e ".[tokenizer]"
```

Run (from `nav/`, i.e. the directory containing `navigator/`):

```bash
python3 -m navigator --port 8001
```

`-m navigator` executes `navigator/__main__.py`. Do not run
`python3 navigator/main.py` — that bypasses the package, and the
relative imports (`from .config import ...`) fail with
"attempted relative import with no known parent package".

## Pick one Python interpreter

On systems with multiple Pythons (Homebrew, pkgsrc, python.org, Xcode
CLT), `python3` and `pip3` often resolve to *different* installs. Symptoms:
`pip3 install foo` reports success, then `python3 -m navigator` raises
`ModuleNotFoundError: No module named 'foo'`.

Diagnose:

```bash
which python3 ; which pip3
python3 -c "import sys; print(sys.executable)"
pip3 --version
```

If the paths differ, always pair the install and the run under the same
interpreter using `-m`:

```bash
python3 -m pip install -e .     # goes where `python3` can see it
python3 -m navigator            # runs under that same interpreter
```

A venv sidesteps the whole problem:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e nav
python -m navigator --port 8001
```

## Configuration

All settings are env-overridable with the `NAVIGATOR_` prefix (see
`nav/navigator/config.py` for the full list). Common knobs:

    NAVIGATOR_OLLAMA_MODEL              default gemma4:cloud
    NAVIGATOR_FINAL_MODEL               default beam:cloud
    NAVIGATOR_OLLAMA_ENDPOINT           default http://127.0.0.1:11434
    NAVIGATOR_PHOTON_ENDPOINT           default http://127.0.0.1:2322
    NAVIGATOR_SANITIZER_ENDPOINT        default http://127.0.0.1:8000/ingest
    NAVIGATOR_POSTCODE_RADIUS_KM        default 25.0
    NAVIGATOR_NEARBY_LOCATION_LIMIT     default 20
    NAVIGATOR_NEARBY_INDEX_LIMIT        default 100

Under `docker compose up`, `compose.yaml` overrides
`NAVIGATOR_FINAL_MODEL` to `nemotron-3-ultra:cloud` and sets
`NAVIGATOR_PHOTON_ENDPOINT` / `NAVIGATOR_OLLAMA_ENDPOINT` to the
in-container DNS names (`http://photon:2322`,
`http://host.docker.internal:11434`). The values above are what the
code falls back to when nothing overrides them.

CLI flags override env vars: `--host`, `--port`, `--db-url`,
`--ingest-server-endpoint`. One caveat — `--nominatim-endpoint` also
exists as a flag, but `nominatim_endpoint` is vestigial: it's echoed in
`/api/health` and nowhere else. Setting it does not change what the
geocoder does. See the "Known issues in the current tree" section of
`README.md` for details, plus a handful of related Dockerfile and
compose discrepancies worth knowing before you debug a mis-set
environment variable.

Two settings you might see referenced but that aren't on the hot path:

- `NAVIGATOR_NOMINATIM_ENDPOINT` — dead (geocoding goes through Photon).
- `NAVIGATOR_POSTCODE_RADIUS_DEG` — dead (only `POSTCODE_RADIUS_KM` is read).

---

# nav-ui

Vite + React dev server. Proxies `/api/*` to `127.0.0.1:8001`
(see `nav-ui/vite.config.ts`) so the browser only ever talks to one origin.

```bash
cd nav-ui
npm install
npm run dev                     # http://localhost:5173
```

Production build:

```bash
npm run build                   # tsc --noEmit && vite build → nav-ui/dist/
```

Under `docker compose up`, the UI is served by nginx on port **80**
(`http://localhost`), not 5173 — the Vite dev server and the nginx
production build are two different entry points.

---

# Boot order & sanity check

```bash
# 1. ollama (background)
ollama serve &

# 2. sanitizer
(cd sanitizer && python3 -m app.main) &

# 3. photon (docker; first run downloads the index)
docker start photon        # or `docker run -d --name photon ...` first time

# 4. navigator
(cd nav && python3 -m navigator --port 8001) &

# 5. nav-ui
(cd nav-ui && npm run dev) &
```

Quick check that everything is reachable:

```bash
curl -s http://127.0.0.1:11434/api/tags                     | head
curl -s http://127.0.0.1:8000/health                        | head
curl -s "http://127.0.0.1:2322/api?q=V6B&limit=5"           | head
curl -s http://127.0.0.1:8001/api/health
```

The last one reports the sanitizer and geocoder reachability as seen *by
the navigator*. If `/api/health` returns 200 but `/api/health/ingest` or
`/api/health/geocoder` reports `"ok": false`, those two upstreams are
down — the Welcome page will show matching red pills.

Then open <http://localhost:5173> and pick "Get Help!".


