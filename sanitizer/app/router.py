"""
router.py — file router for the document processing pipeline.

Reads a file, sniffs its type, and dispatches it down the cheapest viable path:

    office  -> officemd
    pdf     -> native parser (stub) | scanned -> OCR (stub)
    image   -> RapidOCR microservice at http://localhost:8000/ocr
    text    -> read as-is
    other   -> quarantine

Returns the canonical ingestion JSON described in the pipeline plan.

CLI entry point lives in `app/main.py` (`python -m app.main FILE ...`),
not here — one dispatcher for both server and CLI so exit codes and size
limits cannot drift.
"""

from __future__ import annotations

import hashlib
import mimetypes
import tempfile
from pathlib import Path
from typing import Optional

from app.handlers.docling import handle_docling
from app.handlers.image import handle_image
from app.handlers.office import handle_office
from app.handlers.pdf import handle_pdf
from app.handlers.quarantine import quarantine
from app.handlers.text import handle_text
from app.models import Document

from app.handlers.rtf import handle_rtf

try:
    import magic  # python-magic; needs libmagic on the host
except ImportError:
    magic = None


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------


# Keep these with officemd (OOXML, handled without LibreOffice)
OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}

# Route these to Docling (ODF + legacy binary + RTF)
DOCLING_EXTS = {".odt", ".ods", ".odp"}

OFFICE_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

DOCLING_MIMES = {
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
}

RTF_EXTS = {".rtf"}
RTF_MIMES = {"application/rtf", "text/rtf"}


# Classic Office 97-2003 binary formats (OLE2/CFB). Docling can only parse
# these via LibreOffice headless (>=2.114) — a ~500 MB image dependency.
# Reject up front with a "save as OOXML" hint rather than let Docling fail
# with a generic "File format not allowed".
BLOCKED_LEGACY_EXTS = {".doc", ".xls", ".ppt"}
BLOCKED_LEGACY_MIMES = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
}

PDF_EXTS = {".pdf"}
PDF_MIMES = {"application/pdf"}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
IMAGE_MIME_PREFIX = "image/"

TEXT_EXTS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml",
    ".html", ".htm", ".log", ".yaml", ".yml",
}
TEXT_MIME_PREFIX = "text/"


# --------------------------------------------------------------------------
# MIME sniffing
# --------------------------------------------------------------------------

def sniff_mime(raw: bytes, filename: str) -> Optional[str]:
    """Best-effort sniffed MIME type; falls back to extension-based guess."""
    if magic is not None:
        try:
            return magic.from_buffer(raw[:4096], mime=True)
        except Exception:
            pass
    return mimetypes.guess_type(filename)[0]


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

def route(path: Path | str, *, display_name: str | None = None) -> Document:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    raw = path.read_bytes()
    doc_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    declared = mimetypes.guess_type(path.name)[0]
    sniffed = sniff_mime(raw, path.name)
    ext = path.suffix.lower()

    if ext in BLOCKED_LEGACY_EXTS or sniffed in BLOCKED_LEGACY_MIMES:
        doc = quarantine(
            doc_id, path, declared, sniffed,
            route="blocked_legacy_office", converter="none",
            reason=(
                f"legacy_binary_office_unsupported: {ext or 'unknown'} is a "
                f"classic Office 97-2003 binary format. Save the file as "
                f"OOXML (.docx / .xlsx / .pptx) and re-upload."
            ),
        )
    elif ext in RTF_EXTS or sniffed in RTF_MIMES:
        doc = handle_rtf(path, raw, doc_id, declared, sniffed)
    elif ext in DOCLING_EXTS or sniffed in DOCLING_MIMES:
        doc = handle_docling(path, raw, doc_id, declared, sniffed,
                             route_name="docling_office")
    elif ext in OFFICE_EXTS or sniffed in OFFICE_MIMES or declared in OFFICE_MIMES:
        doc = handle_office(path, raw, doc_id, declared, sniffed)
    elif ext in PDF_EXTS or sniffed in PDF_MIMES or declared in PDF_MIMES:
        doc = handle_pdf(path, raw, doc_id, declared, sniffed)
    elif (ext in IMAGE_EXTS or (sniffed or "").startswith(IMAGE_MIME_PREFIX)
          or (declared or "").startswith(IMAGE_MIME_PREFIX)):
        doc = handle_image(path, raw, doc_id, declared, sniffed)
    elif (ext in TEXT_EXTS or (sniffed or "").startswith(TEXT_MIME_PREFIX)
          or (declared or "").startswith(TEXT_MIME_PREFIX)):
        doc = handle_text(path, raw, doc_id, declared, sniffed)
    else:
        doc = quarantine(doc_id, path, declared, sniffed,
                         route="quarantine", converter="none",
                         reason=f"unsupported_format: ext={ext!r} "
                                f"declared={declared!r} sniffed={sniffed!r}")

    if display_name:
        doc.source["filename"] = display_name
    return doc


# app/router.py
import logging, time, uuid
log = logging.getLogger("sanitizer.ingest")


def route_bytes(filename: str, raw: bytes) -> Document:
    """Route an in-memory upload down the same path as `route()`.

    `route()` is path-based — it re-reads bytes for hashing and hands the
    path to officemd / docling / pymupdf. So we spool `raw` to a temp file
    inside a TemporaryDirectory, preserving the original basename so
    extension-based MIME guessing inside `route()` matches what a real
    on-disk upload would produce. `display_name` carries the original
    filename through to `source.filename`.

    Logging note: `filename` is a reserved LogRecord attribute — the key is
    `upload_name` deliberately, not a typo.
    """
    req_id = uuid.uuid4().hex
    t0 = time.perf_counter()
    log.info(
        "ingest.start",
        extra={"req_id": req_id, "upload_name": filename, "bytes": len(raw)},
    )

    # basename only — reject path traversal, ".", "..", and empty strings
    safe_name = Path(filename).name if filename else ""
    if not safe_name or safe_name in (".", ".."):
        safe_name = "upload"

    try:
        with tempfile.TemporaryDirectory(prefix="ingest_") as td:
            tmp_path = Path(td) / safe_name
            tmp_path.write_bytes(raw)
            doc = route(tmp_path, display_name=filename)

        log.info(
            "ingest.finish",
            extra={
                "req_id": req_id,
                "route": doc.source["route"],
                "converter": doc.source["converter"],
                "quality": doc.quality["status"],
                "pages": doc.source["page_count"],
                "blocks": doc.rollup["block_count"],
                "low_conf": doc.rollup["low_confidence_block_count"],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            },
        )
        return doc
    except Exception:
        log.exception(
            "ingest.error",
            extra={"req_id": req_id, "upload_name": filename},
        )
        raise