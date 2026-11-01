"""app/handlers/docling.py — Docling handler.

Handles ODF, legacy binary Office formats, RTF, and (via pdf.py's native
route) digital-born PDFs. docling is imported lazily so a missing optional
dependency quarantines the document instead of failing at import.

MAX_PAGES is enforced *after* conversion — docling exposes no pre-flight
page count. The check runs against the materialized Page list, not
doc_dict["pages"], because _pages_from_docling_dict can synthesize pages
from texts[].prov.page_no that are absent from the top-level pages list.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.handlers.quarantine import quarantine
from app.models import Block, Document, Page, rollup
from app.settings import MAX_PAGES


def _map_docling_label(label: str) -> str:
    if label in {"section_header", "title"}:
        return "heading"
    if label == "list_item":
        return "list"
    if label in {"code", "formula"}:
        return "text"
    if label == "table":
        return "table"
    return "text"


def _pages_from_docling_dict(doc_dict: dict) -> list[Page]:
    pages_map: dict[int, Page] = {}

    for p in doc_dict.get("pages", []):
        page_no = int(p.get("page_no", 1))
        size = p.get("size", {}) or {}
        pages_map[page_no] = Page(
            page_number=page_no,
            width=float(size["width"]) if "width" in size else None,
            height=float(size["height"]) if "height" in size else None,
            blocks=[],
        )

    for item in doc_dict.get("texts", []):
        text = (item.get("text") or "").strip()
        if not text:
            continue

        prov = (item.get("prov") or [{}])[0]
        page_no = int(prov.get("page_no", 1))
        bbox_raw = prov.get("bbox")
        bbox = None
        if bbox_raw and len(bbox_raw) == 4:
            bbox = [float(x) for x in bbox_raw]

        page = pages_map.setdefault(page_no, Page(page_number=page_no, blocks=[]))
        page.blocks.append(Block(
            type=_map_docling_label(item.get("label", "text")),
            text=text,
            bbox=bbox,
            confidence=None,
            block_id=f"p{page_no}_b{len(page.blocks)}",
            reading_order=len(page.blocks),
        ))

    pages = [pages_map[k] for k in sorted(pages_map)]
    for page in pages:
        page.blocks.sort(key=lambda b: (
            b.bbox[1] if b.bbox else 0.0,
            b.bbox[0] if b.bbox else 0.0,
        ))
        for i, b in enumerate(page.blocks):
            b.reading_order = i
    return pages


def handle_docling(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
    *,
    route_name: str = "docling_office",
) -> Document:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        return quarantine(
            doc_id, path, declared, sniffed,
            route=route_name, converter="docling",
            reason="docling_not_installed",
        )

    try:
        converter = DocumentConverter()
        result = converter.convert(str(path))
        doc_dict = result.document.export_to_dict()
    except Exception as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route=route_name, converter="docling",
            reason=f"docling_error: {e}",
        )

    pages = _pages_from_docling_dict(doc_dict)

    if len(pages) > MAX_PAGES:
        return quarantine(
            doc_id, path, declared, sniffed,
            route=route_name, converter="docling",
            reason=f"too_many_pages: {len(pages)} > {MAX_PAGES}",
        )

    full_text = "\n\n".join(b.text for p in pages for b in p.blocks)

    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": route_name,
            "converter": "docling",
            "page_count": len(pages),
        },
        text=full_text,
        pages=pages,
        metadata={},
        rollup=rollup(pages),
        quality={"status": "pass", "reasons": []},
    )