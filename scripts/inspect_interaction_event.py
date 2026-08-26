"""Offline, read-only inspector for NPC Interaction Event v0.1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from npc.context_builder import NpcContextError, build_npc_context  # noqa: E402
from npc.interaction_event import (  # noqa: E402
    NpcInteractionEventError,
    build_interaction_event,
)


SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
CASES_PATH = PROJECT_ROOT / "data" / "npc_interaction_event_test_cases.json"


def _load_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise NpcInteractionEventError(f"{label} does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcInteractionEventError(
            f"{label} could not be read as valid JSON: {path}"
        ) from exc


def _file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_hashes() -> dict[Path, str | None]:
    return {
        path: _file_hash(path)
        for path in (SEED_PATH, SAVE_PATH, PROFILES_PATH)
    }


def _assert_read_only(before: dict[Path, str | None]) -> None:
    changed = [path for path, digest in before.items() if _file_hash(path) != digest]
    if changed:
        raise NpcInteractionEventError(
            "Read-only check failed; protected data changed: "
            + ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in changed)
        )


def _load_case(case_number: int) -> dict[str, Any]:
    document = _load_json(CASES_PATH, "NPC Interaction Event test data")
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list):
        raise NpcInteractionEventError("Test data must contain a cases array.")
    case_id = f"case_{case_number}"
    matches = [case for case in cases if case.get("id") == case_id]
    if len(matches) != 1:
        raise NpcInteractionEventError(f"Unknown Interaction Event case: {case_number}")
    return matches[0]


def _build_from_case(case_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    case = _load_case(case_number)
    world_state = _load_json(SEED_PATH, "World Seed")
    world_state = copy.deepcopy(world_state)
    world_state["player"]["name"] = "Eirik"
    context = build_npc_context(case["npc_id"], world_state)
    response = copy.deepcopy(case["npc_response"])
    event = build_interaction_event(context, case["player_utterance"], response)
    return response, event


def _build_custom(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    missing = [
        flag
        for flag, value in (
            ("--npc-id", args.npc_id),
            ("--utterance", args.utterance),
            ("--response-file", args.response_file),
        )
        if not value
    ]
    if missing:
        raise NpcInteractionEventError(
            "Custom inspection requires: " + ", ".join(missing)
        )

    world_state = _load_json(SEED_PATH, "World Seed")
    world_state = copy.deepcopy(world_state)
    if args.player_name:
        world_state["player"]["name"] = args.player_name
    response_path = Path(args.response_file).resolve()
    response = _load_json(response_path, "Mock NPC Response")
    context = build_npc_context(args.npc_id, world_state)
    event = build_interaction_event(context, args.utterance, response)
    return response, event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a read-only NPC Interaction Event from a Golden Case or an "
            "existing mock NPC Response. This script never calls an LLM."
        )
    )
    parser.add_argument("--case", type=int, help="Inspect offline Golden Case N (1-8).")
    parser.add_argument("--npc-id", help="NPC Entity ID for custom inspection.")
    parser.add_argument("--utterance", help="Player utterance for custom inspection.")
    parser.add_argument("--response-file", help="Path to an existing mock NPC Response JSON.")
    parser.add_argument("--player-name", default="Eirik", help="In-memory player label only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    before = _protected_hashes()
    try:
        if args.case is not None:
            if any((args.npc_id, args.utterance, args.response_file)):
                raise NpcInteractionEventError(
                    "Use either --case or custom inspection arguments, not both."
                )
            response, event = _build_from_case(args.case)
        else:
            response, event = _build_custom(args)
        _assert_read_only(before)
    except (NpcInteractionEventError, NpcContextError) as exc:
        print(f"Interaction Event inspection failed: {exc}", file=sys.stderr)
        return 1

    print("NPC Response Preview:")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    print("\nNPC Interaction Event Preview:")
    print(json.dumps(event, ensure_ascii=False, indent=2))
    print("\nRead-only state check: PASS")
    print("No LLM was called. No Event, Memory, Relationship, or World State was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
