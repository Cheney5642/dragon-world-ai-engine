"""Deterministic D2-C action resolution over the Frozen D2-B contract."""

from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from time import perf_counter
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from core.display_names import location_aliases, npc_aliases
from core.food_ecology import (
    FOODS,
    available_food,
    explicit_food_candidate,
    food_action_kind,
)
from core.free_action_interpreter import validate_action_interpretation
from database.persistence import PostgresPersistenceAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORLD_SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
logger = logging.getLogger(__name__)
OUTCOMES = {"success", "partial", "blocked", "needs_clarification"}
EFFECT_SCOPES = {"narrative_only", "player_state", "domain_route"}
INVENTORY_SLOT_LIMIT = 12
INVENTORY_STACK_LIMIT = 20

_PICKUP_MARKERS = (
    "捡", "拾", "拿起", "收起", "放进背包", "装进背包",
    "pick up", "pickup", "collect", "put in my bag",
)
_NON_PORTABLE_ITEM_MARKERS = (
    "龙", "dragon", "npc", "人", "村民", "房", "屋", "建筑",
    "山", "悬崖", "树", "船", "遗迹", "尸体", "活物",
)


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


def load_runtime_world_skeleton(
    persistence: PostgresPersistenceAdapter,
    path: Path = WORLD_SEED_PATH,
) -> dict[str, Any]:
    """Overlay persisted Dynamic Locations onto the authored world skeleton."""

    from core.location_discovery import merge_location_registries

    skeleton = load_world_skeleton(path)
    skeleton["locations"] = merge_location_registries(
        skeleton["locations"],
        persistence.get_dynamic_location_registry(),
    )
    return skeleton


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
        {"current_location", "goals", "inventory"}
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
        names = location_aliases(location_id, location.get("name"))
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
        identifiers = {npc_key, *npc_aliases(npc_id, npc_name)}
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


def _pickup_text(action: Mapping[str, Any]) -> str:
    return " ".join(
        str(action.get(field) or "")
        for field in ("action", "target", "intent", "method")
    ).strip().casefold()


