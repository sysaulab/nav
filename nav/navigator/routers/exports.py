"""Markdown → DOCX export via pandoc, plus JSON directory backup/restore.

The docx route is the original plan export. The `/database` and
`/database/import` routes are the directory backup pair. They share
this router because both concern "getting data out and back in"; they
do not share implementation.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..backup import export_directory, import_directory
from ..db import get_db, get_engine

router = APIRouter(prefix="/export", tags=["export"])

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024   # 2 MiB — a plan is nowhere near this.
MAX_IMPORT_BYTES = 100 * 1024 * 1024   # 100 MiB — matches nginx + sanitizer.
PANDOC_TIMEOUT_S = 30.0

# Postgres advisory lock key for directory import. Distinct from the
# schema-creation lock (920110) and the purge lock (920111) in
# main.py. Reused by every replica so concurrent imports serialise.
_IMPORT_LOCK_KEY = 920112

_PANDOC = shutil.which("pandoc")


# ── Markdown → DOCX ──────────────────────────────────────

class MarkdownDocxIn(BaseModel):
    markdown: str = Field(..., min_length=1)
    filename: str | None = Field(default=None, max_length=120)


def _safe_filename(name: str | None) -> str:
    base = (name or "action-plan").strip()
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or "action-plan"
    return base[:80]


@router.post("/docx")
async def export_docx(payload: MarkdownDocxIn) -> Response:
    if _PANDOC is None:
        raise HTTPException(503, "pandoc is not installed on this server")

    data = payload.markdown.encode("utf-8")
    if len(data) > MAX_MARKDOWN_BYTES:
        raise HTTPException(413, "markdown is too large to export")

    proc = await asyncio.create_subprocess_exec(
        _PANDOC,
        "-f", "markdown",
        "-t", "docx",
        "-o", "-",                     # force binary output to stdout
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=data), timeout=PANDOC_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(504, "pandoc timed out")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

    if proc.returncode != 0:
        detail = stderr.decode("utf-8", "replace")[:500]
        raise HTTPException(500, f"pandoc failed: {detail}")
    if not stdout:
        raise HTTPException(500, "pandoc produced no output")

    fname = _safe_filename(payload.filename)
    return Response(
        content=stdout,
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}.docx"',
            "Content-Length": str(len(stdout)),
        },
    )


# ── Directory export ─────────────────────────────────────
#
# Compact JSON (no indent, separators=(",", ":")). The file is
# meant to be re-imported; a user who wants to inspect it can
# pretty-print with jq. Compact keeps the payload small enough
# to fit under the import cap on realistic regional directories.

@router.get("/database")
async def export_database(db: AsyncSession = Depends(get_db)) -> Response:
    """Download a JSON snapshot of the directory tables."""
    payload = await export_directory(db)
    body = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"navigator-backup-{stamp}.json"

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
        },
    )


# ── Directory import ─────────────────────────────────────

@router.post("/database/import")
async def import_database(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace the directory from a JSON snapshot.

    Wrapped in a single transaction and serialised by a Postgres
    advisory lock. A failure leaves the directory unchanged.
    """
    if mode != "replace":
        raise HTTPException(400, f"unsupported import mode: {mode!r}")

    raw = await file.read()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(
            413, f"import exceeds {MAX_IMPORT_BYTES} bytes",
        )

    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, f"invalid JSON: {e}")

    engine = get_engine()
    is_postgres = engine.dialect.name == "postgresql"

    if is_postgres:
        # Serialise concurrent imports across replicas. Transaction-
        # scoped: the lock releases on commit or rollback. The value
        # is the same on every replica, so a second import blocks
        # until the first completes (or fails).
        await db.execute(text(f"SELECT pg_advisory_xact_lock({_IMPORT_LOCK_KEY})"))

    try:
        counts = await import_directory(db, payload, mode=mode)
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"import failed: {e}")

    return {"ok": True, "mode": mode, "counts": counts}