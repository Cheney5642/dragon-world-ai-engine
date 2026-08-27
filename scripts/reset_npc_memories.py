"""Explicit, atomic development reset for the independent NPC Memory Store."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.memory import (  # noqa: E402
    MEMORY_STORE_PATH,
    MemoryStoreError,
    load_memory_store,
    write_memory_store_atomically,
)


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


def reset_memory_store(
    store_path: Path,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    """Reset only a validated Memory Store after explicit confirmation."""

    if not confirmed:
        raise MemoryStoreError("Reset requires --confirm. No Store was modified.")
    load_memory_store(store_path)
    empty_store = {"version": "0.1", "memories": []}
    write_memory_store_atomically(empty_store, store_path)
    return load_memory_store(store_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically reset only the development NPC Memory Store. "
            "This does not modify World State or NPC Profiles."
        )
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="explicitly authorize deletion of all persisted NPC Memories",
    )
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
    store_path = args.store.resolve()
    protected_paths = (SEED_PATH, SAVE_PATH, PROFILES_PATH)
    protected_before = {path: file_hash(path) for path in protected_paths}
    try:
        before_count = len(load_memory_store(store_path)["memories"])
        reset_store = reset_memory_store(store_path, confirmed=args.confirm)
        print("NPC Memory Store reset.")
        print(f"Removed memories: {before_count}")
        print(f"Persistent memory store: {store_path}")
        print(f"Current memories: {len(reset_store['memories'])}")
        exit_code = 0
    except MemoryStoreError as exc:
        print(f"NPC Memory reset failed: {exc}", file=sys.stderr)
        exit_code = 1

    changed = [
        path
        for path, digest in protected_before.items()
        if file_hash(path) != digest
    ]
    if changed:
        print(
            "Safety error: reset changed protected state: "
            + ", ".join(str(path) for path in changed),
            file=sys.stderr,
        )
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
