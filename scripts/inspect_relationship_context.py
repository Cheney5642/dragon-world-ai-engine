"""Read-only CLI for inspecting the Relationship Context used by v0.3."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.relationship_context import (  # noqa: E402
    NpcRelationshipContextError,
    build_relationship_context,
)
from npc.relationship_store import RELATIONSHIP_STORE_PATH  # noqa: E402


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
        description="Inspect one read-only NPC Relationship Context."
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
        help="Relationship Store path.",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    store_path = args.store.resolve()
    before = file_hash(store_path)
    try:
        context = build_relationship_context(
            args.npc_id,
            args.player_id,
            store_path=store_path,
        )
    except NpcRelationshipContextError as exc:
        print(f"Could not inspect Relationship Context: {exc}", file=sys.stderr)
        return 1

    if file_hash(store_path) != before:
        print("Read-only safety check failed: Relationship Store changed.", file=sys.stderr)
        return 1

    source = "persistent" if context["relationship_exists"] else "default"
    print(f"NPC: {args.npc_id}")
    print(f"Player: {args.player_id}")
    print(f"Relationship Source: {source}")
    print("Relationship Context:")
    print(json.dumps(context, ensure_ascii=False, indent=2))
    print("Read-only hash check: PASS")
    print("No Relationship record was created or modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
