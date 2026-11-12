"""Public UI-string endpoint for nav-ui.

Not auth-gated: nav-ui runs on a kiosk with no bearer token and needs
translations at boot. English is served from ui_string_translation the
same way as every other locale — the client carries no bundled English
dictionary. English rows are populated from ui_string.english by
seed_missing_english (translator signature "source"), and can be
overridden by an operator via /admin-api (signature "manual"). The
client sees whichever the server serves.
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
    rows = (await db.execute(
        select(UiStringTranslation.key, UiStringTranslation.translated)
        .where(UiStringTranslation.locale == locale)
    )).all()
    return {"locale": locale, "strings": {k: v for k, v in rows}}