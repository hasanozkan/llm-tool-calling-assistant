# ADR-0002 — Tools that change the world wait for the user

**Status:** accepted

## Decision
Every tool declares an `effect`: `read` or `write`. The engine runs reads and
turns writes into `PendingAction`s; only `Assistant.confirm(action_id)` executes
one. A proposal the user did not ask for — no write verb in their message, or
made right after tool output that contained instructions — is marked
`suspicious` with its reasons.

## Why
Prompt injection cannot be fully *detected*: a new phrasing always gets
through. It can be made *harmless*: tool output is wrapped and labelled as
untrusted data, and no amount of persuasion lets the model execute a write.
Detection becomes a warning on the confirmation, not the last line of defence.
