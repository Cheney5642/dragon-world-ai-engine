"""Read-only CLI for inspecting a resolved Generic NPC Context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from npc.context_builder import NpcContextError, build_npc_context  # noqa: E402


SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"


def configure_console_encoding() -> None:
    """Keep Chinese JSON output readable in Windows terminals."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def load_world_state(path: Path = SAVE_PATH) -> dict[str, Any]:
    if not path.exists():
        raise NpcContextError(
            "No current Dragon World save found. Run python scripts/init_save.py first."
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcContextError("The current Dragon World save is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise NpcContextError("The current Dragon World save must be a JSON object.")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect one deterministic, read-only NPC Context."
    )
    parser.add_argument("npc_id", help="Anchor NPC Entity ID, such as npc_astrid")
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    try:
        world_state = load_world_state()
        context = build_npc_context(args.npc_id, world_state)
    except NpcContextError as exc:
        print(f"NPC Context could not be built: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(context, ensure_ascii=False, indent=2))
    print("\nRead-only inspection complete. No World State was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
