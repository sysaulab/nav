"""Extract only what the LLM needs from the sanitizer's canonical output.

Drops:
  - top-level `text` (redundant with pages[].blocks[])
  - source.mime_*, source.converter (provenance only)
  - document_id, rollup.confidence.* (per-block min_confidence is retained)
  - bbox (not actionable without tools)

Keeps:
  - table_data (correctness)
  - block_id (citation handle)
  - min_confidence (hedge on bad OCR)
  - quality (transparency)
"""
from __future__ import annotations


def filter_sanitizer_output(doc: dict) -> dict:
    """`doc` is the full sanitizer /ingest response."""
    return {
        "filename": doc["source"]["filename"],
        "page_count": doc["source"]["page_count"],
        "quality": doc["quality"]["status"],
        "pages": [
            {
                "page_number": p["page_number"],
                "blocks": [
                    {
                        "block_id": b.get("block_id"),
                        "type": b["type"],
                        "text": b["text"],
                        "table_data": b.get("table_data"),
                        "min_confidence": (b.get("confidence") or {}).get("min"),
                    }
                    for b in p["blocks"]
                ],
            }
            for p in doc["pages"]
        ],
    }