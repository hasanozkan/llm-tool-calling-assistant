"""Adapter for the Anthropic Messages API (tool use via content blocks)."""

from collections.abc import Sequence
from typing import Any

import httpx

from assistant.llm.types import Completion, Message, ProviderError, ToolCall, ToolSpec, Usage

API = "https://api.anthropic.com/v1/messages"


class Anthropic:
    def __init__(self, *, api_key: str, model: str, max_tokens: int = 1024, client: httpx.Client | None = None) -> None:
        self.name = f"anthropic:{model}"
        self._key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(timeout=60)

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": _wire(messages),
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        try:
            r = self._client.post(API, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc)) from exc
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}")
        data = r.json()
        text = "".join(b["text"] for b in data["content"] if b["type"] == "text")
        calls = tuple(
            ToolCall(b["id"], b["name"], b.get("input") or {}) for b in data["content"] if b["type"] == "tool_use"
        )
        usage = data.get("usage") or {}
        return Completion(
            Message("assistant", text, calls),
            model=data.get("model", self._model),
            usage=Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
        )


def _wire(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Anthropic wants tool results as user-role content blocks, and
    consecutive tool results merged into one user message."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.role == "assistant" and m.tool_calls:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m.role, "content": m.content})
    return out
