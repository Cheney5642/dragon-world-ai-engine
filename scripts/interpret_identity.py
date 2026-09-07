"""CLI and targeted evaluation for Open Identity Interpreter v0.1."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from identity import IdentityInterpretationError, interpret_identity  # noqa: E402
from llm import LLMProviderError, create_llm_client  # noqa: E402


TEST_CASES_PATH = PROJECT_ROOT / "data" / "identity_interpretation_test_cases.json"


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def read_description() -> str:
    print("请描述你想成为谁。输入空行提交：")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line.strip())
    description = "\n".join(lines).strip()
    if not description:
        raise IdentityInterpretationError("Player identity description is empty.")
    return description


def load_test_cases(case_number: int | None = None) -> list[dict[str, str]]:
    try:
        document = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityInterpretationError(
            "Identity Interpretation Evaluation data is invalid."
        ) from exc
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list) or len(cases) != 8:
        raise IdentityInterpretationError(
            "Identity Interpretation Evaluation requires exactly 8 cases."
        )
    if case_number is None:
        return cases
    selected = [case for case in cases if case.get("id") == f"case_{case_number}"]
    if len(selected) != 1:
        raise IdentityInterpretationError(
            f"Identity Interpretation Case {case_number} does not exist."
        )
    return selected


def _combined(result: dict[str, Any], *fields: str) -> str:
    values: list[str] = []
    for field in fields:
        value = result.get(field)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(values).casefold().replace("_", " ")


def _contains(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = re.sub(r"\s+", " ", text.casefold().replace("_", " "))
    return any(pattern.casefold().replace("_", " ") in normalized for pattern in patterns)


def evaluate_case(case_id: str, result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    facts = _combined(result, "candidate_facts", "identity_summary")
    claims = _combined(result, "candidate_claims")
    hints = _combined(result, "capability_hints")

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    require(len(result.get("traits", [])) <= 5, "traits must contain at most 5 items")
    if case_id != "case_8":
        require(
            result.get("display_name") is None,
            "a name may be extracted only when the player explicitly supplies one",
        )
    require(
        not _contains(hints, ("master", "elite", "expert", "commander")),
        "capability hints must remain conservative",
    )

    if case_id == "case_1":
        require(_contains(facts, ("Skeld", "斯凯尔德")), "Skeld identity should be retained")
        require(_contains(facts, ("渔夫", "fisherman", "fisher")), "fisher identity should be retained")
        require(not claims, "ordinary identity should not become a candidate claim")
        require(
            not _contains(
                _combined(result, "traits", "capability_hints"),
                ("勤劳", "hardworking", "comfortable at sea", "small boat"),
            ),
            "fisherman must not imply personality, sea comfort, or boat experience",
        )
    elif case_id == "case_2":
        require(_contains(facts, ("哥布林", "goblin")), "goblin species should be retained")
        require(_contains(facts, ("商人", "merchant", "trader")), "merchant identity should be retained")
        require(not claims, "narrative species should not automatically become a claim")
        require(
            not _contains(
                _combined(result, "traits", "capability_hints"),
                ("务实", "practical", "适应出行", "road travel", "bartering"),
            ),
            "merchant must not imply personality, travel, or bargaining details",
        )
    elif case_id == "case_3":
        require(_contains(facts, ("龙", "dragon")), "Dragon identity should be retained")
        require(_contains(facts, ("年轻", "young")), "young identity should be retained")
        require(
            not _contains(hints, ("fly", "flight", "flying", "fire", "combat", "飞行", "喷火", "战斗")),
            "Dragon identity must not grant automatic gameplay capabilities",
        )
    elif case_id == "case_4":
        require(_contains(claims, ("王子", "prince", "royal")), "royal identity must be a candidate claim")
        require(not result.get("traits"), "royal claim must not imply personality traits")
        require(not hints, "royal claim must not create capabilities")
    elif case_id == "case_5":
        require(_contains(claims, ("Astrid", "深爱", "love")), "NPC relationship must be a candidate claim")
        require(not hints, "NPC relationship claim must not create capabilities")
    elif case_id == "case_6":
        require(_contains(claims, ("Dragon", "龙")), "Dragon control must be a candidate claim")
        require(_contains(claims, ("臣服", "obey", "submit", "control")), "Dragon authority should remain explicit")
        require(not result.get("traits"), "Dragon authority claim must not imply personality traits")
        require(not hints, "Dragon control claim must not create capabilities")
    elif case_id == "case_7":
        require(_contains(facts, ("不记得", "失忆", "remember", "memory", "amnesia")), "memory loss should be retained")
        require(not claims, "memory loss should not become an extraordinary claim")
    elif case_id == "case_8":
        require(
            str(result.get("identity_summary", "")).startswith(
                "AI-generated candidate identity:"
            ),
            "generated identity must carry the exact AI-generated marker",
        )
        require(not claims, "modest generated identity should not add extraordinary claims")
    return failures


def run_test_mode(case_number: int | None = None) -> int:
    client = create_llm_client()
    failures = 0
    for case in load_test_cases(case_number):
        result = interpret_identity(case["input"], provider_client=client)
        case_failures = evaluate_case(case["id"], result)
        passed = not case_failures
        failures += 0 if passed else 1
        print(f"\n{case['id']}: {'PASS' if passed else 'FAIL'}")
        print(f"Input: {case['input']}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if case_failures:
            print("Evaluation:")
            for failure in case_failures:
                print(f"- {failure}")
    print(f"\nSummary: {len(load_test_cases(case_number)) - failures}/{len(load_test_cases(case_number))} cases passed.")
    print("Identity Interpretation is read-only. No Persistent State was modified.")
    return 0 if failures == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test", action="store_true", help="run all 8 targeted cases")
    group.add_argument("--test-case", type=int, metavar="N", help="run one case")
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    try:
        if args.test or args.test_case is not None:
            return run_test_mode(args.test_case)
        result = interpret_identity(read_description())
        print("\nCandidate Identity Preview:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\nPreview only. No Persistent State was modified.")
        return 0
    except (IdentityInterpretationError, LLMProviderError) as exc:
        print(f"Identity Interpreter failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. No Persistent State was modified.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
