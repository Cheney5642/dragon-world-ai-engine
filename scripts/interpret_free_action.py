"""D2 action preview and targeted semantic evaluation; no server or world access.

--test / --test-case use the real configured provider. Offline safety checks:
python -m unittest discover -s tests -p test_free_action_interpreter.py -v
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from core.free_action_interpreter import (  # noqa: E402
    ActionInterpretationError,
    interpret_action,
    validate_action_interpretation,
)
from llm import LLMProviderError, create_llm_client  # noqa: E402


TEST_CASES_PATH = PROJECT_ROOT / "data" / "free_action_interpretation_test_cases.json"


def load_test_cases() -> list[dict[str, Any]]:
    return json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))["cases"]


def evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Evaluation-only synonyms; no keyword routing in the interpreter."""

    validate_action_interpretation(result)
    failures: list[str] = []
    if result["action_family"] not in case["families"]:
        failures.append(f"action_family should be one of {case['families']}")
    if result["needs_clarification"]:
        failures.append("understandable intent must not require world-fact clarification")
    for field in case["null_fields"]:
        if result[field] is not None:
            failures.append(f"{field} should be null")
    if "goal_operation" in case:
        goal = result["explicit_goal"]
        if goal is None or goal["operation"] != case["goal_operation"]:
            failures.append(f"explicit_goal must {case['goal_operation']}")
    for path, groups in case["contains"].items():
        value: Any = result
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        text = str(value or "").casefold()
        for alternatives in groups:
            if not any(word.casefold() in text for word in alternatives):
                failures.append(f"{path} must retain the meaning of {alternatives}")
    # These checks flag obvious generated outcomes for review, not world rules.
    text = json.dumps(result, ensure_ascii=False).casefold()
    for outcome in (
        "已经到达", "成功骑", "已经杀", "astrid 已死", "astrid已经死",
        "确认拥有", "豪宅确实存在", "发现了一条龙", "已经找到", "脚印证明",
        "successfully", "astrid is dead", "ownership verified", "invalid location",
    ):
        if outcome in text:
            failures.append(f"must preserve intent rather than assert outcome: {outcome}")
    return failures


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test", action="store_true", help="run 12 real provider cases")
    mode.add_argument("--test-case", type=int, choices=range(1, 13), metavar="N")
    mode.add_argument("--input", help="interpret one player action")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        if args.test or args.test_case is not None:
            cases = load_test_cases()
            if args.test_case is not None:
                cases = [case for case in cases if case["id"] == f"case_{args.test_case}"]
            client = create_llm_client()
            print(f"Source mode: real_provider ({client.provider}, {client.model})")
            passed = 0
            for case in cases:
                result = interpret_action(case["input"], provider_client=client)
                failures = evaluate_case(case, result)
                passed += not failures
                print(f"\n{case['id']}: {'FAIL' if failures else 'PASS'}")
                print(f"Input: {case['input']}")
                print(json.dumps(result, ensure_ascii=False, indent=2))
                for failure in failures:
                    print(f"- {failure}")
            print(f"\nSummary: {passed}/{len(cases)} PASS")
            print("Intent only. No database or world state accessed.")
            return int(passed != len(cases))
        player_input = args.input if args.input is not None else input("你想尝试什么？\n")
        print(json.dumps(interpret_action(player_input), ensure_ascii=False, indent=2))
        print("Intent only. No database or world state accessed.")
        return 0
    except LLMProviderError:
        print("Action Interpreter provider failed; see safe provider diagnostics.", file=sys.stderr)
        return 1
    except ActionInterpretationError as exc:
        print(f"Action Interpreter failed: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
