"""What the assistant may do in the library — the domain behind the tools.
A real deployment implements this against the library's HTTP API; the
in-memory adapter keeps the sample and its evals self-contained."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BookHit:
    isbn: str
    title: str
    author: str
    available_copy_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemberStatus:
    member_id: str
    active_loans: int
    max_loans: int
    outstanding_fees_cents: int


@dataclass(frozen=True, slots=True)
class LoanReceipt:
    loan_id: str
    copy_id: str
    due_on: str


class LibraryError(Exception):
    """A domain refusal the model should read and explain, e.g. `loan_limit_reached`."""


class LibraryPort(Protocol):
    def search(self, query: str) -> list[BookHit]: ...
    def member_status(self, member_id: str) -> MemberStatus: ...
    def borrow(self, member_id: str, copy_id: str) -> LoanReceipt: ...
    def return_loan(self, loan_id: str) -> int: ...  # late fee in cents
