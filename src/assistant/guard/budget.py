"""Hard limits per turn: a model stuck in a tool loop, or a runaway context,
stops with a clear message instead of an invoice."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Budget:
    max_model_calls: int = 6
    max_tokens: int = 20_000


class BudgetExceeded(Exception):
    pass
