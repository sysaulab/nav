from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Required — no SQLite fallback. If NAVIGATOR_DATABASE_URL is unset
    # (or --db-url not passed on the CLI), Settings() raises at construction
    # and the app refuses to start. That's deliberate: a silent SQLite file
    # is worse than a startup failure, because it hides the fact that the
    # operator didn't configure the deployment.
    database_url: str

    # Private Photon instance (used for address → lat/lng).
    photon_endpoint: str = "http://127.0.0.1:2322"

    session_purge_interval_s: int = 30

    # ── interview upload / sanitizer proxy ──────────────────
    sanitizer_endpoint: str = "http://127.0.0.1:8000/ingest"   # ← canonical
    sanitizer_timeout_s: float = 600.0
    max_upload_bytes: int = 100 * 1024 * 1024

    # ── chat backend (Ollama) ───────────────────────────────
    # These are legacy: chat and finalize route through the model
    # registry now (see ai/registry.py). Kept for the /api/health
    # endpoint's informational response and for backwards compat
    # with older compose files that still set them.
    ollama_endpoint: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:e4b"
    ollama_timeout_s: float = 600.0

    final_model: str = "gemma4:e4b"
    final_timeout_s: float = 600.0

    # ── location / nearby services ──────────────────────────
    postcode_radius_km: float = 25.0
    nearby_location_limit: int = 20
    nearby_index_limit: int = 100

    # ── document context budget ─────────────────────────────
    # 256K context − 32K generation − ~4K base prompt.
    document_budget_tokens: int = 220_000
    max_documents_per_session: int = 50
    session_idle_minutes: int = 15

    # Tokenizer used for accurate estimation. Falls back to chars/3.5 if
    # transformers is missing or the model isn't cached.
    tokenizer_model: str = "google/gemma-2-2b-it"

    # ── admin ────────────────────────────────────────────────
    # Bearer token for /admin-api/*. Unset = admin unavailable (all
    # /admin-api calls return 503). Rotation = change env, restart.
    admin_token: str | None = None

    # ── model registry seeds ─────────────────────────────────
    # Layered under DB settings; DB wins per-id. See ai/registry.py.
    # Env var names are auto-prefixed: NAVIGATOR_MODELS_JSON,
    # NAVIGATOR_DEFAULT_CHAT_MODEL_ID, NAVIGATOR_DEFAULT_FINALIZE_MODEL_ID.
    models_json: str | None = None
    default_chat_model_id: str | None = None
    default_finalize_model_id: str | None = None

    model_config = SettingsConfigDict(env_prefix="NAVIGATOR_", extra="ignore")