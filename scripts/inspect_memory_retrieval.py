"""Read-only CLI for inspecting deterministic NPC Memory Retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.memory import MEMORY_STORE_PATH, MemoryStoreError  # noqa: E402
from npc.context_builder import NpcContextError, build_npc_context  # noqa: E402
from npc.memory_retriever import (  # noqa: E402
    MAX_RETRIEVAL_LIMIT,
    NpcMemoryRetrievalError,
    retrieve_relevant_memories,
)
from npc.response_runtime_v0_2 import world_context_from_npc_context  # noqa: E402
from scripts.inspect_npc_context import load_world_state  # noqa: E402


SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
PROTECTED_PATHS = (SEED_PATH, SAVE_PATH, PROFILES_PATH, MEMORY_STORE_PATH)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect deterministic, read-only NPC Memory Recall Context."
    )
    parser.add_argument("npc_id", help="NPC Entity ID, such as npc_astrid")
    parser.add_argument("player_utterance", help="Current player utterance")
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_RETRIEVAL_LIMIT,
        help="Maximum recalled memories (1-3, default: 3)",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    hashes_before = {path: file_hash(path) for path in PROTECTED_PATHS}

    try:
        world_state = load_world_state()
        npc_context = build_npc_context(args.npc_id, world_state)
        recall_context = retrieve_relevant_memories(
            args.npc_id,
            npc_context["player"]["id"],
            args.player_utterance,
            world_context_from_npc_context(npc_context),
            args.limit,
        )
    except (
        MemoryStoreError,
        NpcContextError,
        NpcMemoryRetrievalError,
    ) as exc:
        print(f"Memory Retrieval failed: {exc}", file=sys.stderr)
        return 1

    hashes_after = {path: file_hash(path) for path in PROTECTED_PATHS}
    if hashes_after != hashes_before:
        print("Read-only safety check failed: protected state changed.", file=sys.stderr)
        return 1

    print("Player utterance:")
    print(args.player_utterance)
    print("\nMemory Recall Context:")
    print(json.dumps(recall_context, ensure_ascii=False, indent=2))
    print("\nRead-only hash check: PASS")
    print("No Memory Store or World State was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
