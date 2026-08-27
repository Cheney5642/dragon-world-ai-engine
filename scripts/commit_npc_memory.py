"""Preview and explicitly commit one Persistent NPC Memory without an LLM."""

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

from npc.context_builder import NpcContextError, build_npc_context  # noqa: E402
from npc.interaction_event import (  # noqa: E402
    NpcInteractionEventError,
    build_interaction_event,
    validate_interaction_event,
)
from npc.memory import (  # noqa: E402
    MEMORY_STORE_PATH,
    DuplicateMemoryError,
    MemoryStoreError,
    NoPersistentMemoryRequiredError,
    NpcMemoryError,
    build_memory_preview,
    confirm_and_commit_memory,
)


SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
INTERACTION_CASES_PATH = (
    PROJECT_ROOT / "data" / "npc_interaction_event_test_cases.json"
)
MEMORY_CASES_PATH = PROJECT_ROOT / "data" / "npc_memory_test_cases.json"


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise NpcMemoryError(f"{label} does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcMemoryError(f"{label} is not valid readable JSON: {path}") from exc
    if not isinstance(document, dict):
        raise NpcMemoryError(f"{label} must contain a JSON object: {path}")
    return document


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_memory_case(case_number: int) -> dict[str, Any]:
    document = load_json(MEMORY_CASES_PATH, "NPC Memory Golden Cases")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise NpcMemoryError("NPC Memory Golden Cases must contain a cases array.")
    case_id = f"case_{case_number}"
    matches = [case for case in cases if case.get("id") == case_id]
    if len(matches) != 1:
        raise NpcMemoryError(f"Unknown NPC Memory case: {case_number}")
    return matches[0]


def load_runtime_interaction_event(event_path: Path) -> dict[str, Any]:
    """Load and validate a Runtime Event; never accept a Memory JSON as input."""

    event = load_json(event_path.resolve(), "Runtime NPC Interaction Event")
    try:
        validate_interaction_event(event)
    except NpcInteractionEventError as exc:
        raise NpcMemoryError(f"Runtime Interaction Event is invalid: {exc}") from exc
    return event


def build_case_interaction_event(memory_case: dict[str, Any]) -> dict[str, Any]:
    """Build one validated frozen Interaction Event fixture entirely offline."""

    interaction_document = load_json(
        INTERACTION_CASES_PATH,
        "NPC Interaction Event Golden Cases",
    )
    interaction_cases = interaction_document.get("cases")
    if not isinstance(interaction_cases, list):
        raise NpcMemoryError(
            "NPC Interaction Event Golden Cases must contain a cases array."
        )
    interaction_case_id = f"case_{memory_case['interaction_case']}"
    matches = [
        case for case in interaction_cases if case.get("id") == interaction_case_id
    ]
    if len(matches) != 1:
        raise NpcMemoryError(
            f"Unknown Interaction Event fixture: {interaction_case_id}"
        )

    interaction_case = matches[0]
    world_state = load_json(SEED_PATH, "World Seed")
    world_state = copy.deepcopy(world_state)
    world_state["player"]["name"] = "Eirik"
    context = build_npc_context(interaction_case["npc_id"], world_state)
    event = build_interaction_event(
        context,
        interaction_case["player_utterance"],
        copy.deepcopy(interaction_case["npc_response"]),
    )
    event["event_id"] = memory_case["source_event_id"]
    for field, value in memory_case.get("event_overrides", {}).items():
        event[field] = copy.deepcopy(value)
    validate_interaction_event(event)
    return event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Memory Preview from an offline Interaction Event fixture, "
            "then commit only after explicit confirmation. No LLM is called."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--case",
        type=int,
        choices=range(1, 9),
        metavar="N",
        help="NPC Memory Golden Case number (1-8).",
    )
    source.add_argument(
        "--event-file",
        type=Path,
        help="Validated Runtime NPC Interaction Event JSON file.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=MEMORY_STORE_PATH,
        help="Memory Store path; defaults to data/saves/npc_memories.json.",
    )
    return parser.parse_args()


def load_event_source(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.case is not None:
        memory_case = load_memory_case(args.case)
        return "golden_fixture", build_case_interaction_event(memory_case)
    if args.event_file is not None:
        return "runtime_event", load_runtime_interaction_event(args.event_file)
    raise NpcMemoryError("Exactly one Memory source mode is required.")


def run_memory_command(
    interaction_event: dict[str, Any],
    source_mode: str,
    store_path: Path,
) -> int:
    """Run Preview/Confirm/Commit while allowing only the Memory Store to change."""

    store_before = file_hash(store_path)
    print(f"Source mode: {source_mode}")
    try:
        memory = build_memory_preview(interaction_event)
    except NoPersistentMemoryRequiredError:
        if file_hash(store_path) != store_before:
            raise MemoryStoreError(
                "Memory Store changed for a non-candidate Interaction Event."
            )
        print("No persistent memory required.")
        return 0

    print("NPC Memory Preview:")
    print(json.dumps(memory, ensure_ascii=False, indent=2))
    committed = confirm_and_commit_memory(memory, store_path)
    if committed is None:
        if file_hash(store_path) != store_before:
            raise MemoryStoreError("Memory Store changed after cancellation.")
        print("Memory commit cancelled. Store was not modified.")
        return 0

    print("NPC memory committed.")
    print(f"Memory ID: {committed['memory_id']}")
    print(f"NPC: {committed['npc_id']}")
    print(f"Source Event: {committed['source_event_id']}")
    print(f"Persistent memory store: {store_path}")
    return 0


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    store_path = args.store.resolve()
    protected_paths = (SEED_PATH, SAVE_PATH, PROFILES_PATH)
    protected_before = {path: file_hash(path) for path in protected_paths}

    try:
        source_mode, interaction_event = load_event_source(args)
        exit_code = run_memory_command(
            interaction_event,
            source_mode,
            store_path,
        )
    except DuplicateMemoryError as exc:
        print(str(exc))
        exit_code = 0
    except (
        MemoryStoreError,
        NpcMemoryError,
        NpcContextError,
        NpcInteractionEventError,
    ) as exc:
        print(f"NPC Memory operation failed: {exc}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        print("\nCancelled. No memory was committed.", file=sys.stderr)
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
