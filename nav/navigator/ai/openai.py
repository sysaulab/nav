"""OpenAI-compatible chat client.

Works against any /v1/chat/completions endpoint that uses the
OpenAI wire format. API key is read from the env var named by
ModelSpec.api_key_env (default: OPENAI_API_KEY); a missing key is
reported as a ChatEvent(kind="error") rather than an exception so
the streaming contract stays uniform across modules.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

import httpx

from .base import ChatEvent, ModelSpec

log = logging.getLogger("navigator.ai.openai")


class OpenAIClient:
    name = "openai"

    def _api_key(self, spec: ModelSpec) -> str | None:
        env_name = spec.api_key_env or "OPENAI_API_KEY"
        return os.environ.get(env_name)

    async def _stream(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        timeout: float,
    ) -> AsyncIterator[ChatEvent]:
        api_key = self._api_key(spec)
        if not api_key:
            env_name = spec.api_key_env or "OPENAI_API_KEY"
            yield ChatEvent(
                kind="error",
                error=f"missing API key: env var {env_name} is unset",
            )
            return

        payload: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
            "max_tokens": spec.max_output_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{spec.endpoint.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as r:
                    if r.status_code >= 400:
                        body = await r.aread()
                        yield ChatEvent(
                            kind="error",
                            error=f"openai {r.status_code}: {body[:300]!r}",
                        )
                        return

                    tool_buffers: dict[int, dict] = {}
                    finish_reason: str | None = None

                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}

                        if delta.get("content"):
                            yield ChatEvent(kind="delta", text=delta["content"])

                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            buf = tool_buffers.setdefault(idx, {
                                "id": "", "name": "", "arguments": "",
                            })
                            if tc.get("id"):
                                buf["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                buf["name"] = fn["name"]
                            if fn.get("arguments"):
                                buf["arguments"] += fn["arguments"]

                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]

                    for idx in sorted(tool_buffers.keys()):
                        buf = tool_buffers[idx]
                        try:
                            args = (
                                json.loads(buf["arguments"])
                                if buf["arguments"] else {}
                            )
                        except json.JSONDecodeError:
                            args = {"_raw": buf["arguments"]}
                        yield ChatEvent(
                            kind="tool",
                            tool_call_id=buf["id"] or None,
                            tool_name=buf["name"],
                            tool_arguments=args,
                        )

                    yield ChatEvent(kind="done", finish_reason=finish_reason)
        except httpx.RequestError as e:
            yield ChatEvent(
                kind="error",
                error=f"connection failed to {spec.endpoint}: {e}",
            )
    
    def stream_chat(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 600.0,
    ) -> AsyncIterator[ChatEvent]:
        return self._stream(spec, messages, tools, timeout)