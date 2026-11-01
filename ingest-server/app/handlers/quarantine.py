"""app/handlers/quarantine.py — shared quarantine constructor.

Every failure path returns the same empty-document shape so callers can
branch on quality.status without inspecting each handler's error model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.models import Document


def quarantine(
    doc_id: str,
    path: Path,
    declared: Optional[str],
    sniffed: Optional[str],
    *,
    route: str,
    converter: str,
    reason: str,
) -> Document:
    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": route,
            "converter": converter,
            "page_count": 0,
        },
        text="",
        pages=[],
        metadata={},
        rollup={
            "confidence": {"min": None, "mean": None, "max": None},
            "block_count": 0,
            "low_confidence_block_count": 0,
            "low_confidence_block_ids": [],
        },
        quality={"status": "quarantine", "reasons": [reason]},
    )