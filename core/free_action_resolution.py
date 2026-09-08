"""Deterministic D2-C action resolution over the Frozen D2-B contract."""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from core.free_action_interpreter import validate_action_interpretation
from database.persistence import PostgresPersistenceAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORLD_SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
OUTCOMES = {"success", "partial", "blocked", "needs_clarification"}
EFFECT_SCOPES = {"narrative_only", "player_state", "domain_route"}


class ActionResolutionError(RuntimeError):
    """Resolution input or persistent preconditions are invalid."""


def load_world_skeleton(path: Path = WORLD_SEED_PATH) -> dict[str, Any]:
    """Load the existing authored Location registry and world clock."""

    try:
        world = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ActionResolutionError("World skeleton could not be loaded.") from exc
    if not isinstance(world, dict) or not isinstance(world.get("locations"), dict):
        raise ActionResolutionError("World skeleton has no Location registry.")
    clock = world.get("world")
    if not isinstance(clock, dict):
        raise ActionResolutionError("World skeleton has no world clock.")
    return world


def validate_resolution_result(result: Mapping[str, Any]) -> None:
    required = {
        "status",
        "effect_scope",
        "reason_code",
        "domain_route",
        "state_changes",
    }
    if set(result) != required:
        raise ActionResolutionError("Action Resolution Result fields are invalid.")
    if result["status"] not in OUTCOMES:
        raise ActionResolutionError("Action Resolution status is invalid.")
    if result["effect_scope"] not in EFFECT_SCOPES:
        raise ActionResolutionError("Action Resolution effect_scope is invalid.")
    if result["reason_code"] is not None and not isinstance(
        result["reason_code"], str
    ):
        raise ActionResolutionError("Action Resolution reason_code is invalid.")
    if result["domain_route"] not in {None, "npc", "dragon"}:
        raise ActionResolutionError("Action Resolution domain_route is invalid.")
    changes = result["state_changes"]
    if not isinstance(changes, dict) or not set(changes).issubset(
        {"current_location", "goals"}
    ):
        raise ActionResolutionError("Action Resolution state_changes are invalid.")
    if result["effect_scope"] == "player_state" and not changes:
        raise ActionResolutionError("player_state resolution requires a change.")
    if result["effect_scope"] != "player_state" and changes:
        raise ActionResolutionError("Only player_state may contain state changes.")
    if result["effect_scope"] == "domain_route" and result["domain_route"] is None:
        raise ActionResolutionError("domain_route effect requires a route.")


def _result(
    status: str,
    effect_scope: str,
    reason_code: str | None = None,
    *,
    domain_route: str | None = None,
    state_changes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "effect_scope": effect_scope,
        "reason_code": reason_code,
        "domain_route": domain_route,
        "state_changes": copy.deepcopy(dict(state_changes or {})),
    }
    validate_resolution_result(result)
    return result


