"""D3-B: deterministic Dragon encounter decisions without world mutation."""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.free_action_interpreter import validate_action_interpretation
from core.free_action_resolution import (
    load_world_skeleton,
    validate_resolution_result,
)
from database.persistence import PostgresPersistenceAdapter


OUTCOMES = {"none", "trace", "sighting", "direct_encounter"}
PRIMARY_ELIGIBLE_FAMILIES = {"explore", "observe_search"}
CONDITIONAL_ELIGIBLE_FAMILIES = {"travel", "interact", "other"}
DIRECT_ENCOUNTER_EXCLUDED_STATES = {"avoiding", "flying"}
RECENT_HISTORY_LIMIT = 3
HIGH_LEVEL_ENCOUNTER_OUTCOMES = {"sighting", "direct_encounter"}

_DRAGON_TERMS = (
    "龙",
    "dragon",
    "wyrm",
)
_TRACE_TERMS = (
    "龙巢",
    "巢穴",
    "巢痕",
    "巨大脚印",
    "脚印",
    "鳞片",
    "抓痕",
    "烧焦",
    "踪迹",
    "痕迹",
    "nest",
    "footprint",
    "scale",
    "claw mark",
    "track",
    "scorch",
)
_GENERIC_DRAGON_TARGETS = {
    "龙",
    "一条龙",
    "那条龙",
    "附近的龙",
    "dragon",
    "adragon",
    "thedragon",
}


class EncounterDecisionError(RuntimeError):
    """Encounter inputs or outputs violate the D3-B contract."""


def validate_encounter_decision(result: Mapping[str, Any]) -> None:
    """Validate the minimal D3-B decision contract."""

    required = {
        "outcome",
        "is_final",
        "requires_new_dragon",
        "dragon_id",
        "reason_code",
        "context_score",
        "roll",
    }
    if set(result) != required:
        raise EncounterDecisionError("Encounter Decision fields are invalid.")
    if result["outcome"] not in OUTCOMES:
        raise EncounterDecisionError("Encounter Decision outcome is invalid.")
    if not isinstance(result["is_final"], bool):
        raise EncounterDecisionError("Encounter Decision is_final is invalid.")
    if not isinstance(result["requires_new_dragon"], bool):
        raise EncounterDecisionError(
            "Encounter Decision requires_new_dragon is invalid."
        )
    if result["dragon_id"] is not None and not isinstance(
        result["dragon_id"], str
    ):
        raise EncounterDecisionError("Encounter Decision dragon_id is invalid.")
    if not isinstance(result["reason_code"], str) or not result[
        "reason_code"
    ]:
        raise EncounterDecisionError("Encounter Decision reason_code is invalid.")
    if isinstance(result["context_score"], bool) or not isinstance(
        result["context_score"], int
    ):
        raise EncounterDecisionError("Encounter Decision context_score is invalid.")
    if isinstance(result["roll"], bool) or not isinstance(
        result["roll"], (int, float)
    ):
        raise EncounterDecisionError("Encounter Decision roll is invalid.")
    if not 0.0 <= float(result["roll"]) <= 1.0:
        raise EncounterDecisionError("Encounter Decision roll is outside 0..1.")

    outcome = result["outcome"]
    if outcome in {"none", "trace"}:
        if (
            not result["is_final"]
            or result["requires_new_dragon"]
            or result["dragon_id"] is not None
        ):
            raise EncounterDecisionError(
                "none/trace must be final and must not reference a Dragon."
            )
    elif result["is_final"]:
        if result["requires_new_dragon"] or result["dragon_id"] is None:
            raise EncounterDecisionError(
                "A final sighting/direct encounter requires a committed Dragon."
            )
    elif (
        not result["requires_new_dragon"] or result["dragon_id"] is not None
    ):
        raise EncounterDecisionError(
            "A provisional sighting/direct encounter must request a new Dragon."
        )


def _decision(
    outcome: str,
    *,
    is_final: bool,
    requires_new_dragon: bool,
    dragon_id: str | None,
    reason_code: str,
    context_score: int,
    roll: float,
) -> dict[str, Any]:
    result = {
        "outcome": outcome,
        "is_final": is_final,
        "requires_new_dragon": requires_new_dragon,
        "dragon_id": dragon_id,
        "reason_code": reason_code,
        "context_score": context_score,
        "roll": roll,
    }
    validate_encounter_decision(result)
    return result


