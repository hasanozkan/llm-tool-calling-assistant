"""Provider-neutral message and tool types. Every adapter maps to and from
these; nothing above the `llm` package ever sees a vendor's wire format."""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # role == "tool": which call this answers
    untrusted: bool = False  # role == "tool": content came from outside the system


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (object)
    effect: Literal["read", "write"] = "read"


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class Completion:
    message: Message
    model: str
    usage: Usage = field(default_factory=Usage)


class ProviderError(Exception):
    """A provider could not answer (network, rate limit, 5xx). The router may
    try the next provider; the engine never sees vendor exceptions."""
