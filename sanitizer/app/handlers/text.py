"""app/handlers/text.py — plain-text handler.

No failure paths: decoding is lossy-but-lenient (errors="replace") and
there is no converter to fail. Always returns quality.status == "pass".
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.models import Block, Document, Page, rollup


def handle_text(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    text = raw.decode("utf-8", errors="replace")
    blocks = [Block(
        type="text", text=text, confidence=None,
        block_id="b0", reading_order=0,
    )]
    page = Page(page_number=1, blocks=blocks)
    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": "text",
            "converter": "plaintext",
            "page_count": 1,
        },
        text=text,
        pages=[page],
        metadata={},
        rollup=rollup([page]),
        quality={"status": "pass", "reasons": []},
    )