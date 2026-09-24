"""Write tools never run on the model's say-so (ADR-0002). The engine turns a
write call into a PendingAction; only `Assistant.confirm(action_id)` runs it.

`suspicious` marks a proposal the *user* did not ask for — a write that
appeared after untrusted tool output, with no write verb in the user's own
message. The UI shows it with a warning; it still cannot run by itself.
"""

import re
from dataclasses import dataclass, field
from typing import Any

WRITE_INTENT = re.compile(r"\b(borrow|lend|check ?out|return|give back)\b", re.IGNORECASE)


@dataclass(slots=True)
class PendingAction:
    action_id: str
    tool: str
    arguments: dict[str, Any]
    suspicious: bool = False
    reasons: list[str] = field(default_factory=list)


def user_asked_for_a_write(user_text: str) -> bool:
    return bool(WRITE_INTENT.search(user_text))
