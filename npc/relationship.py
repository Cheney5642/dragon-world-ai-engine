"""Deterministic, read-only NPC Relationship evaluation v0.1."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from npc.interaction_event import (
    NpcInteractionEventError,
    validate_interaction_event,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELATIONSHIP_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_relationship.schema.json"
CHANGE_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_relationship_change.schema.json"
)

FAMILIARITY_MIN = 0
FAMILIARITY_MAX = 3
TRUST_MIN = -2
TRUST_MAX = 2

# These topics represent evidence already grounded by an upstream authority.
# The Evaluator never infers them by re-reading raw dialogue.
GROUNDED_POSITIVE_TOPICS = {
    "grounded_help",
    "grounded_help_family",
    "fulfilled_commitment",
    "protected_npc_or_family",
    "verified_shared_result",
}
GROUNDED_NEGATIVE_TOPICS = {
    "direct_threat",
    "direct_insult",
    "grounded_deception",
    "grounded_harm",
}


class NpcRelationshipError(Exception):
    """Raised when a safe, schema-valid Relationship Preview cannot be built."""


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise NpcRelationshipError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcRelationshipError(f"{label} is not valid readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NpcRelationshipError(f"{label} must contain a JSON object: {path}")
    return value


def load_relationship_schema(
    path: Path = RELATIONSHIP_SCHEMA_PATH,
) -> dict[str, Any]:
    return _load_json_object(path, "NPC Relationship Schema")


def load_relationship_change_schema(
    path: Path = CHANGE_SCHEMA_PATH,
) -> dict[str, Any]:
    return _load_json_object(path, "NPC Relationship Change Schema")


def validate_relationship(
    relationship: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_relationship_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(relationship)
    except (SchemaError, ValidationError) as exc:
        raise NpcRelationshipError(
            f"NPC Relationship failed JSON Schema validation: {exc.message}"
        ) from exc


def _resolved_change_schema(
    change_schema: dict[str, Any],
    relationship_schema: dict[str, Any],
) -> dict[str, Any]:
    resolved = copy.deepcopy(change_schema)
    resolved["properties"]["current_relationship"] = copy.deepcopy(
        relationship_schema
    )
    resolved["properties"]["proposed_relationship"] = copy.deepcopy(
        relationship_schema
    )
    return resolved


def validate_relationship_change(
    preview: dict[str, Any],
    *,
    change_schema: dict[str, Any] | None = None,
    relationship_schema: dict[str, Any] | None = None,
) -> None:
    change_schema = change_schema or load_relationship_change_schema()
    relationship_schema = relationship_schema or load_relationship_schema()
    resolved = _resolved_change_schema(change_schema, relationship_schema)
    try:
        Draft202012Validator.check_schema(resolved)
        Draft202012Validator(resolved).validate(preview)
    except (SchemaError, ValidationError) as exc:
        raise NpcRelationshipError(
            f"NPC Relationship Change failed JSON Schema validation: {exc.message}"
        ) from exc

    current = preview["current_relationship"]
    proposed = preview["proposed_relationship"]
    changes = preview["changes"]
    for dimension in ("familiarity", "trust"):
        change = changes[dimension]
        expected_delta = proposed[dimension] - current[dimension]
        if change["before"] != current[dimension]:
            raise NpcRelationshipError(f"{dimension} change before value is inconsistent.")
        if change["after"] != proposed[dimension]:
            raise NpcRelationshipError(f"{dimension} change after value is inconsistent.")
        if change["delta"] != expected_delta:
            raise NpcRelationshipError(f"{dimension} change delta is inconsistent.")
        if change["changed"] is not (expected_delta != 0):
            raise NpcRelationshipError(f"{dimension} changed flag is inconsistent.")

    attitude_change = changes["attitude"]
    attitude_changed = current["attitude"] != proposed["attitude"]
    if attitude_change["before"] != current["attitude"]:
        raise NpcRelationshipError("attitude change before value is inconsistent.")
    if attitude_change["after"] != proposed["attitude"]:
        raise NpcRelationshipError("attitude change after value is inconsistent.")
    if attitude_change["changed"] is not attitude_changed:
        raise NpcRelationshipError("attitude changed flag is inconsistent.")

    any_change = any(changes[item]["changed"] for item in changes)
    expected_decision = "change_proposed" if any_change else "no_change"
    if preview["decision"] != expected_decision:
        raise NpcRelationshipError("Relationship decision is inconsistent with changes.")


def create_initial_relationship(
    npc_id: str,
    player_id: str,
    *,
    acquainted: bool = False,
) -> dict[str, Any]:
    """Create a minimal fixture state; C1 does not persist this value."""

    relationship = {
        "npc_id": npc_id,
        "player_id": player_id,
        "familiarity": 1 if acquainted else 0,
        "trust": 0,
        "attitude": "neutral",
    }
    validate_relationship(relationship)
    return relationship


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _is_grounded_positive(event: dict[str, Any]) -> bool:
    return (
        event["event_type"] == "npc_dialogue"
        and event["relationship_signal"] == "potential_positive"
        and event["topic"] in GROUNDED_POSITIVE_TOPICS
        and event["memory_candidate"] is True
        and event["player_claims"] == []
        and event["npc_response"]["response_type"] in {"answer", "reaction"}
    )


def _is_grounded_negative(event: dict[str, Any]) -> bool:
    return (
        event["event_type"] == "npc_dialogue"
        and event["relationship_signal"] == "potential_negative"
        and event["topic"] in GROUNDED_NEGATIVE_TOPICS
        and event["memory_candidate"] is True
        and event["npc_response"]["response_type"]
        in {"disagreement", "reaction", "refusal"}
    )


def _positive_attitude(current: str, new_trust: int) -> str:
    if current == "neutral" and new_trust >= 1:
        return "warm"
    if current == "wary" and new_trust >= 0:
        return "neutral"
    return current


def _negative_attitude(current: str, new_trust: int) -> str:
    if current in {"neutral", "warm"}:
        return "wary"
    if current == "wary" and new_trust <= TRUST_MIN:
        return "hostile"
    return current


def _changes(
    current: dict[str, Any],
    proposed: dict[str, Any],
) -> dict[str, Any]:
    familiarity_delta = proposed["familiarity"] - current["familiarity"]
    trust_delta = proposed["trust"] - current["trust"]
    return {
        "familiarity": {
            "changed": familiarity_delta != 0,
            "before": current["familiarity"],
            "after": proposed["familiarity"],
            "delta": familiarity_delta,
        },
        "trust": {
            "changed": trust_delta != 0,
            "before": current["trust"],
            "after": proposed["trust"],
            "delta": trust_delta,
        },
        "attitude": {
            "changed": current["attitude"] != proposed["attitude"],
            "before": current["attitude"],
            "after": proposed["attitude"],
        },
    }


def evaluate_relationship_change(
    current_relationship: dict[str, Any],
    interaction_event: dict[str, Any],
    *,
    relationship_schema: dict[str, Any] | None = None,
    change_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Propose a conservative relationship change without mutating inputs."""

    relationship_schema = relationship_schema or load_relationship_schema()
    change_schema = change_schema or load_relationship_change_schema()
    validate_relationship(current_relationship, relationship_schema)
    try:
        validate_interaction_event(interaction_event)
    except NpcInteractionEventError as exc:
        raise NpcRelationshipError(
            f"Relationship evaluation requires a validated Interaction Event: {exc}"
        ) from exc

    if current_relationship["npc_id"] != interaction_event["npc_id"]:
        raise NpcRelationshipError("Relationship NPC id does not match Interaction Event.")
    if current_relationship["player_id"] != interaction_event["player_id"]:
        raise NpcRelationshipError(
            "Relationship Player id does not match Interaction Event."
        )

    current = copy.deepcopy(current_relationship)
    proposed = copy.deepcopy(current_relationship)

    if _is_grounded_positive(interaction_event):
        proposed["familiarity"] = _clamp(
            proposed["familiarity"] + 1,
            FAMILIARITY_MIN,
            FAMILIARITY_MAX,
        )
        proposed["trust"] = _clamp(
            proposed["trust"] + 1,
            TRUST_MIN,
            TRUST_MAX,
        )
        proposed["attitude"] = _positive_attitude(
            proposed["attitude"],
            proposed["trust"],
        )
        reason = "Grounded meaningful help supports one small positive change."
    elif _is_grounded_negative(interaction_event):
        proposed["trust"] = _clamp(
            proposed["trust"] - 1,
            TRUST_MIN,
            TRUST_MAX,
        )
        proposed["attitude"] = _negative_attitude(
            proposed["attitude"],
            proposed["trust"],
        )
        reason = "A grounded hostile interaction supports one small negative change."
    elif interaction_event["player_claims"]:
        reason = "Player claims do not establish Relationship Facts or grounded outcomes."
    else:
        reason = "This Interaction Event does not contain sufficient grounded relationship evidence."

    changes = _changes(current, proposed)
    decision = (
        "change_proposed"
        if any(change["changed"] for change in changes.values())
        else "no_change"
    )
    preview = {
        "npc_id": current["npc_id"],
        "player_id": current["player_id"],
        "source_event_id": interaction_event["event_id"],
        "decision": decision,
        "current_relationship": current,
        "proposed_relationship": proposed,
        "changes": changes,
        "reason": reason,
    }
    validate_relationship_change(
        preview,
        change_schema=change_schema,
        relationship_schema=relationship_schema,
    )
    return preview
