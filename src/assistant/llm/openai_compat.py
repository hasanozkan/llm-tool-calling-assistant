"""Adapter for any OpenAI-compatible Chat Completions endpoint — OpenAI
itself, Gemini's OpenAI endpoint, LiteLLM, vLLM, Ollama."""

import json
from collections.abc import Sequence
from typing import Any

import httpx

from assistant.llm.types import Completion, Message, ProviderError, ToolCall, ToolSpec, Usage


class OpenAICompatible:
    def __init__(self, *, base_url: str, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.name = f"openai-compat:{model}"
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=60)

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        body: dict[str, Any] = {"model": self._model, "messages": [_wire(m) for m in messages]}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        try:
            r = self._client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc)) from exc
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}")
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = tuple(
            ToolCall(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
            for c in msg.get("tool_calls") or []
        )
        usage = data.get("usage") or {}
        return Completion(
            Message("assistant", msg.get("content") or "", calls),
            model=data.get("model", self._model),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
        )


def _wire(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in m.tool_calls
        ]
    return out
