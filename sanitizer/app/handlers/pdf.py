"""app/handlers/pdf.py — PDF handler.

Two routes, selected by a text-layer heuristic:

    native   digital-born (extractable text) -> docling
    scanned  no extractable text             -> pymupdf rasterize + RapidOCR

Both enforce MAX_PAGES. On the scanned route the check runs against the
cheap len(pdf) before any rasterization. A blank scanned page yields a
Page with zero blocks and quality.status == "pass".
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from app.handlers.docling import handle_docling
from app.handlers.quarantine import quarantine
from app.models import Block, Document, Page, rollup
from app.ocr.engine import OcrDecodeError, OcrEngineError, ocr_engine
from app.ocr.reconcile import reconcile_ocr_lines
from app.settings import MAX_PAGES


def _pdf_has_text_layer(
    raw: bytes, sample_pages: int = 3, min_chars: int = 20,
) -> bool:
    """Heuristic: digital-born PDFs have extractable text; scans don't."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return False
    try:
        reader = PdfReader(io.BytesIO(raw))
        total = 0
        for page in reader.pages[:sample_pages]:
            total += len((page.extract_text() or "").strip())
            if total >= min_chars:
                return True
        return total >= min_chars
    except Exception:
        return False


def handle_pdf(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    if _pdf_has_text_layer(raw):
        return _pdf_native(path, raw, doc_id, declared, sniffed)
    return _pdf_scanned(path, raw, doc_id, declared, sniffed)


def _pdf_native(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    return handle_docling(
        path, raw, doc_id, declared, sniffed,
        route_name="pdf_native",
    )


def _pdf_scanned(
    path: Path, raw: bytes, doc_id: str,
    declared: Optional[str], sniffed: Optional[str],
) -> Document:
    try:
        import pymupdf
    except ImportError:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="pdf_scanned_ocr", converter="rapidocr",
            reason="pymupdf_not_installed — pip install pymupdf",
        )

    try:
        pdf = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as e:
        return quarantine(
            doc_id, path, declared, sniffed,
            route="pdf_scanned_ocr", converter="rapidocr",
            reason=f"pymupdf_open_error: {e}",
        )

    page_count = len(pdf)
    if page_count > MAX_PAGES:
        pdf.close()
        return quarantine(
            doc_id, path, declared, sniffed,
            route="pdf_scanned_ocr", converter="rapidocr",
            reason=f"too_many_pages: {page_count} > {MAX_PAGES}",
        )

    pages: list[Page] = []
    try:
        for page_index in range(page_count):
            pdf_page = pdf[page_index]
            rect = pdf_page.rect

            try:
                pix = pdf_page.get_pixmap(dpi=200)
                png_bytes = pix.tobytes("png")
            except Exception as e:
                return quarantine(
                    doc_id, path, declared, sniffed,
                    route="pdf_scanned_ocr", converter="rapidocr",
                    reason=f"pdf_rasterize_error: page={page_index + 1} {e}",
                )

            try:
                lines = ocr_engine.recognize(png_bytes)
            except OcrDecodeError as e:
                return quarantine(
                    doc_id, path, declared, sniffed,
                    route="pdf_scanned_ocr", converter="rapidocr",
                    reason=f"image_decode_error: page={page_index + 1} {e}",
                )
            except OcrEngineError as e:
                return quarantine(
                    doc_id, path, declared, sniffed,
                    route="pdf_scanned_ocr", converter="rapidocr",
                    reason=f"ocr_engine_error: page={page_index + 1} {e}",
                )

            blocks = [Block(**d) for d in reconcile_ocr_lines(lines)]
            for i, b in enumerate(blocks):
                b.block_id = f"p{page_index + 1}_b{i}"
                b.reading_order = i

            pages.append(Page(
                page_number=page_index + 1,
                width=float(rect.width),
                height=float(rect.height),
                blocks=blocks,
            ))
    finally:
        pdf.close()

    full_text = "\n\n".join(b.text for p in pages for b in p.blocks)

    return Document(
        document_id=doc_id,
        source={
            "filename": path.name,
            "mime_type_declared": declared,
            "mime_type_sniffed": sniffed,
            "route": "pdf_scanned_ocr",
            "converter": "rapidocr",
            "page_count": len(pages),
        },
        text=full_text,
        pages=pages,
        metadata={},
        rollup=rollup(pages),
        quality={"status": "pass", "reasons": []},
    )