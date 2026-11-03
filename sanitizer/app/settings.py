"""app/settings.py — environment-driven configuration.

Every limit here is a *safety valve*, not a functional constraint. The
defaults are sized for a single-user workstation; raise via env vars if the
process is later moved to a server with more headroom.
"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else default


# Hard ceiling on a single upload, enforced twice:
#   1. ASGI middleware (`app.main.ContentLengthLimit`) rejects requests whose
#      declared Content-Length exceeds this *before* Starlette parses the body.
#   2. `_read_bounded` in `app.main` re-checks by reading limit+1 bytes, which
#      also covers chunked transfers that omit Content-Length.
# The on-disk spool Starlette uses is capped at this size; the in-memory
# allocation is capped at this size per concurrent request.
MAX_UPLOAD_BYTES: int = _int("SANITIZER_MAX_UPLOAD_BYTES", 100 * 1024 * 1024)

# Hard ceiling on page count for paginated routes (PDF scanned, docling).
# Exceeding it quarantines the document — we do not truncate, because a
# silently-partial document is worse than a rejected one.
MAX_PAGES: int = _int("SANITIZER_MAX_PAGES", 500)

# Blocks below this confidence are listed in rollup.low_confidence_block_ids.
# They are never dropped; filtering is the caller's decision.
LOW_CONFIDENCE_THRESHOLD: float = _float("SANITIZER_LOW_CONFIDENCE_THRESHOLD", 0.65)