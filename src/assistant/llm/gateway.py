"""One interface in front of every model, and a router that picks one.

Routing is by *tier*, not by vendor: the engine asks for `fast` or `strong`
and the router walks that tier's providers in order, falling back on
`ProviderError`. Swapping a vendor is configuration, not code.
"""

import time
from collections.abc import Sequence
from typing import Literal, Protocol

from opentelemetry.trace import SpanKind, Status, StatusCode

from assistant.llm.types import Completion, Message, ProviderError, ToolSpec
from assistant.telemetry import Telemetry, default_telemetry, split_provider_name

Tier = Literal["fast", "strong"]


class LLMProvider(Protocol):
    name: str

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion: ...


class Router:
    def __init__(self, routes: dict[Tier, list[LLMProvider]], telemetry: Telemetry | None = None) -> None:
        if not routes.get("fast"):
            raise ValueError("the fast tier needs at least one provider")
        self._routes = routes
        self._t = telemetry or default_telemetry()

    def complete(self, tier: Tier, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        providers = self._routes.get(tier) or self._routes["fast"]
        errors: list[str] = []
        for provider in providers:
            system, model = split_provider_name(provider.name)
            attrs = {"gen_ai.operation.name": "chat", "gen_ai.system": system, "gen_ai.request.model": model}
            with self._t.tracer.start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT, attributes=attrs) as span:
                started = time.perf_counter()
                try:
                    completion = provider.complete(messages, tools)
                except ProviderError as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.set_attribute("error.type", type(exc).__name__)
                    self._t.fallbacks.add(1, {"gen_ai.system": system, "gen_ai.request.model": model})
                    errors.append(f"{provider.name}: {exc}")
                    continue
                usage = completion.usage
                span.set_attribute("gen_ai.response.model", completion.model)
                span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
                self._t.record_usage(
                    system=system,
                    model=model,
                    tier=tier,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    seconds=time.perf_counter() - started,
                )
                return completion
        raise ProviderError("; ".join(errors) or "no provider")