def _portable_item_name(
    action: Mapping[str, Any],
    npcs: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Return a grounded carryable display name or a rejection reason."""

    text = _pickup_text(action)
    if not any(marker in text for marker in _PICKUP_MARKERS):
        return None, None
    target = action.get("target")
    if not isinstance(target, str) or not target.strip():
        return None, "item_target_missing"
    name = target.strip()
    normalized = _normalized(name)
    if len(name) > 40 or len(normalized) < 1:
        return None, "item_target_invalid"
    if any(marker in normalized for marker in _NON_PORTABLE_ITEM_MARKERS):
        return None, "item_not_portable"
    if isinstance(npcs, Mapping):
        for npc in npcs.values():
            if not isinstance(npc, Mapping):
                continue
            identifiers = {str(npc.get("id") or ""), str(npc.get("name") or "")}
            if normalized in {_normalized(value) for value in identifiers if value}:
                return None, "item_not_portable"

    name = re.sub(r"^(?:一|1)(?:块|枚|根|片|颗|个|只|本|支|把|件)", "", name).strip()
    return (name or target.strip()), None


def _add_inventory_item(
    inventory: list[Any],
    *,
    item_name: str,
    food_kind: str | None = None,
) -> tuple[list[Any] | None, str | None]:
    """Add one item to the bounded JSON inventory without inventing properties."""

    updated = copy.deepcopy(inventory)
    wanted = _normalized(item_name)
    for index, entry in enumerate(updated):
        if isinstance(entry, str):
            entry_name = entry
            quantity = 1
        elif isinstance(entry, Mapping):
            entry_name = str(entry.get("name") or entry.get("id") or "")
            quantity = entry.get("quantity", 1)
        else:
            continue
        if _normalized(entry_name) != wanted:
            continue
        if (entry.get("category") if isinstance(entry, Mapping) else None) != (
            "food" if food_kind else None
        ):
            continue
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            return None, "inventory_invalid"
        if quantity >= INVENTORY_STACK_LIMIT:
            return None, "inventory_stack_limit_reached"
        if isinstance(entry, str):
            updated[index] = {
                "id": f"carried_{uuid.uuid5(uuid.NAMESPACE_URL, wanted).hex[:12]}",
                "name": item_name,
                "quantity": 2,
            }
        else:
            updated[index] = {**dict(entry), "quantity": quantity + 1}
        return updated, None
    if len(updated) >= INVENTORY_SLOT_LIMIT:
        return None, "inventory_full"
    new_item = {
        "id": f"carried_{uuid.uuid5(uuid.NAMESPACE_URL, wanted).hex[:12]}",
        "name": item_name,
        "quantity": 1,
    }
    if food_kind is not None:
        new_item.update({
            "item_id": new_item["id"],
            "category": "food",
            "food_kind": food_kind,
        })
    updated.append(new_item)
    return updated, None


def resolve_action(
    structured_action: Mapping[str, Any],
    player_state: Mapping[str, Any],
    locations: Mapping[str, Any],
    *,
    has_rideable_dragon: bool,
    npcs: Mapping[str, Any] | None = None,
    food_candidate: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve one Structured Action without writing any state."""

    validate_action_interpretation(structured_action)
    current_location = player_state.get("current_location")
    goals = player_state.get("goals")
    inventory = player_state.get("inventory")
    if not isinstance(current_location, str) or current_location not in locations:
        raise ActionResolutionError("Player current Location is not grounded.")
    if not isinstance(goals, list) or not all(isinstance(goal, str) for goal in goals):
        raise ActionResolutionError("Player goals are invalid.")
    if not isinstance(inventory, list):
        raise ActionResolutionError("Player inventory is invalid.")

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

    food_kind_action = food_action_kind(structured_action) if family != "travel" else None
    if food_kind_action is not None:
        location = locations[current_location]
        allowed = available_food(food_kind_action, current_location, location)
        if not allowed:
            return _result(
                "blocked", "narrative_only",
                "food_hunting_unavailable" if food_kind_action == "hunt" else "food_market_unavailable",
            )
        candidate = food_candidate or explicit_food_candidate(
            structured_action,
            location_id=current_location,
            location=location,
        )
        chosen = candidate.get("food_kind") if isinstance(candidate, Mapping) else None
        if chosen not in allowed or candidate.get("name") != FOODS[chosen][0]:
            return _result("blocked", "narrative_only", "food_target_not_grounded")
        updated_inventory, inventory_error = _add_inventory_item(
            inventory,
            item_name=FOODS[chosen][0],
            food_kind=chosen,
        )
        if inventory_error is not None:
            return _result("blocked", "narrative_only", inventory_error)
        assert updated_inventory is not None
        return _result(
            "success", "player_state",
            "food_hunted" if food_kind_action == "hunt" else "food_bought",
            state_changes={"inventory": updated_inventory},
        )

    if family == "use_acquire":
        item_name, rejection = _portable_item_name(structured_action, npcs)
        if rejection is not None:
            return _result("blocked", "narrative_only", rejection)
        if item_name is not None:
            updated_inventory, inventory_error = _add_inventory_item(
                inventory,
                item_name=item_name,
            )
            if inventory_error is not None:
                return _result("blocked", "narrative_only", inventory_error)
            assert updated_inventory is not None
            return _result(
                "success",
                "player_state",
                "item_acquired",
                state_changes={"inventory": updated_inventory},
            )

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
    skeleton = dict(
        world_skeleton
        if world_skeleton is not None
        else load_runtime_world_skeleton(persistence)
    )
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
    food_candidate: Mapping[str, str] | None = None,
    latency_trace_id: str | None = None,
) -> dict[str, Any]:
    """Re-resolve then atomically commit the allowlisted effect and event."""

    if not isinstance(player_input, str) or not player_input.strip():
        raise ActionResolutionError("player_input must be non-empty.")
    resolution_started = perf_counter()
    try:
        player_state = persistence.get_player_state(player_id)
        if player_state is None:
            raise ActionResolutionError(f"PlayerState does not exist: {player_id}")
        skeleton = dict(
            world_skeleton
            if world_skeleton is not None
            else load_runtime_world_skeleton(persistence)
        )
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
            food_candidate=food_candidate,
        )
    finally:
        if latency_trace_id is not None:
            logger.warning(
                "[LATENCY] trace=%s phase=resolution duration_ms=%.1f",
                latency_trace_id, (perf_counter() - resolution_started) * 1000,
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
            **({"food_candidate": dict(food_candidate)} if food_candidate else {}),
        },
    }
    commit_started = perf_counter()
    try:
        committed = persistence.commit_free_action(
            player_id=player_id,
            expected_current_location=player_state["current_location"],
            expected_goals=player_state["goals"],
            expected_inventory=player_state["inventory"],
            state_changes=resolution["state_changes"],
            event=event,
        )
    finally:
        if latency_trace_id is not None:
            logger.warning(
                "[LATENCY] trace=%s phase=db duration_ms=%.1f",
                latency_trace_id, (perf_counter() - commit_started) * 1000,
            )
    return {
        "resolution": resolution,
        "player_state": committed["player_state"],
        "interaction_event": committed["interaction_event"],
    }
