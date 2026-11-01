"""app/handlers/office.py — OOXML handler (officemd).

Covers .docx / .xlsx / .pptx. officemd's IR schema is not stable across
versions, so IR parsing is defensive and falls back to a single block
built from the markdown export if extraction fails.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.handlers.quarantine import quarantine
from app.models import Block, Document, Page, rollup


def _blocks_from_officemd_ir(ir: Any) -> list[Block]:
    candidates: list = []
    if isinstance(ir, list):
        candidates = ir
    elif isinstance(ir, dict):
        for key in ("blocks", "elements", "children", "content"):
            value = ir.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates:
            body = ir.get("body")
            if isinstance(body, dict):
                for key in ("blocks", "elements", "children"):
                    value = body.get(key)
                    if isinstance(value, list):
                        candidates = value
                        break

    blocks: list[Block] = []
    for i, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        text = (
            item.get("text")
            or item.get("content")
            or item.get("markdown")
            or ""
        )
        if not text:
            continue
        blocks.append(Block(
            type=str(item.get("type", "text")),
            text=str(text),
            confidence=None,
            block_id=item.get("id") or f"b{i}",
            reading_order=item.get("order", i),
        ))
    return blocks


def _metadata_from_officemd_ir(ir: Any) -> dict:
    if not isinstance(ir, dict):
        return {}
    for key in ("metadata", "properties", "document_properties", "info"):
        value = ir.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _officemd_convert(path: Path) -> tuple[str, list[Block], dict]:
    try:
        from officemd import markdown_from_bytes, extract_ir_json
    except ImportError as e:
        raise RuntimeError("officemd not installed — `pip install officemd`") from e

    raw = path.read_bytes()
    fmt = path.suffix.lower().lstrip(".")
    text = markdown_from_bytes(raw, format=fmt)

    blocks: list[Block] = []
    metadata: dict = {}
    try:
        ir_raw = extract_ir_json(raw, format=fmt)
        ir = json.loads(ir_raw) if isinstance(ir_raw, str) else ir_raw
        blocks = _blocks_from_officemd_ir(ir)
        metadata = _metadata_from_officemd_ir(ir)
    except Exception:
        # IR extraction is best-effort; markdown still gives usable text.
        pass

    if not blocks:
        blocks = [Block(
            type="text",
            text=text,
            confidence=None,
            block_id="b0",
            reading_order=0,
        )]
    return text, blocks, metadata


def handle_office(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    try:
        text, blocks, metadata = _officemd_convert(path)
    except Exception as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="office", converter="officemd",
            reason=f"officemd_error: {e}",
        )

    page = Page(page_number=1, blocks=blocks)
    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": "office",
            "converter": "officemd",
            "page_count": 1,
        },
        text=text,
        pages=[page],
        metadata=metadata,
        rollup=rollup([page]),
        quality={"status": "pass", "reasons": []},
    )