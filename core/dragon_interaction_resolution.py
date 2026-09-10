"""D4-B deterministic, read-only Dragon interaction resolution."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

from core.free_action_interpreter import (
    ActionInterpretationError,
    validate_action_interpretation,
)


INTERACTION_TYPES = {
    "observe",
    "approach",
    "wait",
    "retreat",
    "communicate",
    "offer_food",
    "touch",
    "threaten",
    "ride_attempt",
    "other",
}
DRAGON_REACTIONS = {
    "calm",
    "curious",
    "wary",
    "defensive",
    "accepting",
    "retreating",
}
RELATIONSHIP_EFFECTS = {"positive", "neutral", "negative"}
POSITIVE_CATEGORIES = {
    "food",
    "close_presence",
    "communication",
    "touch",
    "care_rescue",
    "shared_danger",
}
ANTI_FARMING_RESULTS = {
    "full",
    "familiarity_only",
    "zero",
    "not_applicable",
}
TAMING_STATES = {"wild", "tolerant", "bonding", "tamed"}
BEHAVIOR_STATES = {
    "resting",
    "feeding",
    "wandering",
    "watching",
    "avoiding",
    "threatening",
    "attacking",
    "following",
    "flying",
}
ARCHETYPE_IDS = {"agile_wild", "balanced_wild", "powerful_wild"}

BOND_BOUNDS = {
    "familiarity": (0, 5),
    "trust": (-3, 5),
    "fear": (0, 5),
    "bond": (0, 5),
}
ZERO_CHANGES = {
    "familiarity_delta": 0,
    "trust_delta": 0,
    "fear_delta": 0,
    "bond_delta": 0,
}
RANGE_REQUIRED_TYPES = INTERACTION_TYPES - {"other"}


class DragonInteractionResolutionError(Exception):
    """The supplied grounded snapshots cannot produce a safe D4-B resolution."""


def _normalized_text(action: Mapping[str, Any]) -> str:
    return " ".join(
        str(action.get(field) or "").strip().casefold()
        for field in ("action", "target", "intent", "method")
    )


def _contains_any(text: str, values: Sequence[str]) -> bool:
    return any(value in text for value in values)


def _interaction_type(action: Mapping[str, Any]) -> str:
    """Project already-interpreted D2 fields into one narrow D4 interaction type."""

    text = _normalized_text(action)
    family = action["action_family"]

    if _contains_any(text, ("骑", "ride", "mount")):
        return "ride_attempt"
    if family == "conflict" or _contains_any(
        text,
        ("威胁", "恐吓", "攻击", "杀", "挥剑", "threat", "attack", "kill"),
    ):
        return "threaten"
    if _contains_any(text, ("食物", "喂", "鱼", "肉", "food", "feed")) and (
        family in {"interact", "use_acquire", "other"}
        or _contains_any(text, ("放下", "递给", "给它", "offer", "leave"))
    ):
        return "offer_food"
    if _contains_any(text, ("触碰", "触摸", "摸", "抱", "touch", "pet", "hug")):
        return "touch"
    if _contains_any(text, ("后退", "退后", "拉开距离", "retreat", "step back")):
        return "retreat"
    if _contains_any(text, ("靠近", "接近", "走向", "approach", "move closer")):
        return "approach"
    communicates = _contains_any(
        text,
        ("说话", "交流", "交谈", "安抚", "speak", "talk", "soothe"),
    )
    explicitly_calm = _contains_any(
        text,
        ("平静", "轻声", "温和", "安抚", "calm", "softly", "gentle", "soothe"),
    )
    if family == "interact" and communicates and explicitly_calm:
        return "communicate"
    if family == "rest_wait" or _contains_any(
        text,
        ("等待", "等候", "停下来", "wait", "stay still"),
    ):
        return "wait"
    if family == "observe_search" or _contains_any(
        text,
        ("观察", "注视", "看看", "observe", "watch"),
    ):
        return "observe"
    return "other"


def _is_careful(action: Mapping[str, Any]) -> bool:
    return _contains_any(
        _normalized_text(action),
        ("慢慢", "缓慢", "小心", "轻声", "平静", "careful", "slow", "calm"),
    )


def _is_reckless(action: Mapping[str, Any]) -> bool:
    return _contains_any(
        _normalized_text(action),
        ("突然", "冲过去", "强行", "扑向", "reckless", "sudden", "rush", "force"),
    )


def _bond_snapshot(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "familiarity": 0,
            "trust": 0,
            "fear": 0,
            "bond": 0,
            "riding_unlocked": False,
        }
    result = {
        field: value.get(field)
        for field in (*BOND_BOUNDS, "riding_unlocked")
    }
    for field, (minimum, maximum) in BOND_BOUNDS.items():
        field_value = result[field]
        if (
            isinstance(field_value, bool)
            or not isinstance(field_value, int)
            or not minimum <= field_value <= maximum
        ):
            raise DragonInteractionResolutionError(
                f"Bond snapshot {field} is outside the existing Schema boundary."
            )
    if not isinstance(result["riding_unlocked"], bool):
        raise DragonInteractionResolutionError(
            "Bond snapshot riding_unlocked must be boolean."
        )
    return result


def _dragon_snapshot(
    dragon_id: str,
    dragon: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(dragon_id, str) or not dragon_id.strip():
        raise DragonInteractionResolutionError("dragon_id must be non-empty.")
    if dragon is None:
        return None
    result = copy.deepcopy(dict(dragon))
    if result.get("dragon_id") != dragon_id:
        raise DragonInteractionResolutionError(
            "Committed Dragon snapshot does not match dragon_id."
        )
    for field in ("archetype_id", "behavior_state", "taming_state", "current_location"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise DragonInteractionResolutionError(
                f"Committed Dragon snapshot has invalid {field}."
            )
    if result["archetype_id"] not in ARCHETYPE_IDS:
        raise DragonInteractionResolutionError("Dragon archetype is not authored.")
    if result["behavior_state"] not in BEHAVIOR_STATES:
        raise DragonInteractionResolutionError("Dragon behavior_state is invalid.")
    if result["taming_state"] not in TAMING_STATES:
        raise DragonInteractionResolutionError("Dragon taming_state is invalid.")
    return result


def _has_grounded_food(inventory: Sequence[Any]) -> bool:
    """Accept only an explicitly structured food resource; strings are not taxonomy."""

    for item in inventory:
        if not isinstance(item, Mapping):
            continue
        category = item.get("category", item.get("type"))
        quantity = item.get("quantity", 1)
        if (
            category == "food"
            and isinstance(quantity, Real)
            and not isinstance(quantity, bool)
            and quantity > 0
        ):
            return True
    return False


def _history_interaction_type(record: Mapping[str, Any]) -> str | None:
    direct = record.get("interaction_type")
    if isinstance(direct, str):
        return direct
    payload = record.get("event_payload")
    if not isinstance(payload, Mapping):
        return None
    resolution = payload.get("dragon_interaction_resolution")
    if not isinstance(resolution, Mapping):
        return None
    value = resolution.get("interaction_type")
    return value if isinstance(value, str) else None


def _history_matches_pair(
    record: Mapping[str, Any],
    *,
    player_id: str,
    dragon_id: str,
) -> bool:
    record_player_id = record.get("player_id")
    if record_player_id is not None and record_player_id != player_id:
        return False

    record_dragon_id = record.get("dragon_id")
    payload = record.get("event_payload")
    if isinstance(payload, Mapping):
        resolution = payload.get("dragon_interaction_resolution")
        if isinstance(resolution, Mapping):
            record_dragon_id = resolution.get("dragon_id", record_dragon_id)
    return record_dragon_id is None or record_dragon_id == dragon_id


def _anti_farming_result(
    interaction_type: str,
    relationship_effect: str,
    recent_history: Sequence[Mapping[str, Any]],
    *,
    player_id: str,
    dragon_id: str,
) -> str:
    if relationship_effect != "positive":
        return "not_applicable"
    repeats = 0
    for record in recent_history:
        if not _history_matches_pair(
            record,
            player_id=player_id,
            dragon_id=dragon_id,
        ):
            continue
        previous_type = _history_interaction_type(record)
        if previous_type is None:
            continue
        if previous_type != interaction_type:
            break
        repeats += 1
    if repeats == 0:
        return "full"
    if repeats == 1:
        return "familiarity_only"
    return "zero"


def _clamped_changes(
    bond: Mapping[str, Any],
    proposed: Mapping[str, int],
    anti_farming: str,
) -> dict[str, int]:
    effective = dict(proposed)
    if anti_farming == "familiarity_only":
        effective = {
            "familiarity": max(0, effective.get("familiarity", 0)),
            "trust": 0,
            "fear": 0,
            "bond": 0,
        }
    elif anti_farming == "zero":
        effective = {field: 0 for field in BOND_BOUNDS}

    result: dict[str, int] = {}
    for field, (minimum, maximum) in BOND_BOUNDS.items():
        raw_delta = effective.get(field, 0)
        if isinstance(raw_delta, bool) or not isinstance(raw_delta, int):
            raise DragonInteractionResolutionError(
                f"Proposed {field} delta must be an integer."
            )
        before = bond[field]
        after = min(maximum, max(minimum, before + raw_delta))
        result[f"{field}_delta"] = after - before
    return result


def _next_taming_preview(
    taming_state: str,
    bond: Mapping[str, Any],
    changes: Mapping[str, int],
    existing_categories: set[str],
    current_category: str | None,
    anti_farming: str,
) -> str | None:
    after = {
        field: bond[field] + changes[f"{field}_delta"]
        for field in BOND_BOUNDS
    }
    categories = set(existing_categories)
    if current_category is not None and anti_farming in {"full", "familiarity_only"}:
        categories.add(current_category)

    if (
        taming_state == "wild"
        and after["familiarity"] >= 2
        and after["trust"] >= 1
        and after["fear"] <= 2
        and len(categories) >= 1
    ):
        return "tolerant"
    if (
        taming_state == "tolerant"
        and after["familiarity"] >= 3
        and after["trust"] >= 2
        and after["bond"] >= 1
        and after["fear"] <= 1
        and len(categories) >= 2
    ):
        return "bonding"
    if (
        taming_state == "bonding"
        and after["familiarity"] >= 4
        and after["trust"] >= 3
        and after["bond"] >= 2
        and after["fear"] <= 1
        and len(categories) >= 3
    ):
        return "tamed"
    return None


def _result(
    *,
    source_interaction_event_id: str,
    dragon_id: str,
    status: str,
    interaction_type: str,
    dragon_reaction: str,
    relationship_effect: str,
    reason_code: str | None,
    changes: Mapping[str, int] | None = None,
    positive_category: str | None = None,
    anti_farming: str = "not_applicable",
    significant_event: str | None = None,
    next_taming_state_preview: str | None = None,
) -> dict[str, Any]:
    result = {
        "source_interaction_event_id": source_interaction_event_id,
        "dragon_id": dragon_id,
        "status": status,
        "interaction_type": interaction_type,
        "dragon_reaction": dragon_reaction,
        "relationship_effect": relationship_effect,
        "reason_code": reason_code,
        "state_changes": dict(changes or ZERO_CHANGES),
        "positive_category": positive_category,
        "anti_farming": anti_farming,
        "significant_event": significant_event,
        "next_taming_state_preview": next_taming_state_preview,
    }
    validate_dragon_interaction_resolution(result)
    return result


def validate_dragon_interaction_resolution(result: Any) -> None:
    expected = {
        "source_interaction_event_id",
        "dragon_id",
        "status",
        "interaction_type",
        "dragon_reaction",
        "relationship_effect",
        "reason_code",
        "state_changes",
        "positive_category",
        "anti_farming",
        "significant_event",
        "next_taming_state_preview",
    }
    if not isinstance(result, Mapping) or set(result) != expected:
        raise DragonInteractionResolutionError("D4-B Resolution shape is invalid.")
    if result["status"] not in {"success", "partial", "blocked", "needs_clarification"}:
        raise DragonInteractionResolutionError("D4-B status is invalid.")
    if result["interaction_type"] not in INTERACTION_TYPES:
        raise DragonInteractionResolutionError("D4-B interaction_type is invalid.")
    if result["dragon_reaction"] not in DRAGON_REACTIONS:
        raise DragonInteractionResolutionError("D4-B dragon_reaction is invalid.")
    if result["relationship_effect"] not in RELATIONSHIP_EFFECTS:
        raise DragonInteractionResolutionError("D4-B relationship_effect is invalid.")
    if result["positive_category"] not in POSITIVE_CATEGORIES | {None}:
        raise DragonInteractionResolutionError("D4-B positive_category is invalid.")
    if result["anti_farming"] not in ANTI_FARMING_RESULTS:
        raise DragonInteractionResolutionError("D4-B anti_farming is invalid.")
    if result["reason_code"] is not None and not isinstance(result["reason_code"], str):
        raise DragonInteractionResolutionError("D4-B reason_code is invalid.")
    if result["significant_event"] is not None and not isinstance(
        result["significant_event"], str
    ):
        raise DragonInteractionResolutionError("D4-B significant_event is invalid.")
    if result["next_taming_state_preview"] not in TAMING_STATES | {None}:
        raise DragonInteractionResolutionError(
            "D4-B next_taming_state_preview is invalid."
        )
    if not isinstance(result["source_interaction_event_id"], str) or not result[
        "source_interaction_event_id"
    ]:
        raise DragonInteractionResolutionError("D4-B source event is invalid.")
    if not isinstance(result["dragon_id"], str) or not result["dragon_id"]:
        raise DragonInteractionResolutionError("D4-B dragon_id is invalid.")
    changes = result["state_changes"]
    if not isinstance(changes, Mapping) or set(changes) != set(ZERO_CHANGES):
        raise DragonInteractionResolutionError("D4-B state_changes is invalid.")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in changes.values()):
        raise DragonInteractionResolutionError("D4-B deltas must be integers.")


def resolve_dragon_interaction(
    structured_action: Mapping[str, Any],
    *,
    source_interaction_event_id: str,
    player_id: str,
    dragon_id: str,
    dragon: Mapping[str, Any] | None,
    player_location: str,
    bond: Mapping[str, Any] | None = None,
    recent_history: Sequence[Mapping[str, Any]] = (),
    positive_categories: Sequence[str] = (),
    player_inventory: Sequence[Any] = (),
) -> dict[str, Any]:
    """Return a grounded proposed effect without reading or writing persistence."""

    if not isinstance(source_interaction_event_id, str) or not source_interaction_event_id:
        raise DragonInteractionResolutionError("source_interaction_event_id is required.")
    if not isinstance(player_id, str) or not player_id:
        raise DragonInteractionResolutionError("player_id is required.")
    if not isinstance(player_location, str) or not player_location:
        raise DragonInteractionResolutionError("player_location is required.")
    try:
        validate_action_interpretation(dict(structured_action))
    except ActionInterpretationError as exc:
        raise DragonInteractionResolutionError(
            "Structured Action does not satisfy the frozen D2 contract."
        ) from exc

    interaction_type = _interaction_type(structured_action)
    dragon_value = _dragon_snapshot(dragon_id, dragon)
    bond_value = _bond_snapshot(bond)
    category_set = set(positive_categories)
    if not category_set <= POSITIVE_CATEGORIES:
        raise DragonInteractionResolutionError("Positive category history is invalid.")

    if structured_action["needs_clarification"]:
        return _result(
            source_interaction_event_id=source_interaction_event_id,
            dragon_id=dragon_id,
            status="needs_clarification",
            interaction_type="other",
            dragon_reaction="wary",
            relationship_effect="neutral",
            reason_code="dragon_interaction_needs_clarification",
        )
    if dragon_value is None:
        return _result(
            source_interaction_event_id=source_interaction_event_id,
            dragon_id=dragon_id,
            status="blocked",
            interaction_type=interaction_type,
            dragon_reaction="wary",
            relationship_effect="neutral",
            reason_code="dragon_not_committed",
        )
    if (
        interaction_type in RANGE_REQUIRED_TYPES
        and dragon_value["current_location"] != player_location
    ):
        return _result(
            source_interaction_event_id=source_interaction_event_id,
            dragon_id=dragon_id,
            status="blocked",
            interaction_type=interaction_type,
            dragon_reaction="wary",
            relationship_effect="neutral",
            reason_code="dragon_not_in_interaction_range",
        )

    behavior = dragon_value["behavior_state"]
    taming = dragon_value["taming_state"]
    archetype = dragon_value["archetype_id"]
    proposed = {field: 0 for field in BOND_BOUNDS}
    status = "success"
    reaction = "wary"
    effect = "neutral"
    reason = "dragon_interaction_observed"
    category: str | None = None

    if interaction_type == "observe":
        reaction = "calm" if taming == "tamed" or behavior == "resting" else "wary"
        reason = "dragon_observed"
    elif interaction_type == "wait":
        reaction = "calm" if behavior not in {"threatening", "attacking"} else "wary"
        reason = "patient_wait"
    elif interaction_type == "retreat":
        reaction = "calm" if behavior != "attacking" else "retreating"
        effect = "positive"
        category = "close_presence"
        proposed.update(familiarity=1, trust=1, fear=-1)
        reason = "boundary_respected"
    elif interaction_type == "approach":
        reckless = _is_reckless(structured_action) or not _is_careful(structured_action)
        unsafe = behavior in {"threatening", "attacking", "avoiding"}
        archetype_sensitive = archetype == "agile_wild" and taming == "wild"
        if reckless and (unsafe or archetype_sensitive or archetype == "powerful_wild"):
            status = "blocked"
            reaction = "defensive"
            effect = "negative"
            proposed.update(trust=-1, fear=1, bond=-1)
            reason = "reckless_approach_rejected"
        else:
            status = "partial" if taming == "wild" else "success"
            reaction = "wary" if taming == "wild" else "curious"
            effect = "positive"
            category = "close_presence"
            proposed["familiarity"] = 1
            if taming != "wild" and not unsafe:
                proposed["trust"] = 1
            reason = "cautious_approach"
    elif interaction_type == "communicate":
        status = "partial" if taming == "wild" else "success"
        reaction = "wary" if taming == "wild" or behavior == "watching" else "curious"
        effect = "positive"
        category = "communication"
        proposed.update(familiarity=1, trust=1)
        reason = "calm_communication_acknowledged"
    elif interaction_type == "offer_food":
        if not _has_grounded_food(player_inventory):
            status = "blocked"
            reaction = "wary"
            reason = "offered_food_not_grounded"
        elif behavior in {"threatening", "attacking"}:
            status = "blocked"
            reaction = "defensive"
            reason = "dragon_rejects_food_while_hostile"
        else:
            reaction = "accepting"
            effect = "positive"
            category = "food"
            proposed.update(familiarity=1, trust=1, fear=-1)
            reason = "grounded_food_offer_accepted"
    elif interaction_type == "touch":
        safe_touch = (
            taming in {"tolerant", "bonding", "tamed"}
            and bond_value["trust"] >= 2
            and bond_value["fear"] <= 1
            and behavior not in {"avoiding", "threatening", "attacking", "flying"}
        )
        if not safe_touch:
            status = "blocked"
            reaction = "defensive"
            effect = "negative"
            proposed.update(trust=-1, fear=1, bond=-1)
            reason = "dragon_touch_not_grounded"
        else:
            reaction = "accepting"
            effect = "positive"
            category = "touch"
            proposed.update(familiarity=1, trust=1, bond=1)
            reason = "dragon_allows_touch_preview"
    elif interaction_type == "threaten":
        status = "partial"
        reaction = "retreating" if archetype == "agile_wild" else "defensive"
        effect = "negative"
        proposed.update(trust=-1, fear=1, bond=-1)
        reason = "dragon_reacts_defensively"
    elif interaction_type == "ride_attempt":
        status = "blocked"
        reaction = "defensive" if taming == "wild" else "wary"
        if taming != "tamed":
            reason = "dragon_not_tamed"
        elif not bond_value["riding_unlocked"]:
            reason = "dragon_riding_not_unlocked"
        else:
            status = "partial"
            reaction = "accepting"
            reason = "dragon_riding_runtime_required"
    else:
        status = "partial"
        reaction = "wary"
        reason = "dragon_interaction_not_resolved"

    anti_farming = _anti_farming_result(
        interaction_type,
        effect,
        recent_history,
        player_id=player_id,
        dragon_id=dragon_id,
    )
    changes = _clamped_changes(bond_value, proposed, anti_farming)
    eligibility = _next_taming_preview(
        taming,
        bond_value,
        changes,
        category_set,
        category,
        anti_farming,
    )
    return _result(
        source_interaction_event_id=source_interaction_event_id,
        dragon_id=dragon_id,
        status=status,
        interaction_type=interaction_type,
        dragon_reaction=reaction,
        relationship_effect=effect,
        reason_code=reason,
        changes=changes,
        positive_category=category,
        anti_farming=anti_farming,
        significant_event=None,
        next_taming_state_preview=eligibility,
    )
