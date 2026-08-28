"""Read-only CLI for inspecting one Persistent NPC Relationship."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.relationship_store import (  # noqa: E402
    RELATIONSHIP_STORE_PATH,
    RelationshipStoreError,
    load_relationship_store,
    resolve_current_relationship,
)
from npc.relationship import NpcRelationshipError  # noqa: E402


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect one NPC/Player Relationship without writing State."
    )
    parser.add_argument("npc_id", help="NPC Entity ID, for example npc_astrid")
    parser.add_argument(
        "--player-id",
        default="player_001",
        help="Player Entity ID (default: player_001)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=RELATIONSHIP_STORE_PATH,
        help="Relationship Store path; defaults to data/saves/npc_relationships.json.",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    try:
        store = load_relationship_store(args.store.resolve())
        relationship, persisted = resolve_current_relationship(
            store,
            args.npc_id,
            args.player_id,
        )
    except (NpcRelationshipError, RelationshipStoreError) as exc:
        print(f"Could not inspect NPC relationship: {exc}", file=sys.stderr)
        return 1

    record = next(
        (
            copy.deepcopy(item)
            for item in store["relationships"]
            if item["npc_id"] == args.npc_id
            and item["player_id"] == args.player_id
        ),
        None,
    )
    print(f"NPC: {args.npc_id}")
    print(f"Player: {args.player_id}")
    print(f"Persistent record exists: {'yes' if persisted else 'no'}")
    print("Current Relationship:")
    print(json.dumps(relationship, ensure_ascii=False, indent=2))
    if record is not None:
        print("Persistence Audit:")
        print(
            json.dumps(
                {
                    "applied_event_ids": record["applied_event_ids"],
                    "last_source_event_id": record["last_source_event_id"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("Default relationship is read-only and has not been written to Store.")
    print("Read-only inspection complete. No LLM was called and no Store was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
