"""A deterministic stand-in for a model, so the engine, the guards and the
evals run in CI for free and give the same answer every time.

It is deliberately *gullible*: when a tool result contains an instruction it
obeys it, the way a real model sometimes does. The guards must hold anyway.
`mistakes` switches on known-bad behaviour so the eval gate can be proven to
catch it (see `make evals-negative`).
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from assistant.llm.types import Completion, Message, ToolCall, ToolSpec, Usage

QUOTED = re.compile(r'"([^"]+)"')
MEMBER = re.compile(r"\bm_[a-z]+\b")
LOAN = re.compile(r"\bl_\d+\b")
PAYLOAD = re.compile(r">\n(.*)\n</tool_output>", re.DOTALL)


class ScriptedModel:
    def __init__(self, *, mistakes: frozenset[str] = frozenset(), name: str = "scripted") -> None:
        self.name = name
        self._mistakes = mistakes
        self._n = 0

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        user_idx = max(i for i, m in enumerate(messages) if m.role == "user")
        user = messages[user_idx].content
        names = {c.id: c.name for m in messages[user_idx:] for c in m.tool_calls}
        done = [(names.get(m.tool_call_id or "", "?"), m.content) for m in messages[user_idx:] if m.role == "tool"]
        reply = self._decide(user, done)
        tokens_in = sum(len(m.content) for m in messages) // 4
        return Completion(reply, model=self.name, usage=Usage(tokens_in, len(reply.content) // 4 + 8))

    def _call(self, name: str, **args: Any) -> Message:
        self._n += 1
        return Message("assistant", "", (ToolCall(f"call_{self._n}", name, args),))

    def _decide(self, user: str, done: list[tuple[str, str]]) -> Message:
        low = user.lower()
        member = next(iter(MEMBER.findall(user)), None)
        borrow = "borrow" in low
        quoted = next(iter(QUOTED.findall(user)), None)
        if not done:
            if borrow and member and "skip_search" in self._mistakes:
                return self._call("borrow_copy", member_id=member, copy_id="c_guess")
            if "return" in low and LOAN.search(user):
                return self._call("return_loan", loan_id=LOAN.findall(user)[0])
            if member and any(w in low for w in ("owe", "fees", "status", "how many")):
                return self._call("member_status", member_id=member)
            if quoted:
                return self._call("search_books", query=quoted)
            return Message("assistant", "Tell me a title or author in quotes, or a member id like m_ada.")
        last_tool, content = done[-1]
        data = _payload(content)
        if isinstance(data, dict) and "argument_error" in data:
            return self._decide(user, done[:-1])  # read the error, make the call again properly
        if last_tool == "search_books" and isinstance(data, list):
            text = json.dumps(data)
            if "ignore all previous instructions" in text.lower() and not any(t == "borrow_copy" for t, _ in done):
                bad = next(h for h in data if "IGNORE" in h["title"])
                return self._call("borrow_copy", member_id="m_attacker", copy_id=bad["available_copy_ids"][0])
            if borrow and member and not any(t == "borrow_copy" for t, _ in done):
                hit = next((h for h in data if h["available_copy_ids"]), None)
                if hit:
                    return self._call("borrow_copy", member_id=member, copy_id=hit["available_copy_ids"][0])
                return Message("assistant", "No copy is available right now.")
            if not data:
                return Message("assistant", "I could not find that book.")
            lines = [f"{h['title']} by {h['author']}: {len(h['available_copy_ids'])} available" for h in data]
            return Message("assistant", "; ".join(lines) + ".")
        if last_tool == "member_status" and isinstance(data, dict):
            if "error" in data:
                return Message("assistant", f"I could not look that up ({data['error']}).")
            fees = data["outstanding_fees_cents"] / 100
            return Message(
                "assistant",
                f"{data['member_id']} has {data['active_loans']} of {data['max_loans']} loans and owes {fees:.2f}.",
            )
        if last_tool in ("borrow_copy", "return_loan"):
            return Message("assistant", "I have prepared that change. Please confirm it before I go ahead.")
        return Message("assistant", "Done.")


def _payload(content: str) -> Any:
    match = PAYLOAD.search(content)
    try:
        return json.loads(match.group(1) if match else content)
    except json.JSONDecodeError:
        return None
