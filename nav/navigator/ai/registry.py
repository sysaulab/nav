"""Model registry: load specs from DB, env, hardcoded defaults.

Resolution order for the *set of models*:
    hardcoded defaults -> env seed -> database
    Per-id: database wins, then env, then hardcoded.

Resolution order for the *default chat/finalize model id*:
    hardcoded -> env -> database

The database is the operator surface (via nav-admin); env is the
Dockerfile/compose convenience layer; hardcoded is the dev default
for a workstation where the operator has configured nothing.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import AppSetting
from .base import ChatClient, ModelSpec
from .ollama import OllamaClient
from .openai import OpenAIClient

log = logging.getLogger("navigator.ai.registry")


# ── hardcoded dev defaults ───────────────────────────────
# A workstation running `python -m navigator` with no env vars and no
# DB overrides gets these. Endpoints point at localhost — the Docker
# deploy must override via NAVIGATOR_MODELS_JSON (see compose.yaml)
# because localhost inside a container is the container itself.
_HARDCODED_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="ollama-local",
        module="ollama",
        endpoint="http://127.0.0.1:11434",
        model="gemma2:2b",
        context_window=8_192,
        max_output_tokens=2_048,
        label="Ollama local (gemma2:2b)",
    ),
    ModelSpec(
        id="ollama-gemma4-cloud",
        module="ollama",
        endpoint="http://127.0.0.1:11434",
        model="gemma4:cloud",
        context_window=256_000,
        max_output_tokens=8_192,
        label="Gemma 4 (Ollama Cloud)",
    ),
)
_HARDCODED_DEFAULT_CHAT = "ollama-local"
_HARDCODED_DEFAULT_FINALIZE = "ollama-local"


_CLIENT_BY_MODULE: dict[str, ChatClient] = {
    "ollama": OllamaClient(),
    "openai": OpenAIClient(),
}


class ModelRegistry:
    """In-memory snapshot of the resolved registry.

    Built once per process at startup and refreshed by the admin
    routes after every model/setting write. Reads are lock-free —
    handlers get a snapshot reference, not a lock.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ModelSpec] = {}
        self._default_chat: str = _HARDCODED_DEFAULT_CHAT
        self._default_finalize: str = _HARDCODED_DEFAULT_FINALIZE

    # ── load ─────────────────────────────────────────────

    async def load(self, db: AsyncSession, settings: Settings) -> None:
        merged: dict[str, ModelSpec] = {s.id: s for s in _HARDCODED_SPECS}

        if settings.models_json:
            try:
                for raw in json.loads(settings.models_json):
                    spec = ModelSpec.from_dict(raw)
                    merged[spec.id] = spec
            except Exception as e:
                log.warning("registry.env_specs_parse_failed err=%s", e)

        db_specs = await _load_db_specs(db)
        for spec in db_specs.values():
            merged[spec.id] = spec

        # Resolve the defaults against the *new* spec set before publishing
        # anything. The previous shape assigned `self._specs = merged` first,
        # then awaited two settings reads, then assigned `self._default_*`.
        # That left a window where an in-flight chat/finalize handler could
        # call default_chat() and hit `self._specs[self._default_chat]` with
        # the OLD default id against the NEW specs dict — KeyError if an admin
        # had just deleted the model that was previously the default.
        default_chat = (
            await _get_setting(db, "default.chat")
            or settings.default_chat_model_id
            or _HARDCODED_DEFAULT_CHAT
        )
        default_finalize = (
            await _get_setting(db, "default.finalize")
            or settings.default_finalize_model_id
            or _HARDCODED_DEFAULT_FINALIZE
        )

        # Fall back when the configured default isn't in the new registry.
        # Check `merged`, not `self._specs` — nothing has been published yet.
        if default_chat not in merged:
            log.warning(
                "default.chat=%r not in registry; falling back to hardcoded %r",
                default_chat, _HARDCODED_DEFAULT_CHAT,
            )
            default_chat = _HARDCODED_DEFAULT_CHAT
        if default_finalize not in merged:
            log.warning(
                "default.finalize=%r not in registry; falling back to hardcoded %r",
                default_finalize, _HARDCODED_DEFAULT_FINALIZE,
            )
            default_finalize = _HARDCODED_DEFAULT_FINALIZE

        # Publish atomically — no awaits between these three lines. asyncio
        # yields only at await points, so a reader sees all-old or all-new,
        # never a mix.
        self._specs = merged
        self._default_chat = default_chat
        self._default_finalize = default_finalize

        log.info(
            "registry.loaded models=%s default_chat=%s default_finalize=%s",
            sorted(self._specs), default_chat, default_finalize,
        )

    # ── read ─────────────────────────────────────────────

    def all(self) -> list[ModelSpec]:
        return sorted(self._specs.values(), key=lambda s: s.id)

    def all_enabled(self) -> list[ModelSpec]:
        return [s for s in self.all() if s.enabled]

    def get(self, model_id: str) -> ModelSpec | None:
        return self._specs.get(model_id)

    def default_chat(self) -> ModelSpec:
        return self._specs[self._default_chat]

    def default_finalize(self) -> ModelSpec:
        return self._specs[self._default_finalize]

    def default_chat_id(self) -> str:
        return self._default_chat

    def default_finalize_id(self) -> str:
        return self._default_finalize


def client_for(spec: ModelSpec) -> ChatClient:
    return _CLIENT_BY_MODULE[spec.module]


# ── DB helpers ───────────────────────────────────────────

async def _get_setting(db: AsyncSession, key: str) -> Any | None:
    row = await db.get(AppSetting, key)
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return row.value


async def _load_db_specs(db: AsyncSession) -> dict[str, ModelSpec]:
    stmt = select(AppSetting).where(AppSetting.key.like("model.%"))
    rows = (await db.execute(stmt)).scalars().all()
    out: dict[str, ModelSpec] = {}
    for row in rows:
        try:
            payload: Any = json.loads(row.value)
            spec = ModelSpec.from_dict(payload)
        except Exception as e:
            log.warning(
                "registry.skip_bad_db_model key=%s err=%s", row.key, e,
            )
            continue
        out[spec.id] = spec
    return out


# ── singleton ───────────────────────────────────────────

_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


async def reload_registry(
    db: AsyncSession, settings: Settings,
) -> ModelRegistry:
    """Called by create_app() at startup and by admin routes after
    every model / default write. Mutates the singleton in place so
    in-flight requests that captured a snapshot complete against it
    without a lock — the next request sees the new state."""
    reg = get_registry()
    await reg.load(db, settings)
    return reg