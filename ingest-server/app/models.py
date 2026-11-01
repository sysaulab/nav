"""app/models.py — shared data models for the document sanitizer.

The pipeline's public contract is `Document.to_dict()`. The Pydantic classes
below exist to (a) validate the dicts coming out of reconcile_ocr_lines and
the docling/officemd adapters, and (b) give handlers a typed constructor.

Serialization invariants (relied on by downstream consumers):
  - `to_dict()` key order: schema_version, document_id, source, text,
    metadata, pages, rollup, quality.
  - Per-block keys: type, text, bbox, confidence, table_data, block_id,
    reading_order.
  - Per-page keys: page_number, width, height, blocks.
  - `None` values are emitted as JSON null, never omitted.

Confidence shape when present: {"min", "mean", "max", "lines"} — all floats
except "lines" (int).
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.settings import LOW_CONFIDENCE_THRESHOLD


SCHEMA_VERSION = "1.0"


class Block(BaseModel):
    """A single content block within a page.

    Constructed by handlers from reconcile_ocr_lines() output (OCR routes) or
    directly from adapter dicts (officemd / docling). Handlers may mutate
    `block_id` and `reading_order` after construction to scope IDs per page.

    `extra="forbid"` is deliberate: the dict shapes feeding Block(**d) are a
    contract between reconcile.py and the handlers. A silent extra field is
    a bug, not a forward-compatibility win.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    text: str
    bbox: Optional[list[float]] = None
    confidence: Optional[dict[str, Any]] = None
    table_data: Optional[dict] = None
    block_id: Optional[str] = None
    reading_order: Optional[int] = None


class Page(BaseModel):
    page_number: int
    width: Optional[float] = None
    height: Optional[float] = None
    blocks: list[Block] = Field(default_factory=list)


class Document(BaseModel):
    """Top-level sanitizer output.

    Wrapped in `to_dict()` so `schema_version` is emitted and page serialization
    goes through Pydantic recursion (equivalent to the old
    `[asdict(b) for b in p.blocks]` shape).
    """

    model_config = ConfigDict(arbitrary_types_allowed=False)

    document_id: str
    source: dict[str, Any]
    text: str
    pages: list[Page] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    rollup: dict[str, Any]
    quality: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "document_id": self.document_id,
            "source": self.source,
            "text": self.text,
            "metadata": self.metadata,
            "pages": [p.model_dump() for p in self.pages],
            "rollup": self.rollup,
            "quality": self.quality,
        }


def rollup(pages: list[Page]) -> dict:
    """Aggregate confidence and block counts across pages.

    `confidence.mean` is a per-block mean-of-means (each block contributes
    equally regardless of line count). `confidence.min` / `max` are true
    extrema across every block that reported confidence.

    Blocks with `confidence["min"] < LOW_CONFIDENCE_THRESHOLD` are listed in
    `low_confidence_block_ids` but never dropped — filtering is the caller's
    decision.
    """
    mins: list[float] = []
    means: list[float] = []
    maxs: list[float] = []
    low_ids: list[str] = []

    for page in pages:
        for b in page.blocks:
            if not b.confidence:
                continue
            mins.append(b.confidence["min"])
            means.append(b.confidence["mean"])
            maxs.append(b.confidence["max"])
            if b.confidence["min"] < LOW_CONFIDENCE_THRESHOLD and b.block_id:
                low_ids.append(b.block_id)

    conf: dict[str, Any] = (
        {
            "min": round(min(mins), 4),
            "mean": round(sum(means) / len(means), 4),
            "max": round(max(maxs), 4),
        }
        if mins
        else {"min": None, "mean": None, "max": None}
    )

    return {
        "confidence": conf,
        "block_count": sum(len(p.blocks) for p in pages),
        "low_confidence_block_count": len(low_ids),
        "low_confidence_block_ids": low_ids,
    }