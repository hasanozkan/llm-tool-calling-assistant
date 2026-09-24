"""Tools = a spec the model sees + a handler the engine runs.

Arguments are validated against the spec before a handler runs: a model that
invents a parameter or drops a required one gets a precise error back, which
it can correct — instead of a stack trace or, worse, a silently wrong call.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from assistant.llm.types import ToolSpec

Handler = Callable[..., Any]


class ToolArgumentError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    handler: Handler


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.spec.name: t for t in tools}

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolArgumentError(f"unknown tool {name!r}; available: {sorted(self._tools)}")
        return self._tools[name]

    def validate(self, name: str, arguments: dict[str, Any]) -> None:
        schema = self.get(name).spec.parameters
        props: dict[str, Any] = schema.get("properties", {})
        missing = [p for p in schema.get("required", []) if p not in arguments]
        extra = [a for a in arguments if a not in props]
        wrong = [
            a
            for a, v in arguments.items()
            if a in props and props[a].get("type") == "string" and not isinstance(v, str)
        ]
        if missing or extra or wrong:
            raise ToolArgumentError(
                json.dumps({"tool": name, "missing": missing, "unexpected": extra, "not_a_string": wrong})
            )

    def run(self, name: str, arguments: dict[str, Any]) -> Any:
        self.validate(name, arguments)
        return self.get(name).handler(**arguments)
