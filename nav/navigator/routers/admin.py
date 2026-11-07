"""Admin API — protected by NAVIGATOR_ADMIN_TOKEN bearer.

Public nav-ui's nginx does not proxy /admin-api/*, so these routes
are reachable only through the admin frontend's nginx. The token is
still the primary guard: an attacker who guesses the path could hit
these routes directly against nav:8001 (which is loopback-bound).

v1 surface: model CRUD, defaults, health. Database administration
and other operator tools land in a later pass.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.base import ModelSpec
from ..ai.registry import get_registry, reload_registry
from ..config import Settings
from ..db import get_db
from ..settings_store import delete_app_setting, set_app_setting

log = logging.getLogger("navigator.admin")

router = APIRouter(prefix="/admin-api", tags=["admin"])

_settings: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def _cfg() -> Settings:
    assert _settings is not None, "bind_settings() not called"
    return _settings


async def require_admin(
    authorization: str | None = Header(default=None),
) -> None:
    cfg = _cfg()
    if not cfg.admin_token:
        raise HTTPException(503, "admin is not configured on this server")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != cfg.admin_token:
        raise HTTPException(401, "invalid admin token")


# ── health ───────────────────────────────────────────────

@router.get("/health", dependencies=[Depends(require_admin)])
async def admin_health() -> dict[str, Any]:
    reg = get_registry()
    return {
        "ok": True,
        "models": len(reg.all()),
        "default_chat": reg.default_chat_id(),
        "default_finalize": reg.default_finalize_id(),
    }


# ── models ───────────────────────────────────────────────

class ModelIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    module: str = Field(pattern="^(ollama|openai)$")
    endpoint: str = Field(min_length=1, max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    context_window: int = Field(gt=0, le=10_000_000)
    max_output_tokens: int = Field(gt=0)
    label: str = Field(default="", max_length=255)
    api_key_env: str | None = None
    enabled: bool = True


@router.get("/models", dependencies=[Depends(require_admin)])
async def list_models() -> list[dict[str, Any]]:
    return [s.to_dict() for s in get_registry().all()]


@router.get("/models/defaults", dependencies=[Depends(require_admin)])
async def get_defaults() -> dict[str, str]:
    reg = get_registry()
    return {
        "chat": reg.default_chat_id(),
        "finalize": reg.default_finalize_id(),
    }


class DefaultsIn(BaseModel):
    chat: str | None = None
    finalize: str | None = None


@router.put("/models/defaults", dependencies=[Depends(require_admin)])
async def set_defaults(
    payload: DefaultsIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    reg = get_registry()
    if payload.chat is not None:
        if reg.get(payload.chat) is None:
            raise HTTPException(400, f"unknown model id: {payload.chat!r}")
        await set_app_setting(db, "default.chat", payload.chat)
    if payload.finalize is not None:
        if reg.get(payload.finalize) is None:
            raise HTTPException(400, f"unknown model id: {payload.finalize!r}")
        await set_app_setting(db, "default.finalize", payload.finalize)

    reg = await reload_registry(db, _cfg())
    return {
        "chat": reg.default_chat_id(),
        "finalize": reg.default_finalize_id(),
    }


@router.get("/models/{model_id}", dependencies=[Depends(require_admin)])
async def get_model(model_id: str) -> dict[str, Any]:
    spec = get_registry().get(model_id)
    if spec is None:
        raise HTTPException(404, "model not found")
    return spec.to_dict()


@router.put("/models/{model_id}", dependencies=[Depends(require_admin)])
async def put_model(
    model_id: str,
    payload: ModelIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if model_id != payload.id:
        raise HTTPException(400, "path id and body id must match")
    if payload.max_output_tokens >= payload.context_window:
        raise HTTPException(
            400, "max_output_tokens must be smaller than context_window",
        )

    await set_app_setting(db, f"model.{model_id}", payload.model_dump())
    reg = await reload_registry(db, _cfg())
    spec = reg.get(model_id)
    if spec is None:
        raise HTTPException(500, "model not present after write")
    return spec.to_dict()


@router.delete(
    "/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_model(
    model_id: str, db: AsyncSession = Depends(get_db),
) -> None:
    reg = get_registry()
    if (
        reg.default_chat_id() == model_id
        or reg.default_finalize_id() == model_id
    ):
        raise HTTPException(
            409,
            f"cannot delete {model_id!r}: it is currently a default. "
            "Set a different default first.",
        )
    deleted = await delete_app_setting(db, f"model.{model_id}")
    if not deleted:
        raise HTTPException(404, "model not found (no DB override)")
    await reload_registry(db, _cfg())