def _normalized(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def _resolve_destination(
    destination: str,
    locations: Mapping[str, Any],
) -> str | None:
    wanted = _normalized(destination)
    matches: list[str] = []
    for location_id, location in locations.items():
        if not isinstance(location, Mapping):
            raise ActionResolutionError("World skeleton contains an invalid Location.")
        names = {str(location_id), str(location.get("name") or "")}
        if wanted in {_normalized(name) for name in names if name}:
            matches.append(str(location_id))
    return matches[0] if len(matches) == 1 else None


def _resolve_npc_target(
    target: str | None,
    npcs: Mapping[str, Any],
) -> str | None:
    """Resolve one authored NPC by exact stable id or display name."""

    if not isinstance(target, str) or not target.strip():
        return None
    wanted = _normalized(target)
    matches: list[str] = []
    for npc_key, npc in npcs.items():
        if not isinstance(npc_key, str) or not isinstance(npc, Mapping):
            return None
        npc_id = npc.get("id")
        npc_name = npc.get("name")
        if not isinstance(npc_id, str) or not isinstance(npc_name, str):
            return None
        identifiers = {npc_key, npc_id, npc_name}
        if wanted in {_normalized(identifier) for identifier in identifiers}:
            matches.append(npc_id)
    return matches[0] if len(matches) == 1 else None


def _is_location_reachable(
    current_location: str,
    destination_id: str,
    locations: Mapping[str, Any],
) -> bool:
    """Follow only authored directed connections; fail closed on invalid edges."""

    if current_location not in locations or destination_id not in locations:
        return False

    graph: dict[str, tuple[str, ...]] = {}
    for location_id, location in locations.items():
        if not isinstance(location_id, str) or not isinstance(location, Mapping):
            return False
        connections = location.get("connections")
        if not isinstance(connections, list) or not all(
            isinstance(connection, str) and connection in locations
            for connection in connections
        ):
            return False
        graph[location_id] = tuple(connections)

    visited = {current_location}
    pending = deque([current_location])
    while pending:
        location_id = pending.popleft()
        for connected_id in graph[location_id]:
            if connected_id == destination_id:
                return True
            if connected_id not in visited:
                visited.add(connected_id)
                pending.append(connected_id)
    return False


def _goal_key(goal: str) -> str:
    value = _normalized(goal)
    replacements = (
        ("我的目标是", ""),
        ("不想再", ""),
        ("找到一枚", "找"),
        ("寻找一枚", "找"),
        ("寻找", "找"),
        ("找到", "找"),
        ("searchfor", "find"),
        ("lookfor", "find"),
        ("finda", "find"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    return value


def _dragon_riding_intent(action: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(action.get(field) or "")
        for field in ("action", "target", "intent", "method")
    ).casefold()
    return ("龙" in text or "dragon" in text) and (
        "骑" in text or "ride" in text or "riding" in text
    )


def resolve_action(
    structured_action: Mapping[str, Any],
    player_state: Mapping[str, Any],
    locations: Mapping[str, Any],
    *,
    has_rideable_dragon: bool,
    npcs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one Structured Action without writing any state."""

    validate_action_interpretation(structured_action)
    current_location = player_state.get("current_location")
    goals = player_state.get("goals")
    if not isinstance(current_location, str) or current_location not in locations:
        raise ActionResolutionError("Player current Location is not grounded.")
    if not isinstance(goals, list) or not all(isinstance(goal, str) for goal in goals):
        raise ActionResolutionError("Player goals are invalid.")

    if structured_action["needs_clarification"]:
        return _result(
            "needs_clarification", "narrative_only", "language_ambiguous"
        )

    if _dragon_riding_intent(structured_action):
        if not has_rideable_dragon:
            return _result(
                "blocked", "domain_route", "dragon_riding_not_grounded",
                domain_route="dragon",
            )
        return _result(
            "partial", "domain_route", "dragon_runtime_required",
            domain_route="dragon",
        )

    family = structured_action["action_family"]
    explicit_goal = structured_action["explicit_goal"]
    if explicit_goal is not None:
        goal = explicit_goal["goal"].strip()
        goal_key = _goal_key(goal)
        matching = [index for index, item in enumerate(goals) if _goal_key(item) == goal_key]
        if explicit_goal["operation"] == "add":
            if matching:
                return _result("success", "narrative_only", "goal_already_present")
            if len(goals) >= 5:
                return _result("blocked", "narrative_only", "goal_limit_reached")
            return _result(
                "success", "player_state", "goal_added",
                state_changes={"goals": [*goals, goal]},
            )
        if not matching:
            return _result("success", "narrative_only", "goal_not_present")
        updated = [item for index, item in enumerate(goals) if index not in matching]
        return _result(
            "success", "player_state", "goal_removed",
            state_changes={"goals": updated},
        )

    if family == "travel":
        destination = structured_action["destination"]
        if destination is None:
            return _result("blocked", "narrative_only", "destination_missing")
        destination_id = _resolve_destination(destination, locations)
        if destination_id is None:
            return _result("blocked", "narrative_only", "destination_not_grounded")
        if destination_id == current_location:
            return _result("success", "narrative_only", "already_at_destination")
        if not _is_location_reachable(
            current_location,
            destination_id,
            locations,
        ):
            return _result("blocked", "narrative_only", "destination_unreachable")
        return _result(
            "success", "player_state", "known_travel",
            state_changes={"current_location": destination_id},
        )

    if family == "explore":
        return _result("success", "narrative_only", "open_exploration_recorded")

    known_npc_target = (
        _resolve_npc_target(structured_action.get("target"), npcs)
        if isinstance(npcs, Mapping)
        else None
    )
    if family == "interact" and known_npc_target is not None:
        return _result(
            "partial", "domain_route", "npc_runtime_required",
            domain_route="npc",
        )

    if family == "conflict":
        if known_npc_target is not None:
            return _result(
                "partial", "domain_route", "npc_runtime_required",
                domain_route="npc",
            )
        return _result("partial", "narrative_only", "conflict_runtime_unavailable")

    return _result("success", "narrative_only", "narrative_only")


def resolve_current_action(
    *,
    player_id: str,
    structured_action: Mapping[str, Any],
    persistence: PostgresPersistenceAdapter,
    world_skeleton: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only resolution against current PostgreSQL truth."""

    player_state = persistence.get_player_state(player_id)
    if player_state is None:
        raise ActionResolutionError(f"PlayerState does not exist: {player_id}")
    skeleton = dict(world_skeleton or load_world_skeleton())
    locations = skeleton.get("locations")
    npcs = skeleton.get("npcs", {})
    if not isinstance(locations, Mapping) or not isinstance(npcs, Mapping):
        raise ActionResolutionError("World skeleton registry is invalid.")
    return resolve_action(
        structured_action,
        player_state,
        locations,
        has_rideable_dragon=persistence.has_rideable_dragon(player_id),
        npcs=npcs,
    )


def commit_action_resolution(
    *,
    player_id: str,
    player_input: str,
    structured_action: Mapping[str, Any],
    persistence: PostgresPersistenceAdapter,
    world_skeleton: Mapping[str, Any] | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Re-resolve then atomically commit the allowlisted effect and event."""

    if not isinstance(player_input, str) or not player_input.strip():
        raise ActionResolutionError("player_input must be non-empty.")
    player_state = persistence.get_player_state(player_id)
    if player_state is None:
        raise ActionResolutionError(f"PlayerState does not exist: {player_id}")
    skeleton = dict(world_skeleton or load_world_skeleton())
    locations = skeleton.get("locations")
    npcs = skeleton.get("npcs", {})
    clock = skeleton.get("world")
    if (
        not isinstance(locations, Mapping)
        or not isinstance(npcs, Mapping)
        or not isinstance(clock, Mapping)
    ):
        raise ActionResolutionError("World skeleton is invalid.")
    resolution = resolve_action(
        structured_action,
        player_state,
        locations,
        has_rideable_dragon=persistence.has_rideable_dragon(player_id),
        npcs=npcs,
    )
    event = {
        "event_id": event_id or f"interaction_event_{uuid.uuid4().hex}",
        "event_type": "free_world_action",
        "player_id": player_id,
        "world_context": {
            "world_day": clock["day"],
            "world_hour": clock["hour"],
            "location_id": player_state["current_location"],
        },
        "player_utterance": player_input.strip(),
        "player_claims": [],
        "event_payload": {
            "structured_action": copy.deepcopy(dict(structured_action)),
            "resolution": copy.deepcopy(resolution),
            "world_effect": copy.deepcopy(resolution["state_changes"]),
        },
    }
    committed = persistence.commit_free_action(
        player_id=player_id,
        expected_current_location=player_state["current_location"],
        expected_goals=player_state["goals"],
        state_changes=resolution["state_changes"],
        event=event,
    )
    return {
        "resolution": resolution,
        "player_state": committed["player_state"],
        "interaction_event": committed["interaction_event"],
    }
