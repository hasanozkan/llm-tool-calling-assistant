"""The library as tools. Two read, two write — and the difference matters:
the engine runs reads immediately and turns writes into proposals the user
must confirm (ADR-0002)."""

from dataclasses import asdict

from assistant.library.port import LibraryPort
from assistant.llm.types import ToolSpec
from assistant.tools.registry import Tool, ToolRegistry


def _obj(**props: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": list(props),
        "additionalProperties": False,
    }


def library_tools(lib: LibraryPort) -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                ToolSpec(
                    "search_books",
                    "Find books by title or author; lists available copy ids.",
                    _obj(query="Words from the title or the author's name"),
                ),
                lambda query: [asdict(h) for h in lib.search(query)],
            ),
            Tool(
                ToolSpec(
                    "member_status",
                    "A member's active loans, limit and outstanding fees.",
                    _obj(member_id="The member id, e.g. m_ada"),
                ),
                lambda member_id: asdict(lib.member_status(member_id)),
            ),
            Tool(
                ToolSpec(
                    "borrow_copy",
                    "Lend one available copy to a member. Needs the user's confirmation.",
                    _obj(member_id="The member id", copy_id="An available copy id from search_books"),
                    effect="write",
                ),
                lambda member_id, copy_id: asdict(lib.borrow(member_id, copy_id)),
            ),
            Tool(
                ToolSpec(
                    "return_loan",
                    "Close a loan. Needs the user's confirmation.",
                    _obj(loan_id="The loan id, e.g. l_1"),
                    effect="write",
                ),
                lambda loan_id: {"late_fee_cents": lib.return_loan(loan_id)},
            ),
        ]
    )
