"""AI client protocol, model spec, and normalized streaming events.

ModelSpec is the single source of truth for how much context a model
has and how much of it can be output. Every budget calculation in the
system derives from these two numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, runtime_checkable


_VALID_MODULES = frozenset({"ollama", "openai"})


@dataclass(frozen=True)
class ModelSpec:
    id: str
    module: str                      # "ollama" | "openai"
    endpoint: str
    model: str
    context_window: int
    max_output_tokens: int
    label: str
    api_key_env: str | None = None
    enabled: bool = True

    @property
    def budget_tokens(self) -> int:
        """How much of the window may be consumed by prompt + chat."""
        return max(0, self.context_window - self.max_output_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "module": self.module,
            "endpoint": self.endpoint,
            "model": self.model,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "label": self.label,
            "api_key_env": self.api_key_env,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelSpec":
        module = str(d["module"])
        if module not in _VALID_MODULES:
            raise ValueError(f"unknown module: {module!r}")
        return cls(
            id=str(d["id"]),
            module=module,
            endpoint=str(d["endpoint"]),
            model=str(d["model"]),
            context_window=int(d["context_window"]),
            max_output_tokens=int(d["max_output_tokens"]),
            label=str(d.get("label") or d["id"]),
            api_key_env=d.get("api_key_env"),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class ChatEvent:
    """One event emitted by a ChatClient.stream_chat().

    kind is one of:
      "delta"  — text=str
      "tool"   — tool_name=str, tool_arguments=dict, tool_call_id=str|None
      "done"   — finish_reason=str|None
      "error"  — error=str
    """
    kind: str
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict | None = None
    finish_reason: str | None = None
    error: str | None = None


@runtime_checkable
class ChatClient(Protocol):
    """One model backend. Stateless across calls — the caller owns history."""

    def stream_chat(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Yield ChatEvent. Implementations must not raise on network
        failure; yield ChatEvent(kind="error", ...) and stop."""
        ...