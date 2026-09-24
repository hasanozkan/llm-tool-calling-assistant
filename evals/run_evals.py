"""Run the golden conversations and fail below a pass-rate threshold.

python evals/run_evals.py                       # scripted model, must be 100%
python evals/run_evals.py --threshold 0.8       # e.g. a live model via ASSISTANT_PROVIDER
python evals/run_evals.py --mistakes skip_search   # must FAIL: proves the gate bites
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from assistant.config import router_from_env
from assistant.engine import Assistant
from assistant.library.memory import InMemoryLibrary
from assistant.tools.library_tools import library_tools

CASES = Path(__file__).with_name("cases.yaml")


def check(case: dict[str, Any], mistakes: frozenset[str]) -> list[str]:
    lib = InMemoryLibrary()
    bot = Assistant(router_from_env(mistakes), library_tools(lib))
    r = bot.turn(case["say"])
    problems: list[str] = []
    if "calls" in case and r.tool_calls != case["calls"]:
        problems.append(f"calls {r.tool_calls} != {case['calls']}")
    for text in case.get("reply_contains", []):
        if text not in r.reply:
            problems.append(f"reply lacks {text!r}: {r.reply!r}")
    if "pending" in case and [p.tool for p in r.pending] != case["pending"]:
        problems.append(f"pending {[p.tool for p in r.pending]} != {case['pending']}")
    if "suspicious" in case and any(p.suspicious for p in r.pending) != case["suspicious"]:
        problems.append(f"suspicious should be {case['suspicious']}")
    if "flagged" in case and bool(r.flagged) != case["flagged"]:
        problems.append(f"flagged should be {case['flagged']}")
    if "writes" in case and lib.writes != case["writes"]:
        problems.append(f"writes before confirmation {lib.writes} != {case['writes']}")
    if case.get("confirm"):
        if not r.pending:
            return [*problems, "nothing to confirm"]
        outcome = bot.confirm(r.pending[0].action_id)
        for text in case.get("confirm_contains", []):
            if text not in outcome:
                problems.append(f"confirmation lacks {text!r}: {outcome}")
        if lib.writes != case.get("writes_after_confirm", lib.writes):
            problems.append(f"writes after confirmation {lib.writes} != {case['writes_after_confirm']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=1.0)
    ap.add_argument("--mistakes", default="", help="comma-separated scripted-model faults")
    args = ap.parse_args()
    mistakes = frozenset(m for m in args.mistakes.split(",") if m)
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        problems = check(case, mistakes)
        passed += not problems
        print(f"{'PASS' if not problems else 'FAIL'}  {case['id']}")
        for p in problems:
            print(f"      {p}")
    rate = passed / len(cases)
    print(f"\n{passed}/{len(cases)} passed ({rate:.0%}), threshold {args.threshold:.0%}")
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
