"""Contract tests for the ChatClient protocol.

ai/base.py declares: "Implementations must not raise on network failure;
yield ChatEvent(kind='error', ...) and stop."

These tests exercise every registered client against a deliberately
unreachable endpoint and assert that the only way it can terminate is a
terminal ChatEvent(kind='error'). A raise here means a chat or finalize
stream will abort silently — an ASGI exception in the server log with no
NDJSON error frame reaching the frontend — which is the failure mode
this contract exists to prevent.

The second half tests the belt-and-suspenders in routers/interviews.py:
even a raising client is converted into a visible error frame by
_stream_simple and _stream_with_tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest

from navigator.ai.base import ChatEvent, ModelSpec
from navigator.ai.registry import _CLIENT_BY_MODULE
from navigator.routers import interviews as interviews_mod


# 127.0.0.1:1 is tcpmux — nothing listens there on any sane host, and
# connect refuses immediately, so the test never waits on a timeout.
_UNREACHABLE = "http://127.0.0.1:1"
_TEST_API_KEY_ENV = "NAV_TEST_CLIENT_CONTRACT_KEY"


def _spec(module: str) -> ModelSpec:
    return ModelSpec(
        id=f"contract-test-{module}",
        module=module,
        endpoint=_UNREACHABLE,
        model="contract-test",
        context_window=1024,
        max_output_tokens=128,
        label="contract-test",
        api_key_env=_TEST_API_KEY_ENV,
    )


# ── Client-side contract: no raise on network failure ────────

@pytest.mark.parametrize("module", sorted(_CLIENT_BY_MODULE))
async def test_client_does_not_raise_on_unreachable_endpoint(module: str):
    """Every registered ChatClient must yield a terminal error event."""
    client = _CLIENT_BY_MODULE[module]
    spec = _spec(module)

    # OpenAI short-circuits on a missing API key before touching the
    # network. Supply a dummy so both modules exercise the connect-
    # failure path rather than the "missing key" branch.
    os.environ[_TEST_API_KEY_ENV] = "sk-dummy-not-used"
    try:
        events: list[ChatEvent] = [
            ev async for ev in client.stream_chat(
                spec, [{"role": "user", "content": "hi"}],
            )
        ]
    finally:
        os.environ.pop(_TEST_API_KEY_ENV, None)

    assert events, (
        f"{module} client yielded no events for an unreachable "
        f"endpoint; contract requires a terminal error event"
    )
    last = events[-1]
    assert last.kind == "error", (
        f"{module} client terminated with kind={last.kind!r}, expected "
        f"'error'. The stream would have aborted silently in production."
    )
    assert last.error, f"{module} client yielded an empty error message"


# ── Caller-side belt-and-suspenders: raising client still
#    produces a visible error frame ───────────────────────────

class _RaisingClient:
    """Fake ChatClient that emits one delta, then raises."""

    async def stream_chat(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ):
        yield ChatEvent(kind="delta", text="partial output")
        raise RuntimeError("simulated transport failure")


def _decode_frames(chunks: list[bytes]) -> list[dict[str, Any]]:
    text = b"".join(chunks).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def test_stream_simple_emits_error_frame_when_client_raises(monkeypatch):
    monkeypatch.setattr(
        interviews_mod, "client_for", lambda spec: _RaisingClient(),
    )
    response = interviews_mod._stream_simple(
        _spec("ollama"), [{"role": "user", "content": "hi"}],
    )
    frames = _decode_frames([c async for c in response.body_iterator])

    assert any(
        f.get("message", {}).get("content") == "partial output"
        for f in frames
    ), "partial delta should have reached the client before the raise"
    assert frames[-1].get("error"), "expected terminal error frame"
    assert "simulated transport failure" in frames[-1]["error"]


async def test_stream_with_tools_emits_error_frame_when_client_raises(
    monkeypatch,
):
    monkeypatch.setattr(
        interviews_mod, "client_for", lambda spec: _RaisingClient(),
    )
    response = interviews_mod._stream_with_tools(
        _spec("ollama"),
        [{"role": "user", "content": "hi"}],
        [],
        db=None,     # type: ignore[arg-type] — never reached: client
        sess=None,   # type: ignore[arg-type]   raises before tool dispatch
    )
    frames = _decode_frames([c async for c in response.body_iterator])

    assert any(
        f.get("message", {}).get("content") == "partial output"
        for f in frames
    )
    assert frames[-1].get("error")
    assert "simulated transport failure" in frames[-1]["error"]