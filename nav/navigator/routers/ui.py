"""Public UI-string endpoint for nav-ui.

Not auth-gated: nav-ui runs on a kiosk with no bearer token and needs
translations at boot. Only returns translations for the requested
locale; the client already ships the English source as a fallback.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import UiStringTranslation

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/strings")
async def get_strings(
    locale: str = Query(..., min_length=2, max_length=10),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if locale == "en":
        # English is the source — nothing to return. The client already
        # has it bundled.
        return {"locale": "en", "strings": {}}
    rows = (await db.execute(
        select(UiStringTranslation.key, UiStringTranslation.translated)
        .where(UiStringTranslation.locale == locale)
    )).all()
    return {"locale": locale, "strings": {k: v for k, v in rows}}