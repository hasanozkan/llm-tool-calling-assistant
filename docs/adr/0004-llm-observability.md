# ADR-0004 — LLM observability on OpenTelemetry, alerts shipped with the service

**Status:** accepted

## Decision
- **OpenTelemetry, not a vendor SDK.** Metrics and traces go through the OTel
  API; the process exports metrics for Prometheus to scrape (`/metrics`) and
  traces over OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (Tempo, Jaeger,
  or a commercial APM). Switching backends is configuration.
- **GenAI semantic conventions first.** `gen_ai.client.token.usage`,
  `gen_ai.client.operation.duration`, `gen_ai.request.model`, `gen_ai.tool.name`,
  and the span names `invoke_agent {agent}` → `chat {model}` / `execute_tool {tool}`.
  Anything that reads the conventions reads this service.
- **The agent's safety behaviour is measured too** (`assistant.*`): proposals
  and whether they were suspicious, injection flags, confirmations (including
  a suspicious one a person overrode), escalations to the strong tier,
  provider fallbacks, turns that hit a budget, and estimated spend from a
  price table.
- **Alerts live with the service** (`observability/alerts.yaml`) and are
  unit-tested with `promtool` both ways — each rule fires on its pattern and
  stays quiet just below it. CI runs them.

## Why
Token cost, latency and provider health are what an LLM feature is
operated on. But the signal that is specific to agents is behavioural: a
burst of writes nobody asked for is what an injection campaign looks like
from the outside, and it is only visible if the decision the guard made is
counted where the decision is made.

## Rejected
- **Logging prompts and completions as the observability story** — high
  volume, personal data, and still no numbers to alert on.
- **A vendor's LLM tracing SDK in the engine** — it would couple the engine to
  one backend the way ADR-0001 keeps it uncoupled from one model vendor.
