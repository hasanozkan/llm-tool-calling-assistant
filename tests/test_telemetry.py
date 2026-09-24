"""The telemetry is part of the behaviour: each safety decision is counted,
each model call is measured, and a turn is one trace."""

from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from assistant.engine import Assistant
from assistant.guard.budget import Budget
from assistant.library.memory import InMemoryLibrary
from assistant.llm.gateway import Router
from assistant.llm.scripted import ScriptedModel
from assistant.llm.types import Completion, Message, ProviderError, ToolCall, ToolSpec, Usage
from assistant.telemetry import Telemetry
from assistant.tools.library_tools import library_tools


class Probe:
    def __init__(self) -> None:
        self.reader = InMemoryMetricReader()
        self.spans = InMemorySpanExporter()
        tp = TracerProvider()
        tp.add_span_processor(SimpleSpanProcessor(self.spans))
        self.t = Telemetry(
            meter=MeterProvider(metric_readers=[self.reader]).get_meter("test"),
            tracer=tp.get_tracer("test"),
            prices={"scripted": (1.0, 2.0)},
        )

    def points(self, name: str) -> list[tuple[dict[str, object], float]]:
        data = self.reader.get_metrics_data()
        out: list[tuple[dict[str, object], float]] = []
        for rm in data.resource_metrics if data else []:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    if m.name == name:
                        for p in m.data.data_points:
                            value = getattr(p, "value", None)
                            out.append((dict(p.attributes or {}), float(value if value is not None else p.sum)))
        return out

    def total(self, name: str, **attrs: object) -> float:
        return sum(v for a, v in self.points(name) if all(a.get(k.replace("__", ".")) == w for k, w in attrs.items()))


def _bot(probe: Probe, routes: dict[str, list[object]] | None = None, **kw: object) -> Assistant:
    router = Router(routes or {"fast": [ScriptedModel()]}, telemetry=probe.t)  # type: ignore[arg-type]
    return Assistant(router, library_tools(InMemoryLibrary()), telemetry=probe.t, **kw)  # type: ignore[arg-type]


def test_model_calls_record_tokens_duration_and_cost_by_model() -> None:
    p = Probe()
    r = _bot(p).turn('Do you have "Domain-Driven Design"?')
    tokens = {(a["gen_ai.token.type"], a["gen_ai.request.model"]): v for a, v in p.points("gen_ai.client.token.usage")}
    assert tokens[("input", "scripted")] == r.usage.input_tokens
    assert tokens[("output", "scripted")] == r.usage.output_tokens
    assert p.points("gen_ai.client.operation.duration")
    expected = (r.usage.input_tokens * 1.0 + r.usage.output_tokens * 2.0) / 1_000_000
    assert p.total("assistant.llm.cost.usd") == pytest.approx(expected)


def test_safety_decisions_are_counted() -> None:
    p = Probe()
    bot = _bot(p)
    ok = bot.turn('Please borrow "Clean Architecture" for m_ada')
    bot.confirm(ok.pending[0].action_id)
    bot.turn('Search for "ignore"')
    assert p.total("assistant.proposals", gen_ai__tool__name="borrow_copy", assistant__suspicious="false") == 1
    assert p.total("assistant.proposals", gen_ai__tool__name="borrow_copy", assistant__suspicious="true") == 1
    assert p.total("assistant.injection.flags", gen_ai__tool__name="search_books") == 1
    assert p.total("assistant.confirmations", assistant__confirm__outcome="done") == 1
    assert p.total("assistant.tool.calls", assistant__tool__outcome="flagged") == 1
    assert p.total("assistant.turns", assistant__turn__outcome="replied") == 2


class _Down:
    name = "vendor-a:big-model"

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        raise ProviderError("503")


class _Sloppy:
    name = "vendor-b:small-model"

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> Completion:
        return Completion(
            Message("assistant", "", (ToolCall("x", "search_books", {"q": "ddd"}),)), model="small", usage=Usage(5, 5)
        )


