"""One interface in front of every model, and a router that picks one.

Routing is by *tier*, not by vendor: the engine asks for `fast` or `strong`
and the router walks that tier's providers in order, falling back on
`ProviderError`. Swapping a vendor is configuration, not code.
"""

from collections.abc import Sequence
from typing import Literal, Protocol

from assistant.llm.types import Completion, Message, ProviderError, ToolSpec

Tier = Literal["fast", "strong"]


class LLMProvider(Protocol):
    name: str

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion: ...


class Router:
    def __init__(self, routes: dict[Tier, list[LLMProvider]]) -> None:
        if not routes.get("fast"):
            raise ValueError("the fast tier needs at least one provider")
        self._routes = routes

    def complete(self, tier: Tier, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        providers = self._routes.get(tier) or self._routes["fast"]
        errors: list[str] = []
        for provider in providers:
            try:
                return provider.complete(messages, tools)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
        raise ProviderError("; ".join(errors) or "no provider")
