"""`python -m assistant` — a small REPL. `/confirm <action_id>` runs a proposed change."""

from assistant.config import router_from_env
from assistant.engine import Assistant
from assistant.library.memory import InMemoryLibrary
from assistant.tools.library_tools import library_tools


def main() -> None:
    bot = Assistant(router_from_env(), library_tools(InMemoryLibrary()))
    print('Ask about books ("Domain-Driven Design"), members (m_ada, m_grace), or borrow. Ctrl-D quits.')
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            return
        if text.startswith("/confirm "):
            print(bot.confirm(text.split()[1]))
            continue
        result = bot.turn(text)
        print(result.reply)
        for p in result.pending:
            warn = f"  ⚠ {'; '.join(p.reasons)}" if p.suspicious else ""
            print(f"  proposed {p.tool} {p.arguments} → /confirm {p.action_id}{warn}")


if __name__ == "__main__":
    main()
