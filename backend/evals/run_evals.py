"""Score the copilot against a fixed set of questions.

    python -m ghostwake.pipeline          # make sure there is data
    python evals/run_evals.py             # offline copilot
    GW_LLM_BASE_URL=... GW_LLM_MODEL=... GW_LLM_API_KEY=... python evals/run_evals.py

Each case checks some of: refused or not, which tool was called, words that must or must
not appear, and that no number in the answer is missing from the tool results.
Prints a table and exits non-zero if the pass rate drops below the bar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ghostwake.copilot import agent
from ghostwake.db import session_factory

PASS_BAR = 0.9


def check(case: dict, out: dict) -> list[str]:
    problems = []
    if case.get("expect_refused", False) != out["refused"]:
        problems.append(f"refused={out['refused']}")
    tool = case.get("expect_tool")
    if tool and tool not in [c["tool"] for c in out["tool_calls"]]:
        problems.append(f"missing tool {tool}")
    for w in case.get("must_contain", []):
        if w.lower() not in out["answer"].lower():
            problems.append(f"missing '{w}'")
    for w in case.get("must_not_contain", []):
        if w.lower() in out["answer"].lower():
            problems.append(f"contains '{w}'")
    if out["checks"]["unverified_numbers"]:
        problems.append(f"unverified numbers {out['checks']['unverified_numbers']}")
    return problems


def main() -> int:
    cases = json.loads((Path(__file__).parent / "copilot_cases.json").read_text())
    passed = 0
    with session_factory()() as s:
        for case in cases:
            out = agent.answer(s, case["question"])
            problems = check(case, out)
            passed += not problems
            mark = "PASS" if not problems else "FAIL"
            print(f"{mark}  {case['id']:<22} {out['mode']:<9} {'; '.join(problems)}")
    rate = passed / len(cases)
    print(f"\n{passed}/{len(cases)} passed ({rate:.0%}), bar {PASS_BAR:.0%}")
    return 0 if rate >= PASS_BAR else 1


if __name__ == "__main__":
    sys.exit(main())
