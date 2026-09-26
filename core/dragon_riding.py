"""D6 Dragon Riding domain routing over grounded PostgreSQL truth."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.display_names import dragon_aliases
from core.free_action_resolution import (
    _is_location_reachable,
    _resolve_destination,
    load_runtime_world_skeleton,
)
from database.persistence import PostgresPersistenceAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHETYPE_PATH = PROJECT_ROOT / "data" / "dragon_archetypes.json"

RidingOperation = str

_DISMOUNT_MARKERS = (
    "下龙",
    "背上下来",
    "身上下来",
    "我下来",
    "降落",
    "dismount",
    "get off",
    "land here",
)
_RIDE_MARKERS = (
    "骑",
    "爬上",
    "背上",
    "带我",
    "ride",
    "riding",
    "mount",
)


class DragonRidingError(RuntimeError):
    """A Riding action cannot be safely mapped to formal world truth."""


def _action_text(structured_action: Mapping[str, Any]) -> str:
    return " ".join(
        str(structured_action.get(field) or "").strip().casefold()
        for field in ("action", "target", "destination", "intent", "method")
    )


def classify_riding_operation(
    structured_action: Mapping[str, Any],
) -> RidingOperation | None:
    """Recognize only the small D6 mount/travel/dismount intent surface."""

    text = _action_text(structured_action)
    if any(marker in text for marker in _DISMOUNT_MARKERS):
        return "dismount"
    if structured_action.get("action_family") in {
        "rest_wait",
        "observe_search",
        "explore",
    }:
        return None
    if not any(marker in text for marker in _RIDE_MARKERS):
        return None
    destination = structured_action.get("destination")
    if isinstance(destination, str) and destination.strip():
        return "mounted_travel"
    return "mount"


def _load_rideable_archetypes(path: Path = ARCHETYPE_PATH) -> set[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        archetypes = value["archetypes"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DragonRidingError("Dragon Archetype registry is unavailable.") from exc
    if not isinstance(archetypes, Mapping):
        raise DragonRidingError("Dragon Archetype registry is invalid.")
    rideable_physical_tendencies = {"medium_balanced", "large_powerful"}
    return {
        str(archetype_id)
        for archetype_id, archetype in archetypes.items()
        if isinstance(archetype, Mapping)
        and isinstance(archetype.get("physical_tendencies"), list)
        and bool(
            set(archetype["physical_tendencies"])
            & rideable_physical_tendencies
        )
    }


def _blocked_result(
    *,
    operation: str,
    reason_code: str,
    persistence: PostgresPersistenceAdapter,
    player_id: str,
    dragon: Mapping[str, Any] | None = None,
    destination_id: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "operation": operation,
        "reason_code": reason_code,
        "dragon_id": dragon.get("dragon_id") if dragon else None,
        "dragon_name": dragon.get("name") if dragon else None,
        "destination_id": destination_id,
        "riding_unlocked": False,
        "mounted_dragon_id": persistence.get_player_riding_state(player_id)[
            "mounted_dragon_id"
        ],
        "dragon_event_id": None,
    }


def _resolve_dragon(
    *,
    player_id: str,
    operation: RidingOperation,
    structured_action: Mapping[str, Any],
    persistence: PostgresPersistenceAdapter,
) -> dict[str, Any] | None:
    riding = persistence.get_player_riding_state(player_id)
    mounted_id = riding["mounted_dragon_id"]
    if operation in {"dismount", "mounted_travel"} and mounted_id is not None:
        mounted = persistence.get_dragon(mounted_id, player_id=player_id)
        target = structured_action.get("target")
        if isinstance(target, str) and target.strip() and mounted is not None:
            if target.strip().casefold() not in {
                alias.casefold()
                for alias in dragon_aliases(
                    mounted.get("dragon_id"), mounted.get("name")
                )
            }:
                return None
        return mounted

    player_state = persistence.get_player_state(player_id)
    if player_state is None:
        raise DragonRidingError(f"PlayerState does not exist: {player_id}")
    nearby = persistence.list_dragons_at_location(
        player_state["current_location"], player_id=player_id
    )
    target = structured_action.get("target")
    wanted = target.strip().casefold() if isinstance(target, str) else ""
    matches = [
        dragon
        for dragon in nearby
        if wanted
        and wanted
        in {
            alias.casefold()
            for alias in dragon_aliases(
                dragon.get("dragon_id"), dragon.get("name")
            )
        }
    ]
    if len(matches) == 1:
        return matches[0]
    action_text = _action_text(structured_action)
    named = []
    for dragon in nearby:
        aliases = dragon_aliases(dragon.get("dragon_id"), dragon.get("name"))
        if any(
            re.search(
                rf"(?<![a-z0-9]){re.escape(alias.casefold())}(?![a-z0-9])",
                action_text,
            )
            for alias in aliases
        ):
            named.append(dragon)
    if not wanted and len(named) == 1:
        return named[0]
    if not wanted and len(nearby) == 1 and (
        "龙" in action_text or "dragon" in action_text
    ):
        return nearby[0]
    return None


def route_grounded_riding_before_d2(
    *,
    player_id: str,
    structured_action: Mapping[str, Any],
    persistence: PostgresPersistenceAdapter,
) -> dict[str, Any]:
    """Keep a named Dragon ride out of D2's ordinary walking branch.

    D2 recognizes an explicit dragon noun. For a grounded proper name such as
    Kael, add the equivalent domain hint to the structured method before D2
    commits. A non-Dragon ride remains untouched.
    """

    result = dict(structured_action)
    operation = classify_riding_operation(result)
    if operation is None:
        return result
    if _resolve_dragon(
        player_id=player_id,
        operation=operation,
        structured_action=result,
        persistence=persistence,
    ) is None:
        return result
    if operation != "mounted_travel":
        return result
    method = result.get("method")
    result["method"] = f"{method or ''} 骑龙".strip()
    return result


def commit_riding_action(
    *,
    player_id: str,
    source_interaction_event_id: str,
    structured_action: Mapping[str, Any],
    persistence: PostgresPersistenceAdapter,
) -> dict[str, Any] | None:
    """Ground and atomically commit one D6 operation, or return no D6 route."""

    operation = classify_riding_operation(structured_action)
    if operation is None:
        return None
    dragon = _resolve_dragon(
        player_id=player_id,
        operation=operation,
        structured_action=structured_action,
        persistence=persistence,
    )
    if dragon is None:
        action_text = _action_text(structured_action)
        if "龙" not in action_text and "dragon" not in action_text:
            return None
        return _blocked_result(
            operation=operation,
            reason_code="riding_dragon_not_grounded",
            persistence=persistence,
            player_id=player_id,
        )

    skeleton = load_runtime_world_skeleton(persistence)
    locations = skeleton["locations"]
    destination_id: str | None = None
    if operation == "mounted_travel":
        destination = structured_action.get("destination")
        if not isinstance(destination, str):
            raise DragonRidingError("Mounted travel requires a destination.")
        destination_id = _resolve_destination(destination, locations)
        player_state = persistence.get_player_state(player_id)
        if player_state is None:
            raise DragonRidingError(f"PlayerState does not exist: {player_id}")
        if destination_id is None:
            return _blocked_result(
                operation=operation,
                reason_code="riding_destination_not_grounded",
                persistence=persistence,
                player_id=player_id,
                dragon=dragon,
            )
        if not _is_location_reachable(
            player_state["current_location"], destination_id, locations
        ):
            return _blocked_result(
                operation=operation,
                reason_code="riding_destination_unreachable",
                persistence=persistence,
                player_id=player_id,
                dragon=dragon,
                destination_id=destination_id,
            )

    result = persistence.commit_dragon_riding(
        player_id=player_id,
        dragon_id=dragon["dragon_id"],
        source_interaction_event_id=source_interaction_event_id,
        operation=operation,
        destination_id=destination_id,
        known_location_ids=set(locations),
        rideable_archetype_ids=_load_rideable_archetypes(),
    )
    return {**result, "dragon_name": dragon["name"]}
