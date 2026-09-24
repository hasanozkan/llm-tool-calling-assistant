# ADR-0001 — One gateway, routed by tier

**Status:** accepted

## Decision
The engine talks to `Router`, never to a vendor SDK. Providers implement one
method, `complete(messages, tools)`, over provider-neutral types; adapters map
wire formats (OpenAI-compatible chat completions, Anthropic messages). The
router picks by **tier** (`fast`, `strong`) and falls back within a tier on
`ProviderError`.

## Why
Models change every few months and pricing more often. A vendor switch, a
fallback during an outage, or "use the cheap model unless it stumbles" are
configuration — the domain, the tools and the guards do not move.

## Rejected
- **A vendor SDK in the engine** — every switch becomes a refactor.
- **Routing by vendor name** — the engine should ask for a capability, not a brand.
