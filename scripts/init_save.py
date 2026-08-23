"""Initialize the current persistent world save from the immutable seed."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_DIRECTORY = PROJECT_ROOT / "data" / "saves"
SAVE_PATH = SAVE_DIRECTORY / "current_world.json"
REQUIRED_WORLD_SECTIONS = {
    "world",
    "player",
    "locations",
    "npcs",
    "global_state",
}


class SaveInitializationError(Exception):
    """A readable error raised while initializing a save."""


def configure_console_encoding() -> None:
    """Keep user-facing output readable in Windows terminals."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def load_and_validate_world(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise SaveInitializationError(f"{label} file does not exist: {path}")
    if not path.is_file():
        raise SaveInitializationError(f"{label} path is not a file: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            world_state = json.load(file)
    except PermissionError as exc:
        raise SaveInitializationError(f"Cannot read {label} file: {path}") from exc
    except OSError as exc:
        raise SaveInitializationError(
            f"Could not read {label} file: {path} ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SaveInitializationError(
            f"{label} is not valid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {path}"
        ) from exc

    if not isinstance(world_state, dict):
        raise SaveInitializationError(f"{label} must contain a JSON object: {path}")

    missing_sections = sorted(REQUIRED_WORLD_SECTIONS - world_state.keys())
    if missing_sections:
        raise SaveInitializationError(
            f"{label} is missing required section(s): "
            + ", ".join(missing_sections)
        )
    return world_state


def initialize_save(reset: bool = False) -> None:
    """Create or reset only current_world.json from the validated seed."""

    # Seed is deliberately opened only for validation and copying. Runtime
    # state must never be written back to world_seed.json.
    load_and_validate_world(SEED_PATH, "World seed")

    if SAVE_PATH.exists() and not reset:
        print("Current save already exists. Use --reset to create a new world.")
        return

    try:
        SAVE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SEED_PATH, SAVE_PATH)
    except PermissionError as exc:
        raise SaveInitializationError(f"Cannot write save file: {SAVE_PATH}") from exc
    except OSError as exc:
        raise SaveInitializationError(
            f"Could not create save file: {SAVE_PATH} ({exc})"
        ) from exc

    load_and_validate_world(SAVE_PATH, "Current save")

    if reset:
        print("Dragon World save reset from world seed.")
    else:
        print("New Dragon World save created.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the current Dragon World save from world_seed.json."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="replace current_world.json with a fresh copy of the world seed",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    try:
        initialize_save(reset=args.reset)
        return 0
    except SaveInitializationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. The world seed was not modified.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
