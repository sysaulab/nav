"""Markdown → DOCX export via pandoc.

The public JSON directory backup/restore pair that used to live here
(`/api/export/database` and `/api/export/database/import`) has been
removed. Directory backup/restore is still available, but only on the
authenticated admin surface:

    GET  /admin-api/database/export     (navigator/routers/admin.py)
    POST /admin-api/database/import     (navigator/routers/admin.py)

Both call into navigator/backup.py. This router now exports only the
plan-as-docx endpoint used by nav-ui.
"""
from __future__ import annotations

import asyncio
import re
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/export", tags=["export"])

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024   # 2 MiB — a plan is nowhere near this.
PANDOC_TIMEOUT_S = 30.0
MAX_PLAN_BYTES = 2 * 1024 * 1024   # 2 MiB — an action plan is nowhere near this.


_PANDOC = shutil.which("pandoc")


class HtmlDocxIn(BaseModel):
    html: str = Field(..., min_length=1)
    filename: str | None = Field(default=None, max_length=120)


# ── Markdown → DOCX ──────────────────────────────────────

class MarkdownDocxIn(BaseModel):
    markdown: str = Field(..., min_length=1)
    filename: str | None = Field(default=None, max_length=120)


def _safe_filename(name: str | None) -> str:
    base = (name or "action-plan").strip()
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or "action-plan"
    return base[:80]


@router.post("/docx")
async def export_docx(payload: HtmlDocxIn) -> Response:
    if _PANDOC is None:
        raise HTTPException(503, "pandoc is not installed on this server")

    data = payload.html.encode("utf-8")
    if len(data) > MAX_PLAN_BYTES:
        raise HTTPException(413, "html is too large to export")

    # Read the caller's HTML as HTML, not markdown. The UI already ran
    # the plan through remark-gfm to render it, so the source we receive
    # is well-formed HTML — h1/h2/p/ul/ol/li/table elements. Pandoc's
    # markdown reader is pedantic about CommonMark edge cases (a space
    # before "- " or "1. ", sequential ordered-list numbering) that
    # react-markdown tolerates when it produces this HTML. The HTML
    # reader parses the same constructs without complaint.
    proc = await asyncio.create_subprocess_exec(
        _PANDOC,
        "-f", "html",
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