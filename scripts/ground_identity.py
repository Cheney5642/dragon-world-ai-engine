"""Offline targeted evaluation for deterministic Identity Grounding v0.1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from identity.grounding import (  # noqa: E402
    IdentityGroundingError,
    ground_identity,
    load_identity_grounding_schema,
)
from identity.interpreter import (  # noqa: E402
    load_identity_interpretation_schema,
    validate_identity_interpretation,
)


TEST_CASES_PATH = PROJECT_ROOT / "data" / "identity_grounding_test_cases.json"


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def load_test_cases(case_number: int | None = None) -> list[dict[str, Any]]:
    try:
        document = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityGroundingError(
            "Identity Grounding Evaluation data is invalid."
        ) from exc
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list) or len(cases) != 10:
        raise IdentityGroundingError(
            "Identity Grounding Evaluation requires exactly 10 cases."
        )
    if case_number is None:
        return cases
    selected = [case for case in cases if case.get("id") == f"case_{case_number}"]
    if len(selected) != 1:
        raise IdentityGroundingError(
            f"Identity Grounding Case {case_number} does not exist."
        )
    return selected


def evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    expected = case["expected"]
    failures: list[str] = []
    if result["accepted_facts"] != expected["accepted_facts"]:
        failures.append("accepted_facts did not match the expected Grounding")
    if result["unverified_claims"] != expected["unverified_claims"]:
        failures.append("unverified_claims did not match the expected Grounding")
    if result["accepted_traits"] != case["interpretation"]["traits"]:
        failures.append("ordinary B1 traits were not preserved")
    if (
        result["accepted_capability_hints"]
        != case["interpretation"]["capability_hints"]
    ):
        failures.append("ordinary B1 capability hints were not preserved")
    return failures


def run_tests(case_number: int | None = None) -> int:
    interpretation_schema = load_identity_interpretation_schema()
    grounding_schema = load_identity_grounding_schema()
    cases = load_test_cases(case_number)
    failed = 0
    for case in cases:
        interpretation = case["interpretation"]
        validate_identity_interpretation(interpretation, interpretation_schema)
        result = ground_identity(interpretation, schema=grounding_schema)
        failures = evaluate_case(case, result)
        passed = not failures
        failed += 0 if passed else 1
        print(f"\n{case['id']}: {'PASS' if passed else 'FAIL'}")
        print(f"Input: {case['input']}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        for failure in failures:
            print(f"- {failure}")
    print(f"\nSummary: {len(cases) - failed}/{len(cases)} cases passed.")
    print("Grounding is deterministic and read-only. No LLM or state mutation was used.")
    return 0 if failed == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="run all 10 cases")
    group.add_argument("--test-case", type=int, metavar="N", help="run one case")
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    try:
        return run_tests(args.test_case)
    except IdentityGroundingError as exc:
        print(f"Identity Grounding failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
