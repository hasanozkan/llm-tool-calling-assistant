# ADR-0003 — Golden conversations are a CI gate, and the gate is proven

**Status:** accepted

## Decision
`evals/cases.yaml` lists conversations with what must and must not happen:
the tool calls, the reply, the proposed writes, and — read from the library
itself — what was actually written before and after confirmation. CI runs
them against a deterministic scripted model at 100%. The same cases score a
live model (`make evals-live`) at a lower threshold.

`make evals-negative` runs a scripted model with a known fault (borrowing
without searching) and requires the gate to fail.

## Why
Checking the reply text alone is how a regression hides: the assistant can
say the right thing while doing the wrong one. Asserting on effects — calls
made, rows written — is what makes an eval a gate.