def _none(reason_code: str) -> dict[str, Any]:
    return _decision(
        "none",
        is_final=True,
        requires_new_dragon=False,
        dragon_id=None,
        reason_code=reason_code,
        context_score=0,
        roll=0.0,
    )


def _action_text(structured_action: Mapping[str, Any]) -> str:
    return " ".join(
        str(structured_action.get(field) or "")
        for field in (
            "action",
            "target",
            "destination",
            "direction",
            "intent",
            "method",
        )
    ).casefold()


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    return any(term.casefold() in text for term in terms)


def _is_eligible(
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
) -> tuple[bool, str]:
    if resolution["status"] == "blocked":
        return False, "d2_action_blocked"
    if resolution["status"] == "needs_clarification":
        return False, "d2_action_needs_clarification"
    if structured_action["explicit_goal"] is not None:
        return False, "explicit_goal_not_encounter_action"

    family = structured_action["action_family"]
    if family in PRIMARY_ELIGIBLE_FAMILIES:
        return True, "eligible_primary_action"
    if family in CONDITIONAL_ELIGIBLE_FAMILIES and _contains_any(
        _action_text(structured_action), _DRAGON_TERMS + _TRACE_TERMS
    ):
        return True, "eligible_dragon_intent"
    return False, "action_not_eligible"


def _location_score(location: Mapping[str, Any]) -> int:
    location_type = location.get("type")
    if location_type in {"forest", "wild_area"}:
        return 2
    if location_type == "ruins":
        return 1
    return 0


