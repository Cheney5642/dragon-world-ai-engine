"""CLI for Unified NPC Mutation Bridge v0.1; no LLM is called."""

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

from npc.interaction_event import (  # noqa: E402
    NpcInteractionEventError,
    validate_interaction_event,
)
from npc.interaction_runtime import (  # noqa: E402
    NpcInteractionRuntimeError,
    validate_interaction_runtime_result,
)
from npc.memory import (  # noqa: E402
    MEMORY_STORE_PATH,
    DuplicateMemoryError,
    MemoryStoreError,
    NpcMemoryError,
)
from npc.mutation_bridge import (  # noqa: E402
    MutationUnavailableError,
    NpcMutationBridgeError,
    commit_npc_mutation_plan,
    prepare_npc_mutation_plan,
)
from npc.relationship_store import (  # noqa: E402
    RELATIONSHIP_STORE_PATH,
    DuplicateRelationshipEventError,
    NpcRelationshipPersistenceError,
    RelationshipStoreError,
)
from scripts.commit_npc_memory import (  # noqa: E402
    build_case_interaction_event,
    load_memory_case,
)
from scripts.commit_npc_relationship import load_relationship_case  # noqa: E402


CASES_PATH = PROJECT_ROOT / "data" / "npc_mutation_bridge_test_cases.json"
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise NpcMutationBridgeError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcMutationBridgeError(
            f"{label} is not valid readable JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise NpcMutationBridgeError(f"{label} must contain a JSON object: {path}")
    return value


def load_bridge_case(case_number: int) -> dict[str, Any]:
    document = load_json(CASES_PATH, "NPC Mutation Bridge Golden Cases")
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise NpcMutationBridgeError(
            "NPC Mutation Bridge Golden Cases require exactly 8 cases."
        )
    case_id = f"case_{case_number}"
    matches = [case for case in cases if case.get("id") == case_id]
    if len(matches) != 1:
        raise NpcMutationBridgeError(f"Unknown NPC Mutation Bridge case: {case_number}")
    return copy.deepcopy(matches[0])


def resolve_case_event(case: dict[str, Any]) -> dict[str, Any]:
    fixture = case["event_fixture"]
    if fixture["dataset"] == "npc_memory":
        event = build_case_interaction_event(load_memory_case(fixture["case"]))
    elif fixture["dataset"] == "npc_relationship":
        event = load_relationship_case(fixture["case"])["interaction_event"]
    else:
        raise NpcMutationBridgeError(
            f"Unsupported Golden Event dataset: {fixture['dataset']}"
        )
    validate_interaction_event(event)
    return event


def load_event_file(path: Path) -> dict[str, Any]:
    event = load_json(path.resolve(), "Runtime NPC Interaction Event")
    try:
        validate_interaction_event(event)
    except NpcInteractionEventError as exc:
        raise NpcMutationBridgeError(
            f"Runtime Interaction Event is invalid: {exc}"
        ) from exc
    return event


def load_runtime_result_event(path: Path) -> dict[str, Any]:
    result = load_json(path.resolve(), "Unified NPC Runtime Result")
    try:
        validate_interaction_runtime_result(result)
    except NpcInteractionRuntimeError as exc:
        raise NpcMutationBridgeError(
            f"Unified NPC Runtime Result is invalid: {exc}"
        ) from exc
    event = result["interaction_event"]
    if result["interaction_available"] is not True or not isinstance(event, dict):
        raise NpcMutationBridgeError(
            "Unified NPC Runtime Result has no available Interaction Event."
        )
    return copy.deepcopy(event)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview and independently confirm Memory / Relationship mutations "
            "from one validated Interaction Event. No LLM is called."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--case",
        type=int,
        choices=range(1, 9),
        metavar="N",
        help="NPC Mutation Bridge Golden Case number (1-8).",
    )
    source.add_argument(
        "--event-file",
        type=Path,
        help="Validated NPC Interaction Event JSON file.",
    )
    source.add_argument(
        "--runtime-result-file",
        type=Path,
        help="Validated Unified NPC Runtime Result JSON file.",
    )
    parser.add_argument(
        "--memory-store",
        type=Path,
        default=MEMORY_STORE_PATH,
        help="Memory Store path.",
    )
    parser.add_argument(
        "--relationship-store",
        type=Path,
        default=RELATIONSHIP_STORE_PATH,
        help="Relationship Store path.",
    )
    return parser.parse_args()


