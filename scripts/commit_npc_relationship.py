"""Preview and explicitly commit one NPC Relationship mutation without an LLM."""

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
from npc.relationship_store import (  # noqa: E402
    RELATIONSHIP_STORE_PATH,
    DuplicateRelationshipEventError,
    NoRelationshipChangeRequiredError,
    NpcRelationshipPersistenceError,
    RelationshipStoreError,
    build_persistent_relationship_preview,
    confirm_and_commit_relationship,
)


PERSISTENCE_CASES_PATH = (
    PROJECT_ROOT / "data" / "npc_relationship_persistence_test_cases.json"
)
C1_RELATIONSHIP_CASES_PATH = (
    PROJECT_ROOT / "data" / "npc_relationship_test_cases.json"
)
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
MEMORY_STORE_PATH = PROJECT_ROOT / "data" / "saves" / "npc_memories.json"
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
        raise NpcRelationshipPersistenceError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcRelationshipPersistenceError(
            f"{label} is not valid readable JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise NpcRelationshipPersistenceError(
            f"{label} must contain a JSON object: {path}"
        )
    return value


def load_relationship_case(case_number: int) -> dict[str, Any]:
    document = load_json(
        PERSISTENCE_CASES_PATH,
        "NPC Relationship Persistence Golden Cases",
    )
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise NpcRelationshipPersistenceError(
            "NPC Relationship Persistence Golden Cases require exactly 8 cases."
        )
    case_id = f"case_{case_number}"
    matches = [case for case in cases if case.get("id") == case_id]
    if len(matches) != 1:
        raise NpcRelationshipPersistenceError(
            f"Unknown NPC Relationship case: {case_number}"
        )
    persistence_case = matches[0]
    c1_document = load_json(
        C1_RELATIONSHIP_CASES_PATH,
        "Frozen C1 Relationship Golden Cases",
    )
    c1_cases = c1_document.get("cases")
    if not isinstance(c1_cases, list) or len(c1_cases) != 8:
        raise NpcRelationshipPersistenceError(
            "Frozen C1 Relationship Golden Cases require exactly 8 cases."
        )
    interaction_case_id = f"case_{persistence_case['interaction_case']}"
    event_matches = [
        case for case in c1_cases if case.get("id") == interaction_case_id
    ]
    if len(event_matches) != 1:
        raise NpcRelationshipPersistenceError(
            f"Unknown Frozen C1 Relationship case: {interaction_case_id}"
        )
    resolved_case = copy.deepcopy(persistence_case)
    resolved_case["interaction_event"] = copy.deepcopy(
        event_matches[0]["interaction_event"]
    )
    return resolved_case


def load_runtime_interaction_event(path: Path) -> dict[str, Any]:
    event = load_json(path.resolve(), "Runtime NPC Interaction Event")
    try:
        validate_interaction_event(event)
    except NpcInteractionEventError as exc:
        raise NpcRelationshipPersistenceError(
            f"Runtime Interaction Event is invalid: {exc}"
        ) from exc
    return event


def load_event_source(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.case is not None:
        case = load_relationship_case(args.case)
        event = case["interaction_event"]
        validate_interaction_event(event)
        return "golden_fixture", event
    if args.event_file is not None:
        return "runtime_event", load_runtime_interaction_event(args.event_file)
    raise NpcRelationshipPersistenceError(
        "Exactly one Relationship source mode is required."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Relationship Change Preview from one validated Interaction "
            "Event and commit only after explicit confirmation. No LLM is called."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--case",
        type=int,
        choices=range(1, 9),
        metavar="N",
        help="NPC Relationship Golden Case number (1-8).",
    )
    source.add_argument(
        "--event-file",
        type=Path,
        help="Validated Runtime NPC Interaction Event JSON file.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=RELATIONSHIP_STORE_PATH,
        help="Relationship Store path; defaults to data/saves/npc_relationships.json.",
    )
    return parser.parse_args()


def run_relationship_command(
    interaction_event: dict[str, Any],
    source_mode: str,
    store_path: Path,
) -> int:
    store_before = file_hash(store_path)
    print(f"Source mode: {source_mode}")
    preview = build_persistent_relationship_preview(
        interaction_event,
        store_path,
    )
    print("Relationship Change Preview:")
    print(json.dumps(preview, ensure_ascii=False, indent=2))

    if preview["decision"] == "no_change":
        if file_hash(store_path) != store_before:
            raise RelationshipStoreError(
                "Relationship Store changed for a no_change Preview."
            )
        print("No persistent relationship change required.")
        return 0

    committed = confirm_and_commit_relationship(
        interaction_event,
        preview,
        store_path,
    )
    if committed is None:
        if file_hash(store_path) != store_before:
            raise RelationshipStoreError(
                "Relationship Store changed after cancellation."
            )
        print("Relationship commit cancelled. Store was not modified.")
        return 0

    record, committed_preview = committed
    print("NPC relationship committed.")
    print(f"NPC: {record['npc_id']}")
    print(f"Player: {record['player_id']}")
    print(f"Familiarity: {record['familiarity']}")
    print(f"Trust: {record['trust']}")
    print(f"Attitude: {record['attitude']}")
    print(f"Source Event: {committed_preview['source_event_id']}")
    print(f"Persistent relationship store: {store_path}")
    return 0


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    store_path = args.store.resolve()
    protected_paths = (SEED_PATH, SAVE_PATH, MEMORY_STORE_PATH, PROFILES_PATH)
    protected_before = {path: file_hash(path) for path in protected_paths}
    try:
        source_mode, interaction_event = load_event_source(args)
        exit_code = run_relationship_command(
            interaction_event,
            source_mode,
            store_path,
        )
    except DuplicateRelationshipEventError as exc:
        print(str(exc))
        exit_code = 0
    except NoRelationshipChangeRequiredError as exc:
        print(str(exc))
        exit_code = 0
    except (
        NpcInteractionEventError,
        NpcRelationshipPersistenceError,
        RelationshipStoreError,
    ) as exc:
        print(f"NPC Relationship operation failed: {exc}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        print("\nCancelled. No relationship was committed.", file=sys.stderr)
        exit_code = 130

    changed = [
        path
        for path, digest in protected_before.items()
        if file_hash(path) != digest
    ]
    if changed:
        print(
            "Safety error: protected state changed: "
            + ", ".join(str(path) for path in changed),
            file=sys.stderr,
        )
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