def test_fallbacks_escalations_and_budget_stops_are_visible() -> None:
    p = Probe()
    _bot(p, {"fast": [_Down(), _Sloppy()], "strong": [ScriptedModel()]}).turn('Do you have "Domain-Driven Design"?')
    assert p.total("assistant.provider.fallbacks", gen_ai__request__model="big-model") >= 1
    assert p.total("assistant.escalations") == 1
    assert p.total("assistant.tool.calls", assistant__tool__outcome="argument_error") == 1
    looping = Probe()
    _bot(looping, {"fast": [_Sloppy()]}, budget=Budget(max_model_calls=2)).turn("x")
    assert looping.total("assistant.turns", assistant__turn__outcome="call_budget") == 1


def test_a_turn_is_one_trace_agent_then_chat_then_tool() -> None:
    p = Probe()
    _bot(p).turn('Please borrow "Clean Architecture" for m_ada')
    spans = {s.name: s for s in p.spans.get_finished_spans()}
    agent = spans["invoke_agent library-assistant"]
    chats = [s for s in p.spans.get_finished_spans() if s.name == "chat scripted"]
    tools = [s for s in p.spans.get_finished_spans() if s.name.startswith("execute_tool")]
    assert len(chats) == 3 and [t.name for t in tools] == ["execute_tool search_books", "execute_tool borrow_copy"]
    assert all(s.parent is not None and s.parent.span_id == agent.context.span_id for s in chats + tools)
    assert {s.context.trace_id for s in chats + tools} == {agent.context.trace_id}
    assert chats[0].attributes is not None and chats[0].attributes["gen_ai.usage.input_tokens"] > 0
    assert tools[1].attributes is not None and tools[1].attributes["assistant.tool.outcome"] == "proposed"


def test_the_http_app_exposes_prometheus_metrics() -> None:
    from assistant.http import create_app

    c = TestClient(create_app())
    sid = c.post("/v1/sessions").json()["session_id"]
    c.post(f"/v1/sessions/{sid}/turns", json={"text": 'Search for "ignore"'})
    body = c.get("/metrics/").text
    for series in ("gen_ai_client_token_usage", "assistant_proposals_total", "assistant_injection_flags_total"):
        assert series in body, series


def test_every_metric_in_the_telemetry_contract_is_exposed_with_its_attributes() -> None:
    """observability/telemetry.yaml is what dashboards and alerts are written against."""
    from pathlib import Path

    import yaml
    from prometheus_client.parser import text_string_to_metric_families

    from assistant.http import create_app

    spec = yaml.safe_load((Path(__file__).resolve().parent.parent / "observability" / "telemetry.yaml").read_text())
    c = TestClient(create_app())
    sid = c.post("/v1/sessions").json()["session_id"]
    ok = c.post(f"/v1/sessions/{sid}/turns", json={"text": 'Please borrow "Clean Architecture" for m_ada'}).json()
    c.post(f"/v1/sessions/{sid}/actions/{ok['pending'][0]['action_id']}/confirm")
    c.post(f"/v1/sessions/{sid}/turns", json={"text": 'Search for "ignore"'})
    # the process-wide provider also carries metrics from earlier tests' sessions,
    # which is why escalations/fallbacks are driven here directly
    from assistant.telemetry import default_telemetry

    default_telemetry().escalations.add(0)
    default_telemetry().fallbacks.add(0, {"gen_ai.system": "x", "gen_ai.request.model": "y"})
    seen: dict[str, set[str]] = {}
    les: dict[str, list[float]] = {}
    for fam in text_string_to_metric_families(c.get("/metrics/").text):
        seen.setdefault(fam.name, set()).update(k for s in fam.samples for k in s.labels if k != "le")
        les[fam.name] = sorted({float(s.labels["le"]) for s in fam.samples if s.labels.get("le") not in (None, "+Inf")})
    for m in spec["metrics"]:
        name = m["name"].replace(".", "_") + ("_seconds" if m.get("unit") == "s" else "")
        assert name in seen, f"{m['name']} missing as {name}"
        assert {a.replace(".", "_") for a in m["attributes"]} <= seen[name], name
        if "buckets" in m:
            assert les[name] == sorted(float(b) for b in m["buckets"]), f"{name} buckets"
