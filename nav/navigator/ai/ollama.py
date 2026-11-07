"""Ollama chat client.

Passes num_ctx and num_predict explicitly from the ModelSpec. This
matters: without num_ctx, Ollama uses its compiled-in default (2048)
regardless of the model's actual window, silently truncating long
prompts. The prior chat handler set it inline; the prior finalize
handler did not — that bug is what this module exists to prevent.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import ChatEvent, ModelSpec

log = logging.getLogger("navigator.ai.ollama")


class OllamaClient:
    name = "ollama"

    async def _stream(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        timeout: float,
    ) -> AsyncIterator[ChatEvent]:
        payload: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": spec.context_window,
                "num_predict": spec.max_output_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{spec.endpoint.rstrip('/')}/api/chat", json=payload,
            ) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    yield ChatEvent(
                        kind="error",
                        error=f"ollama {r.status_code}: {body[:300]!r}",
                    )
                    return

                pending_tool_calls: list[dict] = []
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message") or {}
                    if msg.get("content"):
                        yield ChatEvent(kind="delta", text=msg["content"])
                    if msg.get("tool_calls"):
                        pending_tool_calls.extend(msg["tool_calls"])
                    if chunk.get("done"):
                        for tc in pending_tool_calls:
                            fn = tc.get("function") or {}
                            yield ChatEvent(
                                kind="tool",
                                tool_call_id=tc.get("id"),
                                tool_name=fn.get("name", ""),
                                tool_arguments=fn.get("arguments") or {},
                            )
                        yield ChatEvent(
                            kind="done",
                            finish_reason=chunk.get("done_reason"),
                        )
                        return

                yield ChatEvent(kind="error", error="ollama stream ended early")

    def stream_chat(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 600.0,
    ) -> AsyncIterator[ChatEvent]:
        return self._stream(spec, messages, tools, timeout)