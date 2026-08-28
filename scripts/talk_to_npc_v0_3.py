"""Interactive, read-only CLI for Relationship-aware NPC Response v0.3."""

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

from llm import LLMProviderError, create_llm_client  # noqa: E402
from npc.context_builder import NpcContextError  # noqa: E402
from npc.memory import MEMORY_STORE_PATH, MemoryStoreError  # noqa: E402
from npc.memory_retriever import MAX_RETRIEVAL_LIMIT  # noqa: E402
from npc.relationship_context import NpcRelationshipContextError  # noqa: E402
from npc.relationship_store import (  # noqa: E402
    RELATIONSHIP_STORE_PATH,
    RelationshipStoreError,
)
from npc.response_runtime import (  # noqa: E402
    NpcInteractionUnavailableError,
    NpcResponseError,
    load_response_schema,
)
from npc.response_runtime_v0_3 import (  # noqa: E402
    load_relationship_response_prompt,
    prepare_relationship_aware_context,
    request_relationship_aware_response,
    validate_relationship_aware_response,
)
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
        raise NpcResponseError("Player utterance must not be empty.")
    return utterance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview one Relationship-aware, read-only NPC response."
    )
    parser.add_argument("npc_id", help="NPC Entity ID, such as npc_astrid")
    parser.add_argument(
        "--player-id",
        default="player_001",
        help="Player Entity ID (default: player_001)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_RETRIEVAL_LIMIT,
        help="Maximum recalled memories (1-3, default: 3)",
    )
    parser.add_argument(
        "--default-relationship-fixture",
        action="store_true",
        help=(
            "Use an in-memory empty Store so the frozen Default Relationship "
            "can be compared without modifying Persistent State."
        ),
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    hashes_before = {path: file_hash(path) for path in PROTECTED_PATHS}

    try:
        world_state = load_world_state()
        utterance = read_player_utterance()
        npc_context, recall_context, relationship_context = (
            prepare_relationship_aware_context(
                args.npc_id,
                utterance,
                world_state,
                args.player_id,
                limit=args.limit,
                relationship_store_document=(
                    {"version": "0.1", "relationships": []}
                    if args.default_relationship_fixture
                    else None
                ),
            )
        )
        provider = create_llm_client()
        response_schema = load_response_schema()
        response = request_relationship_aware_response(
            provider,
            npc_context,
            recall_context,
            relationship_context,
            utterance,
            load_relationship_response_prompt(),
            response_schema,
        )
        validate_relationship_aware_response(
            response,
            response_schema,
            npc_context,
            recall_context,
            relationship_context,
        )
    except NpcInteractionUnavailableError as exc:
        print(f"NPC interaction unavailable: {exc}", file=sys.stderr)
        return 1
    except (
        LLMProviderError,
        MemoryStoreError,
        NpcContextError,
        NpcRelationshipContextError,
        NpcResponseError,
        RelationshipStoreError,
    ) as exc:
        print(f"NPC Response failed: {exc}", file=sys.stderr)
        return 1

    hashes_after = {path: file_hash(path) for path in PROTECTED_PATHS}
    if hashes_after != hashes_before:
        print("Read-only safety check failed: protected state changed.", file=sys.stderr)
        return 1

    source = (
        "persistent" if relationship_context["relationship_exists"] else "default"
    )
    print(f"\nRelationship Source: {source}")
    print("Relationship Context:")
    print(json.dumps(relationship_context, ensure_ascii=False, indent=2))
    print("\nMemory Recall Context:")
    print(json.dumps(recall_context, ensure_ascii=False, indent=2))
    print("\nNPC Response Preview:")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    print("\nRead-only hash check: PASS")
    print("No Relationship, Memory, Profile, or World State was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
