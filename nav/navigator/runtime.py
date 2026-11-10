"""Runtime-tunable prompt text, nearby-search parameters, and admin token.

Layered: hardcoded defaults <- Settings (env) <- database (admin UI).

The chat and finalize system prompts, the three nearby-search tunables,
and the admin token were previously compile-time or env-only. This module
makes them operator-tunable without a redeploy. The DB is the source of
truth; `load()` reads it and publishes an immutable snapshot that handlers
read lock-free.

Write paths live in `routers/admin.py`. Every write calls
`reload_runtime()` immediately after `set_app_setting()`, so the next
request sees the change. Reads use `get_runtime().current()`.

SECURITY: ``RuntimeSettings.admin_token`` is a credential. Never log it,
never return it from an API endpoint, never pass it to a template.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import AppSetting
from .prompt import BASE_SYSTEM_PROMPT, FINALIZE_SYSTEM_PROMPT

log = logging.getLogger("navigator.runtime")


KEY_CHAT_PROMPT = "prompt.chat"
KEY_FINALIZE_PROMPT = "prompt.finalize"
KEY_NEARBY = "params.nearby"
KEY_ADMIN_TOKEN = "auth.admin_token"


@dataclass(frozen=True)
class NearbyParams:
    radius_km: float
    location_limit: int
    index_limit: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "radius_km": self.radius_km,
            "location_limit": self.location_limit,
            "index_limit": self.index_limit,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NearbyParams":
        return cls(
            radius_km=float(d["radius_km"]),
            location_limit=int(d["location_limit"]),
            index_limit=int(d["index_limit"]),
        )


@dataclass(frozen=True)
class RuntimeSettings:
    chat_prompt: str
    finalize_prompt: str
    nearby: NearbyParams
    # Credential — never log, never serialize into a response.
    admin_token: str | None


class RuntimeRegistry:
    def __init__(self) -> None:
        # Populated by the first load() call. Calling current() before
        # load() is a programming error — main.py calls load() in the
        # startup handler, before serving traffic.
        self._current: RuntimeSettings | None = None

    def current(self) -> RuntimeSettings:
        if self._current is None:
            raise RuntimeError("RuntimeRegistry.load() has not been called")
        return self._current

    async def load(self, db: AsyncSession, settings: Settings) -> None:
        # Defaults: prompts from source, nearby and token from env.
        chat_prompt = BASE_SYSTEM_PROMPT
        finalize_prompt = FINALIZE_SYSTEM_PROMPT
        nearby = NearbyParams(
            radius_km=settings.postcode_radius_km,
            location_limit=settings.nearby_location_limit,
            index_limit=settings.nearby_index_limit,
        )
        admin_token = settings.admin_token

        # Prompt overrides — tolerate plain text as well as JSON strings,
        # so an operator can seed via psql without worrying about quoting.
        row = await db.get(AppSetting, KEY_CHAT_PROMPT)
        if row is not None and row.value.strip():
            try:
                v = json.loads(row.value)
                if isinstance(v, str) and v.strip():
                    chat_prompt = v
            except json.JSONDecodeError:
                chat_prompt = row.value

        row = await db.get(AppSetting, KEY_FINALIZE_PROMPT)
        if row is not None and row.value.strip():
            try:
                v = json.loads(row.value)
                if isinstance(v, str) and v.strip():
                    finalize_prompt = v
            except json.JSONDecodeError:
                finalize_prompt = row.value

        # Nearby override — partial dict allowed; missing keys fall back
        # to env defaults above.
        row = await db.get(AppSetting, KEY_NEARBY)
        if row is not None:
            try:
                d = json.loads(row.value)
                if isinstance(d, dict):
                    merged = {**nearby.to_dict(), **d}
                    nearby = NearbyParams.from_dict(merged)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                log.warning("runtime.bad_nearby_override err=%s", e)

        # Admin token override. An empty or whitespace-only DB value is
        # treated as "no override", NOT as "disable admin" — disabling
        # admin requires unsetting both the env value and the DB row.
        row = await db.get(AppSetting, KEY_ADMIN_TOKEN)
        if row is not None and row.value.strip():
            try:
                v = json.loads(row.value)
                if isinstance(v, str) and v:
                    admin_token = v
            except json.JSONDecodeError:
                admin_token = row.value

        # Publish atomically. asyncio yields only at await points, so a
        # reader sees all-old or all-new, never a mix.
        self._current = RuntimeSettings(
            chat_prompt=chat_prompt,
            finalize_prompt=finalize_prompt,
            nearby=nearby,
            admin_token=admin_token,
        )
        log.info(
            "runtime.loaded chat_len=%d finalize_len=%d "
            "radius_km=%s location_limit=%s index_limit=%s admin_token=%s",
            len(chat_prompt), len(finalize_prompt),
            nearby.radius_km, nearby.location_limit, nearby.index_limit,
            "set" if admin_token else "unset",
        )


_registry: RuntimeRegistry | None = None


def get_runtime() -> RuntimeRegistry:
    global _registry
    if _registry is None:
        _registry = RuntimeRegistry()
    return _registry


async def reload_runtime(
    db: AsyncSession, settings: Settings,
) -> RuntimeRegistry:
    reg = get_runtime()
    await reg.load(db, settings)
    return reg


def defaults_for(settings: Settings) -> RuntimeSettings:
    """What a fresh install would run with — shown as 'default' in the UI."""
    return RuntimeSettings(
        chat_prompt=BASE_SYSTEM_PROMPT,
        finalize_prompt=FINALIZE_SYSTEM_PROMPT,
        nearby=NearbyParams(
            radius_km=settings.postcode_radius_km,
            location_limit=settings.nearby_location_limit,
            index_limit=settings.nearby_index_limit,
        ),
        admin_token=settings.admin_token,
    )