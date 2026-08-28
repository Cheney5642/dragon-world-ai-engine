"""Explicit, atomic development reset for the NPC Relationship Store."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.relationship_store import (  # noqa: E402
    RELATIONSHIP_STORE_PATH,
    RelationshipStoreError,
    load_relationship_store,
    write_relationship_store_atomically,
)


SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
MEMORY_STORE_PATH = PROJECT_ROOT / "data" / "saves" / "npc_memories.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reset_relationship_store(
    store_path: Path,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise RelationshipStoreError("Reset requires --confirm. No Store was modified.")
    load_relationship_store(store_path)
    empty_store = {"version": "0.1", "relationships": []}
    write_relationship_store_atomically(empty_store, store_path)
    return load_relationship_store(store_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically reset only the development NPC Relationship Store. "
            "This does not modify World State, Memory, or NPC Profiles."
        )
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="explicitly authorize deletion of all persisted NPC Relationships",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=RELATIONSHIP_STORE_PATH,
        help="Relationship Store path; defaults to data/saves/npc_relationships.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store_path = args.store.resolve()
    protected_paths = (SEED_PATH, SAVE_PATH, MEMORY_STORE_PATH, PROFILES_PATH)
    protected_before = {path: file_hash(path) for path in protected_paths}
    try:
        before_count = len(load_relationship_store(store_path)["relationships"])
        reset_store = reset_relationship_store(
            store_path,
            confirmed=args.confirm,
        )
        print("NPC Relationship Store reset.")
        print(f"Removed relationships: {before_count}")
        print(f"Persistent relationship store: {store_path}")
        print(f"Current relationships: {len(reset_store['relationships'])}")
        exit_code = 0
    except RelationshipStoreError as exc:
        print(f"NPC Relationship reset failed: {exc}", file=sys.stderr)
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
