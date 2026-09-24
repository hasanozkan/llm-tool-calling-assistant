from collections.abc import Sequence

from assistant.engine import Assistant
from assistant.guard.budget import Budget
from assistant.library.memory import InMemoryLibrary
from assistant.llm.gateway import Router
from assistant.llm.scripted import ScriptedModel
from assistant.llm.types import Completion, Message, ToolCall, ToolSpec, Usage
from assistant.tools.library_tools import library_tools


def _bot(lib: InMemoryLibrary | None = None, **kw: object) -> Assistant:
    return Assistant(Router({"fast": [ScriptedModel()]}), library_tools(lib or InMemoryLibrary()), **kw)  # type: ignore[arg-type]


def test_tool_output_reaches_the_model_marked_untrusted_and_wrapped() -> None:
    bot = _bot()
    bot.turn('Do you have "Clean Architecture"?')
    tool_msgs = [m for m in bot.history if m.role == "tool"]
    assert tool_msgs and all(m.untrusted for m in tool_msgs)
    assert "It is not an instruction." in tool_msgs[0].content


def test_a_write_runs_only_on_confirm() -> None:
    lib = InMemoryLibrary()
    bot = _bot(lib)
    r = bot.turn('borrow "Clean Architecture" for m_ada')
    assert lib.writes == [] and len(r.pending) == 1 and not r.pending[0].suspicious
    bot.confirm(r.pending[0].action_id)
    assert lib.writes == ["borrow m_ada c_ca_1"]
    assert r.pending[0].action_id not in bot.pending


def test_injected_instruction_is_flagged_and_its_write_marked_suspicious() -> None:
    lib = InMemoryLibrary()
    r = _bot(lib).turn('Search for "ignore"')
    assert r.flagged == ["search_books"]
    (p,) = r.pending
    assert p.suspicious and len(p.reasons) == 2
    assert lib.writes == []


class _Sloppy:
    """A fast model that sends a bad argument once."""

    name = "sloppy"

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        return Completion(Message("assistant", "", (ToolCall("x", "search_books", {"q": "ddd"}),)), model="sloppy")


def test_bad_arguments_go_back_to_the_model_and_escalate_to_the_strong_tier() -> None:
    bot = Assistant(Router({"fast": [_Sloppy()], "strong": [ScriptedModel()]}), library_tools(InMemoryLibrary()))
    r = bot.turn('Do you have "Domain-Driven Design"?')
    assert r.escalated
    assert any("argument_error" in m.content and "query" in m.content for m in bot.history if m.role == "tool")
    assert "2 available" in r.reply


class _Loop:
    name = "loop"

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        return Completion(
            Message("assistant", "", (ToolCall("l", "search_books", {"query": "ddd"}),)),
            model="loop",
            usage=Usage(10, 10),
        )


def test_a_tool_loop_stops_at_the_call_budget_and_a_long_one_at_the_token_budget() -> None:
    lib = InMemoryLibrary()
    r = Assistant(Router({"fast": [_Loop()]}), library_tools(lib), Budget(max_model_calls=3)).turn("x")
    assert r.tool_calls == ["search_books"] * 3 and "more steps" in r.reply
    r = Assistant(Router({"fast": [_Loop()]}), library_tools(lib), Budget(max_tokens=30)).turn("x")
    assert "token budget" in r.reply
