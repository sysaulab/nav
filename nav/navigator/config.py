from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./navigator.db"

    # Private Nominatim instance (used for address → lat/lng).
    nominatim_endpoint: str = "http://127.0.0.1:8080"

    # Private Photon instance (used for address → lat/lng).
    photon_endpoint: str = "http://127.0.0.1:2322"

    session_purge_interval_s: int = 30

    # ── interview upload / sanitizer proxy ──────────────────
    sanitizer_endpoint: str = "http://127.0.0.1:8000/ingest"   # ← canonical
    sanitizer_timeout_s: float = 600.0
    max_upload_bytes: int = 100 * 1024 * 1024
    

    # ── chat backend (Ollama) ───────────────────────────────
    ollama_endpoint: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:cloud"
    ollama_timeout_s: float = 600.0

    # ── final plan (Ollama) ─────────────────────────────────
    final_model: str = "beam:cloud"
    final_timeout_s: float = 600.0

    # ── location / nearby services ──────────────────────────
    postcode_radius_deg: float = 0.5
   
    # ── location / nearby services ──────────────────────────
    postcode_radius_km: float = 25.0
    nearby_location_limit: int = 20    # locations listed in the prompt
    nearby_index_limit: int = 100      # total services in the index

    # ── document context budget ─────────────────────────────
    # 256K context − 32K generation − ~4K base prompt.
    document_budget_tokens: int = 220_000
    max_documents_per_session: int = 50
    session_idle_minutes: int = 15

    # Tokenizer used for accurate estimation. Falls back to chars/3.5 if
    # transformers is missing or the model isn't cached.
    tokenizer_model: str = "google/gemma-2-2b-it"

    model_config = SettingsConfigDict(env_prefix="NAVIGATOR_", extra="ignore")