def load_event_source(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.case is not None:
        return "golden_fixture", resolve_case_event(load_bridge_case(args.case))
    if args.event_file is not None:
        return "runtime_event", load_event_file(args.event_file)
    if args.runtime_result_file is not None:
        return "unified_runtime_result", load_runtime_result_event(
            args.runtime_result_file
        )
    raise NpcMutationBridgeError("Exactly one Event source mode is required.")


def ask_confirmation(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        answer = ""
    return answer.strip().casefold() in {"y", "yes"}


def print_plan(event: dict[str, Any], plan: dict[str, Any]) -> None:
    print("Interaction Event Summary:")
    print(
        json.dumps(
            {
                "event_id": event["event_id"],
                "npc_id": event["npc_id"],
                "player_id": event["player_id"],
                "topic": event["topic"],
                "memory_candidate": event["memory_candidate"],
                "relationship_signal": event["relationship_signal"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("Memory Mutation Preview:")
    print(json.dumps(plan["memory"], ensure_ascii=False, indent=2))
    print("Relationship Mutation Preview:")
    print(json.dumps(plan["relationship"], ensure_ascii=False, indent=2))
    print(f"Has any mutation: {str(plan['has_any_mutation']).lower()}")


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    memory_store_path = args.memory_store.resolve()
    relationship_store_path = args.relationship_store.resolve()
    protected_paths = (SEED_PATH, SAVE_PATH, PROFILES_PATH)
    hashes_before = {
        path: file_hash(path)
        for path in (*protected_paths, memory_store_path, relationship_store_path)
    }

    try:
        source_mode, event = load_event_source(args)
        plan = prepare_npc_mutation_plan(
            event,
            relationship_store_path=relationship_store_path,
        )
        print(f"Source mode: {source_mode}")
        print_plan(event, plan)

        commit_memory = False
        commit_relationship = False
        if plan["memory"]["commit_available"]:
            commit_memory = ask_confirmation("Commit Memory? [y/N]: ")
        if plan["relationship"]["commit_available"]:
            commit_relationship = ask_confirmation(
                "Commit Relationship Change? [y/N]: "
            )

        if commit_memory or commit_relationship:
            commit_result = commit_npc_mutation_plan(
                event,
                plan,
                commit_memory=commit_memory,
                commit_relationship=commit_relationship,
                memory_store_path=memory_store_path,
                relationship_store_path=relationship_store_path,
            )
            print("Commit Result:")
            print(json.dumps(commit_result, ensure_ascii=False, indent=2))
            print(
                "Cross-store transaction: unsupported; each selected Store was "
                "committed independently."
            )
        elif plan["has_any_mutation"]:
            print("All available mutations were cancelled. Stores were not modified.")
        else:
            print("No persistent mutation is available. No confirmation was requested.")
    except (
        DuplicateMemoryError,
        DuplicateRelationshipEventError,
        MemoryStoreError,
        MutationUnavailableError,
        NpcMemoryError,
        NpcMutationBridgeError,
        NpcRelationshipPersistenceError,
        RelationshipStoreError,
    ) as exc:
        print(f"NPC Mutation Bridge failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. No further mutation was committed.", file=sys.stderr)
        return 130

    after = {
        path: file_hash(path)
        for path in (*protected_paths, memory_store_path, relationship_store_path)
    }
    illegal_changes = [
        path
        for path in protected_paths
        if after[path] != hashes_before[path]
    ]
    if not commit_memory and after[memory_store_path] != hashes_before[memory_store_path]:
        illegal_changes.append(memory_store_path)
    if (
        not commit_relationship
        and after[relationship_store_path] != hashes_before[relationship_store_path]
    ):
        illegal_changes.append(relationship_store_path)
    if illegal_changes:
        print(
            "Safety error: unauthorized Persistent State changed: "
            + ", ".join(str(path) for path in illegal_changes),
            file=sys.stderr,
        )
        return 1

    print("Persistent boundary check: PASS")
    print("No LLM was called.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
