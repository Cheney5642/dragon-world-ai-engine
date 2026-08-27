"""Read-only CLI for NPC Relationship Change Preview v0.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.relationship import (  # noqa: E402
    NpcRelationshipError,
    evaluate_relationship_change,
)


CASES_PATH = PROJECT_ROOT / "data" / "npc_relationship_test_cases.json"
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "saves" / "npc_memories.json",
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "npc" / "interaction_event.py",
    PROJECT_ROOT / "npc" / "memory.py",
    PROJECT_ROOT / "npc" / "memory_retriever.py",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "response_runtime_v0_2.py",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def load_relationship_case(case_number: int) -> dict[str, Any]:
    try:
        document = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcRelationshipError(
            "NPC Relationship Evaluation data is not valid JSON."
        ) from exc
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list) or len(cases) != 8:
        raise NpcRelationshipError(
            "NPC Relationship Evaluation requires exactly 8 cases."
        )
    expected_id = f"case_{case_number}"
    selected = [case for case in cases if case.get("id") == expected_id]
    if len(selected) != 1:
        raise NpcRelationshipError(
            f"NPC Relationship Evaluation Case {case_number} is missing."
        )
    return selected[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect one deterministic Relationship Change Preview."
    )
    parser.add_argument(
        "--case",
        type=int,
        required=True,
        choices=range(1, 9),
        metavar="N",
        help="Golden Case number from 1 to 8",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    hashes_before = {path: file_hash(path) for path in PROTECTED_PATHS}

    try:
        case = load_relationship_case(args.case)
        preview = evaluate_relationship_change(
            case["current_relationship"],
            case["interaction_event"],
        )
    except NpcRelationshipError as exc:
        print(f"Relationship Evaluation failed: {exc}", file=sys.stderr)
        return 1

    hashes_after = {path: file_hash(path) for path in PROTECTED_PATHS}
    if hashes_after != hashes_before:
        print("Read-only safety check failed: protected state changed.", file=sys.stderr)
        return 1

    print(f"Case: {case['id']} — {case['name']}")
    print("\nCurrent Relationship:")
    print(json.dumps(case["current_relationship"], ensure_ascii=False, indent=2))
    print("\nValidated Interaction Event:")
    print(json.dumps(case["interaction_event"], ensure_ascii=False, indent=2))
    print("\nRelationship Change Preview:")
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    print("\nRead-only hash check: PASS")
    print("No Relationship Store, Memory, or World State was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