def _history_decision(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("event_payload")
    if not isinstance(payload, Mapping):
        return {}
    for key in ("encounter_decision", "decision"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            return nested
    return payload


def _recent_history_penalty(recent_history: Sequence[Mapping[str, Any]]) -> int:
    """Penalize only committed high-level encounters, never none/trace."""

    high_level_count = sum(
        1
        for event in recent_history
        if _history_decision(event).get("outcome")
        in HIGH_LEVEL_ENCOUNTER_OUTCOMES
    )
    return 2 * min(high_level_count, RECENT_HISTORY_LIMIT)


def _context_score(
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
    location: Mapping[str, Any],
    existing_dragons: Sequence[Mapping[str, Any]],
    recent_history: Sequence[Mapping[str, Any]],
) -> int:
    family = structured_action["action_family"]
    score = 3 if family == "observe_search" else 2 if family == "explore" else 1
    action_text = _action_text(structured_action)
    if _contains_any(action_text, _DRAGON_TERMS):
        score += 2
    if _contains_any(action_text, _TRACE_TERMS):
        score += 1
    score += _location_score(location)
    if existing_dragons:
        score += 1
    if resolution["status"] == "success":
        score += 1
    score -= _recent_history_penalty(recent_history)
    return max(score, 0)


def _outcome_for(score: int, roll: float) -> str:
    signal = score + (roll * 4.0)
    if signal < 4.0:
        return "none"
    if signal < 10.0:
        return "trace"
    if signal < 12.0:
        return "sighting"
    return "direct_encounter"


def _normalized(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def _is_specific_dragon_target(target: str) -> bool:
    normalized_target = _normalized(target)
    return (
        bool(normalized_target)
        and normalized_target not in _GENERIC_DRAGON_TARGETS
        and not _contains_any(target.casefold(), _TRACE_TERMS)
    )


def _eligible_existing_dragons(
    existing_dragons: Sequence[Mapping[str, Any]],
    outcome: str,
) -> list[Mapping[str, Any]]:
    eligible: list[Mapping[str, Any]] = []
    for dragon in existing_dragons:
        dragon_id = dragon.get("dragon_id")
        if not isinstance(dragon_id, str) or not dragon_id:
            raise EncounterDecisionError("Existing Dragon has no stable dragon_id.")
        if outcome == "direct_encounter" and dragon.get(
            "behavior_state"
        ) in DIRECT_ENCOUNTER_EXCLUDED_STATES:
            continue
        eligible.append(dragon)
    return eligible


def _select_existing_dragon(
    structured_action: Mapping[str, Any],
    existing_dragons: Sequence[Mapping[str, Any]],
    recent_history: Sequence[Mapping[str, Any]],
    outcome: str,
) -> Mapping[str, Any] | None:
    eligible = _eligible_existing_dragons(existing_dragons, outcome)
    if not eligible:
        return None

    target = structured_action.get("target")
    if isinstance(target, str) and target.strip():
        wanted = _normalized(target)
        targeted = [
            dragon
            for dragon in eligible
            if wanted
            in {
                _normalized(str(dragon["dragon_id"])),
                _normalized(str(dragon.get("name") or "")),
            }
        ]
        if len(targeted) == 1:
            return targeted[0]
        if _is_specific_dragon_target(target):
            return None

    eligible_by_id = {str(dragon["dragon_id"]): dragon for dragon in eligible}
    for event in recent_history:
        recent_dragon_id = _history_decision(event).get("dragon_id")
        if isinstance(recent_dragon_id, str) and recent_dragon_id in eligible_by_id:
            return eligible_by_id[recent_dragon_id]

    return min(eligible, key=lambda dragon: str(dragon["dragon_id"]))


def decide_dragon_encounter(
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
    *,
    current_location: str,
    locations: Mapping[str, Any],
    existing_dragons: Sequence[Mapping[str, Any]] = (),
    recent_history: Sequence[Mapping[str, Any]] = (),
    roll: float | None = None,
    random_source: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Return one D3-B decision over already grounded D2 and world inputs."""

    validate_action_interpretation(structured_action)
    validate_resolution_result(resolution)
    location = locations.get(current_location)
    if not isinstance(location, Mapping):
        raise EncounterDecisionError("Current authored Location is not grounded.")
    eligible, eligibility_reason = _is_eligible(structured_action, resolution)
    if not eligible:
        return _none(eligibility_reason)

    score = _context_score(
        structured_action,
        resolution,
        location,
        existing_dragons,
        recent_history,
    )
    if roll is not None and random_source is not None:
        raise EncounterDecisionError("Inject either roll or random_source, not both.")
    actual_roll = float(roll if roll is not None else (random_source or random.random)())
    if not 0.0 <= actual_roll <= 1.0:
        raise EncounterDecisionError("Injected encounter roll must be within 0..1.")
    outcome = _outcome_for(score, actual_roll)

    if outcome == "none":
        return _decision(
            outcome,
            is_final=True,
            requires_new_dragon=False,
            dragon_id=None,
            reason_code="context_no_encounter",
            context_score=score,
            roll=actual_roll,
        )
    if outcome == "trace":
        return _decision(
            outcome,
            is_final=True,
            requires_new_dragon=False,
            dragon_id=None,
            reason_code="dragon_trace",
            context_score=score,
            roll=actual_roll,
        )

    selected = _select_existing_dragon(
        structured_action,
        existing_dragons,
        recent_history,
        outcome,
    )
    if selected is not None:
        return _decision(
            outcome,
            is_final=True,
            requires_new_dragon=False,
            dragon_id=str(selected["dragon_id"]),
            reason_code=f"existing_dragon_{outcome}",
            context_score=score,
            roll=actual_roll,
        )
    return _decision(
        outcome,
        is_final=False,
        requires_new_dragon=True,
        dragon_id=None,
        reason_code=f"new_dragon_required_for_{outcome}",
        context_score=score,
        roll=actual_roll,
    )


def decide_current_dragon_encounter(
    *,
    player_id: str,
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
    persistence: PostgresPersistenceAdapter,
    world_skeleton: Mapping[str, Any] | None = None,
    roll: float | None = None,
    random_source: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Read current PostgreSQL truth and delegate to the pure D3-B decision."""

    player_state = persistence.get_player_state(player_id)
    if player_state is None:
        raise EncounterDecisionError(f"PlayerState does not exist: {player_id}")
    current_location = player_state.get("current_location")
    if not isinstance(current_location, str) or not current_location:
        raise EncounterDecisionError("Player current Location is invalid.")
    skeleton = dict(world_skeleton or load_world_skeleton())
    locations = skeleton.get("locations")
    if not isinstance(locations, Mapping):
        raise EncounterDecisionError("World skeleton has no Location registry.")

    existing_dragons = persistence.list_dragons_at_location(current_location)
    recent_history = persistence.list_recent_dragon_encounter_decisions(
        player_id,
        location_id=current_location,
        limit=RECENT_HISTORY_LIMIT,
    )
    return decide_dragon_encounter(
        structured_action,
        resolution,
        current_location=current_location,
        locations=locations,
        existing_dragons=existing_dragons,
        recent_history=recent_history,
        roll=roll,
        random_source=random_source,
    )
