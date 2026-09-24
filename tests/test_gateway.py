import json
from collections.abc import Sequence

import httpx
import pytest

from assistant.llm.anthropic import Anthropic
from assistant.llm.gateway import Router
from assistant.llm.openai_compat import OpenAICompatible
from assistant.llm.types import Completion, Message, ProviderError, ToolCall, ToolSpec

TOOL = ToolSpec("search_books", "find", {"type": "object", "properties": {"query": {"type": "string"}}})


class _Down:
    name = "down"

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        raise ProviderError("503")


class _Up:
    name = "up"

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        return Completion(Message("assistant", "hi"), model="up")


def test_the_router_falls_back_within_a_tier_and_reports_every_failure() -> None:
    assert Router({"fast": [_Down(), _Up()]}).complete("fast", [], []).model == "up"
    with pytest.raises(ProviderError, match="down: 503"):
        Router({"fast": [_Down()]}).complete("fast", [], [])


def test_a_missing_strong_tier_uses_fast() -> None:
    assert Router({"fast": [_Up()]}).complete("strong", [], []).model == "up"


def test_openai_compatible_wire_format_round_trip() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "t1",
                                    "type": "function",
                                    "function": {"name": "search_books", "arguments": '{"query": "ddd"}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    p = OpenAICompatible(
        base_url="https://x/v1", api_key="k", model="m", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    history = [
        Message("user", "find ddd"),
        Message("assistant", "", (ToolCall("t0", "search_books", {"query": "x"}),)),
        Message("tool", "[]", tool_call_id="t0"),
    ]
    out = p.complete(history, [TOOL])
    assert seen["auth"] == "Bearer k"
    assert seen["tools"] == [
        {"type": "function", "function": {"name": "search_books", "description": "find", "parameters": TOOL.parameters}}
    ]
    assert seen["messages"][2] == {"role": "tool", "tool_call_id": "t0", "content": "[]"}  # type: ignore[index]
    assert out.message.tool_calls == (ToolCall("t1", "search_books", {"query": "ddd"}),)
    assert out.usage.total == 15


def test_anthropic_wire_format_merges_tool_results_and_lifts_the_system_prompt() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["key"] = request.headers["x-api-key"]
        return httpx.Response(
            200,
            json={
                "model": "c",
                "content": [
                    {"type": "text", "text": "Let me look."},
                    {"type": "tool_use", "id": "u1", "name": "search_books", "input": {"query": "ddd"}},
                ],
                "usage": {"input_tokens": 20, "output_tokens": 5},
            },
        )

    p = Anthropic(api_key="k", model="c", client=httpx.Client(transport=httpx.MockTransport(handler)))
    history = [
        Message("system", "be precise"),
        Message("user", "two searches"),
        Message(
            "assistant",
            "",
            (ToolCall("a", "search_books", {"query": "x"}), ToolCall("b", "search_books", {"query": "y"})),
        ),
        Message("tool", "[1]", tool_call_id="a"),
        Message("tool", "[2]", tool_call_id="b"),
    ]
    out = p.complete(history, [TOOL])
    assert seen["system"] == "be precise" and seen["key"] == "k"
    msgs = seen["messages"]
    assert isinstance(msgs, list) and len(msgs) == 3
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["a", "b"]
    assert out.message.content == "Let me look."
    assert out.message.tool_calls == (ToolCall("u1", "search_books", {"query": "ddd"}),)


def test_http_errors_become_provider_errors() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(ProviderError, match="429"):
        Anthropic(api_key="k", model="c", client=client).complete([Message("user", "x")], [])
