"""Markdown → DOCX export via pandoc, with no intermediate files.

pandoc reads markdown from stdin and writes the docx zip to stdout. This
only works with an explicit `-o -`; without it pandoc refuses to write
binary formats to stdout. See jgm/pandoc@61cf3aff (pandoc >= 2.0).
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
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024  # 2 MiB — a plan is nowhere near this.
PANDOC_TIMEOUT_S = 30.0

_PANDOC = shutil.which("pandoc")


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
        "-o", "-",                     # ← force binary output to stdout
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