"""Token estimation for prompt budgeting.

Prefers a real HF tokenizer (any Gemma-family model — only the tokenizer
files are downloaded, ~few MB). Falls back to a conservative chars/3.5
heuristic if `transformers` is absent or the model isn't cached.

Over-estimating is safe (may exclude one doc early). Under-estimating would
truncate output, so the heuristic deliberately under-divides.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("sanitizer.tokens")

_tokenizer: Any = None
_tokenizer_attempted: bool = False


def _load(model_name: str):
    global _tokenizer, _tokenizer_attempted
    if _tokenizer_attempted:
        return _tokenizer
    _tokenizer_attempted = True
    try:
        from transformers import AutoTokenizer
        # local_files_only=True guarantees no network call, even if the
        # container is started outside HF_HUB_OFFLINE. A missing cache is
        # a warning + heuristic fallback, not a multi-second DNS hang.
        _tokenizer = AutoTokenizer.from_pretrained(
            model_name, local_files_only=True,
        )
        log.info("tokenizer.loaded model=%s", model_name)
    except Exception as e:
        log.warning(
            "tokenizer.unavailable model=%s err=%s — falling back to chars/3.5",
            model_name, e,
        )
        _tokenizer = None
    return _tokenizer


def estimate_tokens(payload: Any, *, model_name: str = "google/gemma-2-2b-it") -> int:
    """Count tokens of `payload` (str as-is, dict/list via compact JSON)."""
    text = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    tok = _load(model_name)
    if tok is not None:
        try:
            return len(tok.encode(text, add_special_tokens=False))
        except Exception as e:
            log.warning("tokenizer.encode_failed err=%s — char heuristic", e)
    # Conservative: 3.5 chars/token (JSON is denser than prose).
    return max(1, int(len(text) / 3.5))