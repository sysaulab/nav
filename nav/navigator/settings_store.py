"""KV settings write helpers.

Reads happen inline via `db.get(AppSetting, key)` where used — the
reads are one-liners and adding a wrapper would obscure them. This
module owns the writes because the upsert idiom is worth not
repeating.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSetting


async def set_app_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Upsert one key. JSON-encodes `value` and commits.

    Caller must not hold other uncommitted writes on `db` — this
    commits the whole session, which is what the admin routes want
    (one write per request).
    """
    encoded = json.dumps(value)
    stmt = pg_insert(AppSetting).values(key=key, value=encoded)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"], set_={"value": encoded},
    )
    await db.execute(stmt)
    await db.commit()


async def delete_app_setting(db: AsyncSession, key: str) -> bool:
    """Remove one key. Returns True if a row was deleted."""
    row = await db.get(AppSetting, key)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True