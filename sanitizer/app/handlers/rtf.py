"""app/handlers/rtf.py — RTF handler via Pandoc.

Docling's RTF backend shells out to LibreOffice, which the sanitizer image
does not install. Pandoc has a native RTF reader (2.14+; nested tables in
3.11+), so we use that instead and keep the LibreOffice dependency out of
the image.

RTF → Markdown, not RTF → plain text: Markdown preserves headings, lists,
and tables, which is what the navigator's prompt renderer expects.

`subprocess.run` rather than `asyncio.create_subprocess_exec` because this
handler is sync — it runs in FastAPI's threadpool, not on the event loop.
Using two `asyncio.run()` calls (one per await) would bind the child's
pipes to a loop that closes between them, raising `Event loop is closed`
on every real RTF.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.handlers.quarantine import quarantine
from app.models import Block, Document, Page, rollup


PANDOC_TIMEOUT_S = 30.0
_PANDOC = shutil.which("pandoc")


def handle_rtf(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    if _PANDOC is None:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="rtf_pandoc", converter="pandoc",
            reason="pandoc_not_installed — install pandoc (>=2.14 for RTF input)",
        )

    try:
        markdown = _pandoc_convert(raw)
    except RuntimeError as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="rtf_pandoc", converter="pandoc",
            reason=f"pandoc_error: {e}",
        )

    blocks = [Block(
        type="text", text=markdown, confidence=None,
        block_id="b0", reading_order=0,
    )]
    page = Page(page_number=1, blocks=blocks)

    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": "rtf_pandoc",
            "converter": "pandoc",
            "page_count": 1,
        },
        text=markdown,
        pages=[page],
        metadata={},
        rollup=rollup([page]),
        quality={"status": "pass", "reasons": []},
    )


def _pandoc_convert(raw: bytes) -> str:
    """Run `pandoc -f rtf -t markdown` over stdin → stdout.

    Returns the Markdown text. Raises RuntimeError on non-zero exit,
    timeout, or empty output — callers convert that into a quarantine.
    """
    if not raw:
        raise RuntimeError("empty RTF payload")

    try:
        proc = subprocess.run(
            [_PANDOC, "-f", "rtf", "-t", "markdown", "-o", "-"],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PANDOC_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        # subprocess.run kills and reaps the child before re-raising.
        raise RuntimeError(
            f"pandoc timed out after {PANDOC_TIMEOUT_S}s"
        ) from e
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f"pandoc unavailable: {e}") from e

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace")[:300]
        raise RuntimeError(detail or f"exit {proc.returncode}")

    text = proc.stdout.decode("utf-8", "replace").strip()
    if not text:
        raise RuntimeError("pandoc produced no output")
    return text