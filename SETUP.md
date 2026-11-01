# Services

Five processes, in roughly this order. The first three are independent;
navigator depends on all of them; the web UI depends on navigator.

  11434  ollama         (LLM inference — chat + final plan)
   8000  ingest-server  (sanitizer: upload → structured text)
   8080  nominatim      (postal code / address → lat,lng)
   8001  navigator      (API + session state)
   5173  web-ui         (dev server, proxies /api → 8001)


# ollama

Used directly by navigator for two models:

  gemma4:e4b-mlx     chat
  granite4.2:9b      final action plan

Both run locally on Apple Silicon via MLX — nothing leaves the machine.
The `-mlx` tag is the on-device quant; a bare `:cloud` suffix routes to
Ollama's servers instead. Verify with `ollama ps` during a chat: a real
local model shows a VRAM footprint.

    ollama serve            # or launch the app
    ollama pull gemma4:e4b-mlx
    ollama pull granite4.2:9b

Community tags come and go. If a pull 404s, substitute any Gemma-family
model for chat and any instruction-tuned model for the final plan, then
override at launch:

    NAVIGATOR_OLLAMA_MODEL=gemma3:4b \
    NAVIGATOR_FINAL_MODEL=granite3.2:8b \
        python3 -m navigator


# ingest-server

Sanitizer. Receives a document, extracts text + layout, returns canonical
JSON. Its port must match `sanitizer_endpoint` in `nav-server/navigator/config.py`
(default `http://127.0.0.1:8000/ingest`).

    python3 main.py                 # starts the server on :8000
    python3 main.py <file>          # one-shot: sanitize a file, print to stdout

The `file` mode is useful for debugging uploads without the navigator in
the loop — same code path, same output shape.


# nominatim

Private geocoder. Handles the postal-code gate in the UI and the
`/api/geocode` endpoint. Docker is the path of least resistance.

1. Install docker
2. Run the command below (this example loads British Columbia — swap the
   `PBF_URL` / `REPLICATION_URL` for another region if you're elsewhere)
3. Go make coffee
4. Be patient

    docker run -it \
      -e PBF_URL=https://download.geofabrik.de/north-america/canada/british-columbia-latest.osm.pbf \
      -e REPLICATION_URL=https://download.geofabrik.de/north-america/canada/british-columbia-updates/ \
      -e POSTGRES_SHARED_BUFFERS=4GB \
      -e POSTGRES_EFFECTIVE_CACHE_SIZE=8GB \
      -p 8080:8080 \
      --name nominatim-bc \
      --shm-size=4g \
      -v nominatim-bc-data:/var/lib/postgresql/16/main \
      mediagis/nominatim:5.3

First boot imports the whole extract — tens of minutes for BC. Subsequent
boots are fast; the data lives in the `nominatim-bc-data` volume.

Health check once it's up:

    curl http://127.0.0.1:8080/search?q=V6B&format=json

Override the endpoint with `NAVIGATOR_NOMINATIM_ENDPOINT` if not on 8080.


# navigator

FastAPI app. SQLite in WAL mode. Session state, document metadata, and
the two streaming proxies (chat + finalize) live here.

Install (from `nav-server/`):

    python3 -m pip install -e .

That installs every runtime dependency from `pyproject.toml` — fastapi,
uvicorn, sqlalchemy, aiosqlite, pydantic, pydantic-settings, httpx,
python-multipart. Add `[tokenizer]` to get the real HF tokenizer for
prompt-budget estimation instead of the chars/3.5 fallback:

    python3 -m pip install -e ".[tokenizer]"

Run (from `nav-server/`, i.e. the directory containing `navigator/`):

    python3 -m navigator --port 8001

`-m navigator` executes `navigator/__main__.py`. Do not run
`python3 navigator/main.py` — that bypasses the package, and the
relative imports (`from .config import ...`) fail with
"attempted relative import with no known parent package".

### Pick one Python interpreter

On systems with multiple Pythons (Homebrew, pkgsrc, python.org, Xcode
CLT), `python3` and `pip3` often resolve to *different* installs. Symptoms:
`pip3 install foo` reports success, then `python3 -m navigator` raises
`ModuleNotFoundError: No module named 'foo'`.

Diagnose:

    which python3 ; which pip3
    python3 -c "import sys; print(sys.executable)"
    pip3 --version

If the paths differ, always pair the install and the run under the same
interpreter using `-m`:

    python3 -m pip install -e .     # goes where `python3` can see it
    python3 -m navigator            # runs under that same interpreter

A venv sidesteps the whole problem:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -e nav-server
    python -m navigator --port 8001

### Configuration

All settings are env-overridable with the `NAVIGATOR_` prefix (see
`navigator/config.py` for the full list). Common knobs:

    NAVIGATOR_OLLAMA_MODEL              default gemma4:e4b-mlx
    NAVIGATOR_FINAL_MODEL               default granite4.2:9b
    NAVIGATOR_OLLAMA_ENDPOINT           default http://127.0.0.1:11434
    NAVIGATOR_NOMINATIM_ENDPOINT        default http://127.0.0.1:8080
    NAVIGATOR_SANITIZER_ENDPOINT        default http://127.0.0.1:8000/ingest
    NAVIGATOR_POSTCODE_RADIUS_DEG       default 0.5   (~55 km lat)
    NAVIGATOR_NEARBY_SERVICES_LIMIT     default 20

CLI flags override env vars: `--host`, `--port`, `--db-url`,
`--ingest-server-endpoint`, `--nominatim-endpoint`.


# web-ui

Vite + React dev server. Proxies `/api/*` to `127.0.0.1:8001`
(see `vite.config.ts`) so the browser only ever talks to one origin.

    cd web-ui
    npm install
    npm run dev                     # http://localhost:5173

Production build:

    npm run build                   # tsc --noEmit && vite build → web-ui/dist/


# Boot order & sanity check

    # 1. ollama (background)
    ollama serve &

    # 2. sanitizer
    (cd ingest-server && python3 main.py) &

    # 3. nominatim (docker, one-time import on first run)
    docker start nominatim-bc

    # 4. navigator
    (cd nav-server && python3 -m navigator --port 8001) &

    # 5. web-ui
    (cd web-ui && npm run dev) &

Quick check that everything is reachable:

    curl -s http://127.0.0.1:11434/api/tags                  | head
    curl -s http://127.0.0.1:8000/                          | head
    curl -s "http://127.0.0.1:8080/search?q=V6B&format=json" | head
    curl -s http://127.0.0.1:8001/api/health

The last one reports the sanitizer and geocoder reachability as seen *by
the navigator*. If `/api/health` returns 200 but `/api/health/ingest` or
`/api/health/geocoder` reports `"ok": false`, those two upstreams are
down — the Welcome page will show matching red pills.

Then open http://localhost:5173 and pick "Help a customer".