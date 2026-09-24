"""LLM and agent telemetry, on OpenTelemetry (ADR-0004).

Names follow the OpenTelemetry GenAI semantic conventions where they exist
(`gen_ai.client.token.usage`, `gen_ai.client.operation.duration`,
`gen_ai.request.model`, `gen_ai.tool.name`, span names `chat {model}`,
`execute_tool {tool}`, `invoke_agent {agent}`), so any OTel backend reads
them without a mapping. What the conventions do not cover — the agent's own
safety behaviour — is namespaced `assistant.*`.

The instruments come from providers passed in; production passes the global
ones (configured in `assistant.http`), tests pass in-memory readers.
"""

import json
import os
from dataclasses import dataclass, field

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer

AGENT_NAME = "library-assistant"

# The GenAI semantic conventions' advised boundaries (observability/telemetry.yaml).
# The SDK's defaults are sized for milliseconds: seconds would all land in the
# first bucket and every percentile would be a guess.
TOKEN_BUCKETS = [1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]
DURATION_BUCKETS = [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]

# USD per million tokens, (input, output). Configure real prices with
# ASSISTANT_PRICES='{"<model-id>": [3.0, 15.0]}'; unknown models record no cost
# rather than a wrong one.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {"scripted": (0.0, 0.0)}


def prices_from_env() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("ASSISTANT_PRICES")
    extra = {k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()} if raw else {}
    return {**DEFAULT_PRICES, **extra}


@dataclass
class Telemetry:
    meter: Meter = field(default_factory=lambda: metrics.get_meter("assistant"))
    tracer: Tracer = field(default_factory=lambda: trace.get_tracer("assistant"))
    prices: dict[str, tuple[float, float]] = field(default_factory=prices_from_env)

    def __post_init__(self) -> None:
        m = self.meter
        # GenAI semantic conventions
        self.token_usage = m.create_histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Tokens per model call, by type",
            explicit_bucket_boundaries_advisory=TOKEN_BUCKETS,
        )
        self.operation_duration = m.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="Model call duration",
            explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
        )
        # agent behaviour
        self.cost = m.create_counter(
            "assistant.llm.cost.usd", description="Estimated spend in USD, from the price table"
        )
        self.fallbacks = m.create_counter(
            "assistant.provider.fallbacks", description="Provider errors that moved to the next provider"
        )
        self.tool_calls = m.create_counter("assistant.tool.calls", description="Tool calls by outcome")
        self.proposals = m.create_counter("assistant.proposals", description="Writes proposed for confirmation")
        self.confirmations = m.create_counter("assistant.confirmations", description="Proposals the user confirmed")
        self.injection_flags = m.create_counter(
            "assistant.injection.flags", description="Tool outputs that read like instructions"
        )
        self.escalations = m.create_counter(
            "assistant.escalations", description="Turns moved from the fast to the strong tier"
        )
        self.turns = m.create_counter("assistant.turns", description="Turns by how they ended")

    def record_usage(
        self, *, system: str, model: str, tier: str, input_tokens: int, output_tokens: int, seconds: float
    ) -> None:
        base = {"gen_ai.system": system, "gen_ai.request.model": model, "assistant.tier": tier}
        self.token_usage.record(input_tokens, {**base, "gen_ai.token.type": "input"})
        self.token_usage.record(output_tokens, {**base, "gen_ai.token.type": "output"})
        self.operation_duration.record(seconds, {**base, "gen_ai.operation.name": "chat"})
        if model in self.prices:
            per_in, per_out = self.prices[model]
            self.cost.add((input_tokens * per_in + output_tokens * per_out) / 1_000_000, base)


def split_provider_name(name: str) -> tuple[str, str]:
    """`anthropic:claude-x` → ("anthropic", "claude-x"); `scripted` → ("scripted", "scripted")."""
    system, _, model = name.partition(":")
    return system, model or system


_default: Telemetry | None = None


def default_telemetry() -> Telemetry:
    """One set of instruments per process, bound to the global providers."""
    global _default
    if _default is None:
        _default = Telemetry()
    return _default


_configured = False


def configure_global_providers(service_name: str = "llm-tool-calling-assistant") -> None:
    """Prometheus pull for metrics; OTLP push for traces when
    OTEL_EXPORTER_OTLP_ENDPOINT is set (Tempo, Jaeger, any OTLP backend).
    Idempotent: OTel allows setting the global providers once per process."""
    global _configured
    if _configured:
        return
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create({"service.name": service_name})
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()]))
    tracer_provider = TracerProvider(resource=resource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    _configured = True
