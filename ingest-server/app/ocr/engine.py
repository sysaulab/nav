# app/ocr/engine.py
"""app/ocr/engine.py — in-process RapidOCR wrapper.

Single-process, single-threaded for the same reason the HTTP path uses
`_ingest_lock`: one inference at a time to bound memory on a single-user
workstation.

Contract (see docstring on OcrEngine.recognize):
  - Returns [] for a valid image with no detected text.
  - Raises OcrDecodeError for undecodable input.
  - Raises OcrEngineError for inference failure.
  - Never returns None.

RapidOCR gotchas this wrapper absorbs:

  1. `rapidocr_onnxruntime` returns `(None, None)` — not `([], None)` — for
     images with zero detected text, AND for images it silently rejects due
     to shape/dtype. The latter is the dangerous case: a single-channel
     (grayscale) array reaches the detector as (H, W) instead of (H, W, 3)
     and the detector returns (None, None) without warning. So we must
     normalize to 3-channel BGR uint8 *before* inference, or B&W scans come
     back empty.

  2. The native return is `[[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text, conf]`
     per line — four corner points, not a [xmin,ymin,xmax,ymax] box. The
     rest of the pipeline (reconcile.OcrLine) expects the axis-aligned box
     form, so we convert here. Forgetting this is a silent shape mismatch
     that surfaces as KeyError or nonsense heights downstream.

  3. Large images are downscaled to a 2000 px long edge. Downscale only,
     never upscale — a small image upscaled 3x produces softer strokes and
     is measurably worse on the CWTS-style datasets we test against.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Optional

import numpy as np
from PIL import Image, UnidentifiedImageError

log = logging.getLogger("sanitizer.ocr.engine")


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class OcrError(Exception):
    """Base class — do not raise directly; use a subclass."""


class OcrDecodeError(OcrError):
    """Image bytes could not be decoded into a usable raster."""


class OcrEngineError(OcrError):
    """RapidOCR raised during model construction or inference."""


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

_MAX_LONG_EDGE = 2000   # matches the old HTTP endpoint's cap
_MIN_LONG_EDGE = 32     # anything smaller is almost certainly garbage


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

class OcrEngine:
    """Lazy-initialized RapidOCR wrapper.

    The RapidOCR() constructor loads ONNX models (~100 MB) and takes seconds.
    We construct lazily so importing this module is cheap for tests and for
    the router (which imports it transitively via handlers/*).
    """

    def __init__(self) -> None:
        self._engine: Any = None

    def _get(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as e:
                raise OcrEngineError(
                    "rapidocr_onnxruntime not installed — "
                    "`pip install rapidocr-onnxruntime`"
                ) from e
            try:
                self._engine = RapidOCR()
            except Exception as e:
                raise OcrEngineError(f"RapidOCR init failed: {e}") from e
        return self._engine

    # ----------------------------------------------------------------------

    def recognize(self, image_bytes: bytes) -> list[dict]:
        """Run OCR on `image_bytes`. See module docstring for the contract."""
        arr = _decode(image_bytes)
        arr = _downscale(arr, _MAX_LONG_EDGE)
        if max(arr.shape[:2]) < _MIN_LONG_EDGE:
            log.debug(
                "ocr.tiny_image shape=%s — running anyway", arr.shape,
            )

        engine = self._get()
        try:
            result = engine(arr)
        except Exception as e:
            raise OcrEngineError(f"RapidOCR inference failed: {e}") from e

        # rapidocr 3.x returns a RapidOCROutput dataclass, not a tuple.
        # All fields (boxes / txts / scores) are None when nothing is found.
        if result is None or getattr(result, "txts", None) is None:
            log.debug("ocr.no_text shape=%s", arr.shape)
            return []

        lines: list[dict] = []
        # boxes: np.ndarray (N, 4, 2) — four corner points per line
        # txts:  Tuple[str]
        # scores: Tuple[float]
        for pts, text, conf in zip(result.boxes, result.txts, result.scores):
            try:
                xs = [float(p[0]) for p in pts]
                ys = [float(p[1]) for p in pts]
            except (IndexError, TypeError, ValueError) as e:
                log.warning(
                    "ocr.malformed_line dropped=%r err=%s", (pts, text, conf), e,
                )
                continue

            text = str(text).strip()
            if not text:
                continue

            lines.append({
                "text": text,
                "confidence": float(conf),
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
            })

        log.debug("ocr.recognized lines=%d shape=%s", len(lines), arr.shape)
        return lines


# --------------------------------------------------------------------------
# Preprocessing helpers
# --------------------------------------------------------------------------

def _decode(image_bytes: bytes) -> np.ndarray:
    """bytes -> 3-channel BGR uint8 ndarray.

    PIL is used rather than cv2.imdecode because PIL reliably identifies
    CMYK / palette / 16-bit PNGs and raises a clean error on corruption;
    cv2.imdecode silently returns None for several formats, which is exactly
    the failure mode we're trying to avoid here.
    """
    if not image_bytes:
        raise OcrDecodeError("empty image payload")
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()                          # forces full decode; surfaces truncation
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise OcrDecodeError(f"cannot decode image: {e}") from e

    # RapidOCR's detector expects 3-channel BGR. Convert regardless of
    # source mode ("L", "1", "P", "RGBA", "CMYK", 16-bit) — this is the
    # single-channel fix; without it, B&W scans return (None, None).
    if img.mode != "RGB":
        img = img.convert("RGB")

    arr = np.asarray(img, dtype=np.uint8)          # (H, W, 3) RGB
    arr = arr[:, :, ::-1].copy()                   # RGB -> BGR, contiguous
    return arr


def _downscale(arr: np.ndarray, max_long_edge: int) -> np.ndarray:
    """Downscale so the long edge <= max_long_edge. Never upscales."""
    h, w = arr.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long_edge:
        return arr

    scale = max_long_edge / long_edge
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    # PIL's LANCZOS is the right kernel for OCR: preserves stroke edges
    # better than bilinear and produces fewer ringing artifacts than cubic.
    from PIL import Image
    rgb = arr[:, :, ::-1]                          # BGR -> RGB for PIL
    img = Image.fromarray(rgb, mode="RGB").resize(
        (new_w, new_h), Image.LANCZOS,
    )
    out = np.asarray(img, dtype=np.uint8)[:, :, ::-1].copy()
    log.debug(
        "ocr.downscale %dx%d -> %dx%d", w, h, new_w, new_h,
    )
    return out


# Module-level singleton — matches the prior interface.
ocr_engine = OcrEngine()