"""
reconcile.py — consolidate OCR lines from the RapidOCR microservice
into reading-ordered blocks with proper confidence stats.

Usage:

    from app.ocr.reconcile import reconcile_ocr_lines
    lines = ocr_engine.recognize(image_bytes)
    blocks = [Block(**d) for d in reconcile_ocr_lines(lines)]
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Optional


log = logging.getLogger("sanitizer.ocr.reconcile")


# --------------------------------------------------------------------------
# Input model
# --------------------------------------------------------------------------

@dataclass
class OcrLine:
    text: str
    bbox: list[float]          # [x_min, y_min, x_max, y_max]
    confidence: float

    @classmethod
    def from_dict(cls, d: dict) -> "OcrLine":
        return cls(
            text=str(d.get("text", "")).strip(),
            bbox=list(d.get("bbox", [0.0, 0.0, 0.0, 0.0])),
            confidence=float(d.get("confidence", 0.0)),
        )

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])

    @property
    def y_center(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def reconcile_ocr_lines(
    raw_lines: list[dict] | None,
    *,
    h_gap_factor: float = 0.55,   # gap vs median line height => paragraph break
    v_gap_factor: float = 1.50,   # gap vs median line height => column gutter
    heading_height_ratio: float = 1.20,
) -> list[dict]:
    """
    Consolidate OCR lines into blocks. Returns a list of dicts shaped like
    router.Block: type, text, bbox, confidence, table_data, block_id,
    reading_order.

    `raw_lines` may be None: RapidOCR's low-level API returns (None, None)
    for images with no detected text. A blank image is a valid input that
    yields zero blocks (see handlers/__init__.py: "blank pages are valid
    output"), so None and [] both mean "no text detected" and both return [].

    The coercion lives here rather than in callers because both handle_image
    and _pdf_scanned flow through this function. A `reconcile.none_input`
    warning is emitted when None is seen — that means OcrEngine.recognize()
    violated its contract (it should return []), and we want it loud in the
    logs, not silently absorbed.
    """
    if raw_lines is None:
        log.warning(
            "reconcile.none_input — OcrEngine.recognize() returned None; "
            "contract says it must return []. Treating as no-text, but this "
            "is an engine bug worth investigating.",
        )

    lines = [OcrLine.from_dict(d) for d in (raw_lines or [])]
    lines = [l for l in lines if l.text and l.height > 0]
    if not lines:
        return []

    heights = [l.height for l in lines if l.height > 0]
    median_h = statistics.median(heights) if heights else 1.0

    leaves = _xy_cut(lines, h_gap=h_gap_factor * median_h, v_gap=v_gap_factor * median_h)

    blocks: list[dict] = []
    for leaf in leaves:
        block = _make_block(leaf, median_h, heading_height_ratio)
        if block:
            blocks.append(block)

    for i, b in enumerate(blocks):
        b["block_id"] = f"b{i}"
        b["reading_order"] = i
    return blocks


# --------------------------------------------------------------------------
# XY-cut
# --------------------------------------------------------------------------

def _xy_cut(lines: list[OcrLine], h_gap: float, v_gap: float) -> list[list[OcrLine]]:
    """Recursive XY-cut. Returns leaves in reading order."""
    if len(lines) <= 1:
        return [list(lines)]

    # 1) Horizontal split — the dominant choice for paragraphs.
    bands = _split_at_gaps(lines, axis="y", min_gap=h_gap)
    if len(bands) > 1:
        out: list[list[OcrLine]] = []
        for band in bands:
            out.extend(_xy_cut(band, h_gap, v_gap))
        return out

    # 2) Vertical split — only if the result is a clean column layout.
    columns = _split_at_gaps(lines, axis="x", min_gap=v_gap)
    if len(columns) > 1 and _is_clean_column_split(columns):
        out = []
        for col in columns:
            out.extend(_xy_cut(col, h_gap, v_gap))
        return out

    # 3) No split — one leaf, sorted top-to-bottom then left-to-right.
    return [sorted(lines, key=lambda l: (round(l.y_center), l.bbox[0]))]


def _split_at_gaps(lines: list[OcrLine], *, axis: str, min_gap: float):
    if axis == "y":
        start = lambda l: l.bbox[1]
        end = lambda l: l.bbox[3]
    else:
        start = lambda l: l.bbox[0]
        end = lambda l: l.bbox[2]

    ordered = sorted(lines, key=start)
    groups: list[list[OcrLine]] = [[ordered[0]]]
    current_end = end(ordered[0])

    for line in ordered[1:]:
        gap = start(line) - current_end
        if gap >= min_gap:
            groups.append([line])
        else:
            groups[-1].append(line)
        current_end = max(current_end, end(line))
    return groups


def _is_clean_column_split(columns: list[list[OcrLine]]) -> bool:
    """Reject splits where any line crosses a column boundary."""
    ranges = [
        (min(l.bbox[0] for l in c), max(l.bbox[2] for l in c))
        for c in columns
    ]
    for col in columns:
        for line in col:
            hits = sum(1 for lo, hi in ranges if line.bbox[0] < hi and line.bbox[2] > lo)
            if hits > 1:
                return False
    return True


# --------------------------------------------------------------------------
# Block construction
# --------------------------------------------------------------------------

def _make_block(
    lines: list[OcrLine], median_h: float, heading_ratio: float,
) -> Optional[dict]:
    if not lines:
        return None

    text = _join_lines([l.text for l in lines])
    if not text.strip():
        return None

    bbox = [
        min(l.bbox[0] for l in lines),
        min(l.bbox[1] for l in lines),
        max(l.bbox[2] for l in lines),
        max(l.bbox[3] for l in lines),
    ]

    scores = [l.confidence for l in lines]
    confidence = {
        "min":  round(min(scores), 4),
        "mean": round(sum(scores) / len(scores), 4),
        "max":  round(max(scores), 4),
        "lines": len(scores),
    }

    return {
        "type": _classify(lines, text, median_h, heading_ratio),
        "text": text,
        "bbox": bbox,
        "confidence": confidence,
        "table_data": None,
        "block_id": None,       # assigned by reconcile_ocr_lines
        "reading_order": None,
    }


def _join_lines(texts: list[str]) -> str:
    """Join OCR lines; de-hyphenate only when it's safe."""
    parts = [t.strip() for t in texts if t and t.strip()]
    if not parts:
        return ""
    out = parts[0]
    for nxt in parts[1:]:
        # Safe de-hyphenation: "jum-" + "ped"  ->  "jumped"
        if (
            out.endswith("-")
            and len(out) >= 2
            and out[-2].isalpha()
            and nxt[:1].islower()
        ):
            out = out[:-1] + nxt
        else:
            out = out + " " + nxt
    return out


def _classify(
    lines: list[OcrLine], text: str,
    median_h: float, heading_ratio: float,
) -> str:
    if not lines:
        return "text"
    avg_h = sum(l.height for l in lines) / len(lines)
    is_tall = avg_h >= heading_ratio * median_h
    letters = [c for c in text if c.isalpha()]
    is_caps = (
        bool(letters)
        and sum(c.isupper() for c in letters) / len(letters) >= 0.80
        and len(text) <= 100
    )
    short_enough = len(lines) <= 2 and len(text) <= 120

    if short_enough and (is_tall or is_caps):
        return "heading"
    return "text"