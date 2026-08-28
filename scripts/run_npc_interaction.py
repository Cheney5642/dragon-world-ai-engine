"""Interactive CLI for Unified NPC Interaction Runtime v0.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from llm import LLMProviderError  # noqa: E402
from npc.interaction_runtime import (  # noqa: E402
    NpcInteractionRuntimeError,
    run_npc_interaction,
)
from npc.memory import MEMORY_STORE_PATH, MemoryStoreError  # noqa: E402
from npc.relationship_store import (  # noqa: E402
    RELATIONSHIP_STORE_PATH,
    RelationshipStoreError,
)
from npc.response_runtime import NpcResponseError  # noqa: E402
from scripts.inspect_npc_context import load_world_state  # noqa: E402


SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
PROTECTED_PATHS = (
    SEED_PATH,
    SAVE_PATH,
    PROFILES_PATH,
    MEMORY_STORE_PATH,
    RELATIONSHIP_STORE_PATH,
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


def read_player_utterance() -> str:
    print("What do you say? Submit an empty line to finish:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    utterance = "\n".join(lines).strip()
    if not utterance:
        raise NpcInteractionRuntimeError("Player utterance must not be empty.")
    return utterance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one read-only NPC Response + Interaction Event pipeline."
    )
    parser.add_argument("npc_id", help="NPC Entity ID, such as npc_astrid")
    parser.add_argument(
        "--player-id",
        default="player_001",
        help="Player Entity ID (default: player_001)",
    )
    return parser.parse_args()


def _print_result_sections(result: dict[str, object]) -> None:
    if result["interaction_available"] is False:
        print("\nInteraction Preconditions:")
        print("interaction_available = false")
        print(f"reason = {result['unavailable_reason']}")
        print("\nRuntime Result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    npc_context = result["npc_context"]
    assert isinstance(npc_context, dict)
    summary = {
        "npc_id": npc_context["npc"]["id"],
        "npc_name": npc_context["npc"]["name"],
        "player_id": npc_context["player"]["id"],
        "same_location": npc_context["shared_context"]["same_location"],
        "location": npc_context["runtime_state"]["current_location"],
    }
    print("\nNPC Context Summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nMemory Recall Context:")
    print(json.dumps(result["memory_recall_context"], ensure_ascii=False, indent=2))
    print("\nRelationship Context:")
    print(json.dumps(result["relationship_context"], ensure_ascii=False, indent=2))
    print("\nNPC Response:")
    print(json.dumps(result["npc_response"], ensure_ascii=False, indent=2))
    print("\nInteraction Event:")
    print(json.dumps(result["interaction_event"], ensure_ascii=False, indent=2))
    print("\nRuntime Result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    configure_console_encoding()
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    hashes_before = {path: file_hash(path) for path in PROTECTED_PATHS}

    try:
        world_state = load_world_state()
        utterance = read_player_utterance()
        result = run_npc_interaction(
            args.npc_id,
            args.player_id,
            utterance,
            world_state,
        )
    except (
        LLMProviderError,
        MemoryStoreError,
        NpcInteractionRuntimeError,
        NpcResponseError,
        RelationshipStoreError,
    ) as exc:
        print(f"NPC Interaction failed: {exc}", file=sys.stderr)
        return 1

    hashes_after = {path: file_hash(path) for path in PROTECTED_PATHS}
    if hashes_after != hashes_before:
        print("Read-only safety check failed: protected state changed.", file=sys.stderr)
        return 1

    _print_result_sections(result)
    print("\nRead-only hash check: PASS")
    print("No Memory, Relationship, Profile, or World State was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
