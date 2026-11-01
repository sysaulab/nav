"""app/handlers/image.py — image OCR handler.

Calls RapidOCR in-process. A blank image yields a Page with zero blocks,
rollup.confidence of all nulls, and quality.status == "pass".
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.handlers.quarantine import quarantine
from app.models import Block, Document, Page, rollup
from app.ocr.engine import OcrDecodeError, OcrEngineError, ocr_engine
from app.ocr.reconcile import reconcile_ocr_lines


def handle_image(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    try:
        lines = ocr_engine.recognize(raw)
    except OcrDecodeError as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="image_ocr", converter="rapidocr",
            reason=f"image_decode_error: {e}",
        )
    except OcrEngineError as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="image_ocr", converter="rapidocr",
            reason=f"ocr_engine_error: {e}",
        )

    blocks = [Block(**d) for d in reconcile_ocr_lines(lines)]
    page = Page(page_number=1, blocks=blocks)
    full_text = "\n\n".join(b.text for b in blocks)

    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": "image_ocr",
            "converter": "rapidocr",
            "page_count": 1,
        },
        text=full_text,
        pages=[page],
        metadata={},
        rollup=rollup([page]),
        quality={"status": "pass", "reasons": []},
    )