"""Read-only CLI for inspecting one NPC's Persistent Memories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.memory import MEMORY_STORE_PATH, MemoryStoreError, load_memory_store  # noqa: E402


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read persisted memories for one NPC without calling an LLM."
    )
    parser.add_argument("npc_id", help="NPC Entity ID, for example npc_astrid.")
    parser.add_argument(
        "--store",
        type=Path,
        default=MEMORY_STORE_PATH,
        help="Memory Store path; defaults to data/saves/npc_memories.json.",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    try:
        store = load_memory_store(args.store.resolve())
    except MemoryStoreError as exc:
        print(f"Could not inspect NPC memories: {exc}", file=sys.stderr)
        return 1

    memories = [
        memory for memory in store["memories"] if memory["npc_id"] == args.npc_id
    ]
    print(f"NPC: {args.npc_id}")
    print(f"Persistent memories: {len(memories)}")
    print(json.dumps(memories, ensure_ascii=False, indent=2))
    print("Read-only inspection complete. No LLM was called and no Store was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
