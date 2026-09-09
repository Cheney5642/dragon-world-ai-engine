"""D3-C Dragon Candidate generation, deterministic Grounding, and commit."""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from core.dragon_encounter_decision import validate_encounter_decision
from core.free_action_resolution import load_world_skeleton
from database.persistence import PersistenceMappingError, PostgresPersistenceAdapter
from llm import LLMProviderClient, create_llm_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = PROJECT_ROOT / "prompts" / "dragon_candidate_system.md"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "dragon_candidate.schema.json"
ARCHETYPE_PATH = PROJECT_ROOT / "data" / "dragon_archetypes.json"

AGE_STAGES = {"hatchling", "juvenile", "young_adult", "adult"}
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
_FORBIDDEN_WORLD_TRUTH_PATTERNS = (
    "属于玩家",
    "玩家的龙",
    "主人",
    "被驯服",
    "已驯服",
    "驯服的",
    "羁绊",
    "坐骑",
    "允许骑乘",
    "曾经袭击",
    "曾经摧毁",
    "守护了 skeld",
    "owned by",
    "belongs to",
    "player's dragon",
    "players dragon",
    "tamed by",
    "already tamed",
    "bonded with",
    "accepts a rider",
    "riding unlocked",
    "destroyed skeld",
    "attacked skeld",
)


class DragonCandidateError(RuntimeError):
    """A D3-C candidate cannot safely become Dragon World Truth."""


def load_dragon_candidate_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise DragonCandidateError("Dragon Candidate Schema must be an object.")
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise DragonCandidateError("Dragon Candidate Schema could not be loaded.") from exc
    return schema


def validate_dragon_candidate(
    candidate: Any,
    schema: Mapping[str, Any] | None = None,
) -> None:
    schema_value = dict(schema or load_dragon_candidate_schema())
    try:
        Draft202012Validator(schema_value).validate(candidate)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise DragonCandidateError(
            f"Dragon Candidate failed Schema validation at {location}."
        ) from exc


def load_dragon_archetypes(path: Path = ARCHETYPE_PATH) -> dict[str, Any]:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DragonCandidateError("Dragon Archetype Registry could not be loaded.") from exc
    return _validated_registry(registry)


def _validated_registry(registry: Any) -> dict[str, Any]:
    if not isinstance(registry, dict) or set(registry) != {"version", "archetypes"}:
        raise DragonCandidateError("Dragon Archetype Registry fields are invalid.")
    archetypes = registry.get("archetypes")
    if not isinstance(archetypes, dict) or not archetypes:
        raise DragonCandidateError("Dragon Archetype Registry is empty.")
    for archetype_id, archetype in archetypes.items():
        if not isinstance(archetype_id, str) or not archetype_id.strip():
            raise DragonCandidateError("Dragon Archetype ID is invalid.")
        _validate_archetype(archetype)
    return registry


def _validate_archetype(archetype: Any) -> None:
    if not isinstance(archetype, Mapping) or set(archetype) != {
        "description",
        "physical_tendencies",
        "behavioral_tendencies",
        "runtime_defaults",
    }:
        raise DragonCandidateError("Dragon Archetype fields are invalid.")
    physical = archetype["physical_tendencies"]
    behavioral = archetype["behavioral_tendencies"]
    defaults = archetype["runtime_defaults"]
    if not isinstance(physical, list) or not physical or not all(
        isinstance(item, str) and item for item in physical
    ):
        raise DragonCandidateError("Archetype physical tendencies are invalid.")
    if not isinstance(behavioral, list) or not behavioral or not all(
        isinstance(item, str) and item for item in behavioral
    ):
        raise DragonCandidateError("Archetype behavioral tendencies are invalid.")
    if not isinstance(defaults, Mapping) or set(defaults) != {
        "age_stage",
        "health_state",
        "energy",
        "hunger",
        "alertness",
        "behavior_state",
        "taming_state",
    }:
        raise DragonCandidateError("Archetype runtime defaults are invalid.")
    if defaults["age_stage"] not in AGE_STAGES:
        raise DragonCandidateError("Archetype age_stage is invalid.")
    if defaults["behavior_state"] not in BEHAVIOR_STATES:
        raise DragonCandidateError("Archetype behavior_state is invalid.")
    if defaults["taming_state"] != "wild":
        raise DragonCandidateError("New encounter Archetype must remain wild.")
    if not isinstance(defaults["health_state"], str) or not defaults[
        "health_state"
    ].strip():
        raise DragonCandidateError("Archetype health_state is invalid.")
    for field in ("energy", "hunger", "alertness"):
        value = defaults[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DragonCandidateError(f"Archetype {field} is invalid.")
        if not 0 <= value <= 100:
            raise DragonCandidateError(f"Archetype {field} is outside 0..100.")


def validate_provisional_new_dragon_decision(decision: Mapping[str, Any]) -> None:
    try:
        validate_encounter_decision(decision)
    except Exception as exc:
        raise DragonCandidateError("Encounter Decision is invalid.") from exc
    if not (
        decision["outcome"] in {"sighting", "direct_encounter"}
        and decision["is_final"] is False
        and decision["requires_new_dragon"] is True
        and decision["dragon_id"] is None
    ):
        raise DragonCandidateError(
            "D3-C requires a provisional sighting/direct encounter for a new Dragon."
        )


def _non_blank(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DragonCandidateError(f"Dragon Candidate {field} must not be blank.")
    return value.strip()


def _all_candidate_text(candidate: Mapping[str, Any]) -> str:
    appearance = candidate.get("appearance")
    values: list[str] = [
        str(candidate.get("name") or ""),
        str(candidate.get("ecological_flavor") or ""),
    ]
    if isinstance(appearance, Mapping):
        values.append(str(appearance.get("description") or ""))
        features = appearance.get("distinctive_features")
        if isinstance(features, list):
            values.extend(str(item) for item in features)
    traits = candidate.get("personality_traits")
    if isinstance(traits, list):
        values.extend(str(item) for item in traits)
    return " ".join(values).casefold()


def _resolve_archetype_id(
    candidate: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> str:
    archetypes = registry.get("archetypes")
    if not isinstance(archetypes, Mapping):
        raise DragonCandidateError("Dragon Archetype Registry has no archetypes.")
    physical = candidate["physical_tendency"]
    behavioral = candidate["behavioral_tendency"]
    scored: list[tuple[int, str]] = []
    for archetype_id, archetype in archetypes.items():
        if not isinstance(archetype_id, str) or not isinstance(archetype, Mapping):
            raise DragonCandidateError("Dragon Archetype Registry entry is invalid.")
        physical_match = physical in archetype.get("physical_tendencies", [])
        if not physical_match:
            continue
        score = 2 + int(behavioral in archetype.get("behavioral_tendencies", []))
        scored.append((score, archetype_id))
    if not scored:
        raise DragonCandidateError("Dragon Candidate cannot resolve an Archetype.")
    best_score = max(score for score, _ in scored)
    best = sorted(archetype_id for score, archetype_id in scored if score == best_score)
    if len(best) != 1:
        raise DragonCandidateError("Dragon Candidate Archetype resolution is ambiguous.")
    return best[0]


def build_dragon_candidate_user_message(
    *,
    provisional_decision: Mapping[str, Any],
    encounter_location_id: str,
    locations: Mapping[str, Any],
    world_context: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
) -> str:
    validate_provisional_new_dragon_decision(provisional_decision)
    location = locations.get(encounter_location_id)
    if not isinstance(location, Mapping):
        raise DragonCandidateError("Encounter Location is not authored World Truth.")
    registry_value = _validated_registry(
        dict(registry) if registry is not None else load_dragon_archetypes()
    )
    archetypes = registry_value["archetypes"]
    physical = sorted(
        {
            tendency
            for archetype in archetypes.values()
            for tendency in archetype["physical_tendencies"]
        }
    )
    behavioral = sorted(
        {
            tendency
            for archetype in archetypes.values()
            for tendency in archetype["behavioral_tendencies"]
        }
    )
    context = {
        "provisional_encounter": provisional_decision["outcome"],
        "location": {
            "location_id": encounter_location_id,
            "name": location.get("name"),
            "type": location.get("type"),
            "description": location.get("description"),
        },
        "environment": dict(world_context or {}),
        "allowed_physical_tendencies": physical,
        "allowed_behavioral_tendencies": behavioral,
        "world_tone": "low-magic northern dark fantasy",
    }
    return json.dumps(context, ensure_ascii=False)


def generate_dragon_candidate(
    *,
    provisional_decision: Mapping[str, Any],
    encounter_location_id: str,
    locations: Mapping[str, Any],
    world_context: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
    provider_client: LLMProviderClient | None = None,
) -> dict[str, Any]:
    """Generate one schema-valid Candidate; do not Ground or persist it."""

    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DragonCandidateError("Dragon Candidate Prompt could not be read.") from exc
    if not prompt:
        raise DragonCandidateError("Dragon Candidate Prompt is empty.")
    schema = load_dragon_candidate_schema()
    client = provider_client or create_llm_client()
    output = client.create_structured_output(
        system_prompt=prompt,
        user_message=build_dragon_candidate_user_message(
            provisional_decision=provisional_decision,
            encounter_location_id=encounter_location_id,
            locations=locations,
            world_context=world_context,
            registry=registry,
        ),
        schema=schema,
        schema_name="dragon_candidate",
    )
    if not isinstance(output, str):
        raise DragonCandidateError("Dragon Candidate output must be JSON text.")
    try:
        candidate = json.loads(output)
    except ValueError as exc:
        raise DragonCandidateError("Dragon Candidate output is not valid JSON.") from exc
    validate_dragon_candidate(candidate, schema)
    return candidate


def ground_dragon_candidate(
    *,
    candidate: Mapping[str, Any],
    provisional_decision: Mapping[str, Any],
    encounter_location_id: str,
    locations: Mapping[str, Any],
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map creative Candidate data into a deterministic, safe Dragon record."""

    validate_provisional_new_dragon_decision(provisional_decision)
    validate_dragon_candidate(candidate)
    if encounter_location_id not in locations or not isinstance(
        locations[encounter_location_id], Mapping
    ):
        raise DragonCandidateError("Encounter Location is not authored World Truth.")

    name = _non_blank(candidate["name"], "name")
    appearance = candidate["appearance"]
    description = _non_blank(appearance["description"], "appearance.description")
    features = [
        _non_blank(value, "appearance.distinctive_features")
        for value in appearance["distinctive_features"]
    ]
    personality = [
        _non_blank(value, "personality_traits")
        for value in candidate["personality_traits"]
    ]
    ecological_flavor = _non_blank(
        candidate["ecological_flavor"],
        "ecological_flavor",
    )
    candidate_text = _all_candidate_text(candidate)
    if any(pattern in candidate_text for pattern in _FORBIDDEN_WORLD_TRUTH_PATTERNS):
        raise DragonCandidateError(
            "Dragon Candidate asserts ownership, bond, taming, riding, or history."
        )

    registry_value = _validated_registry(
        dict(registry) if registry is not None else load_dragon_archetypes()
    )
    archetype_id = _resolve_archetype_id(candidate, registry_value)
    archetype = registry_value["archetypes"][archetype_id]
    defaults = archetype["runtime_defaults"]
    behavior_state = defaults["behavior_state"]
    if candidate["behavioral_tendency"] == "cautious":
        behavior_state = "watching"
    elif candidate["behavioral_tendency"] == "territorial":
        behavior_state = "threatening"

    return {
        "archetype_id": archetype_id,
        "name": name,
        "sex": None,
        "age_stage": defaults["age_stage"],
        "appearance": {
            "description": description,
            "distinctive_features": features,
            "ecological_flavor": ecological_flavor,
        },
        "temperament_traits": personality,
        "current_location": encounter_location_id,
        "health_state": defaults["health_state"],
        "energy": defaults["energy"],
        "hunger": defaults["hunger"],
        "alertness": defaults["alertness"],
        "behavior_state": behavior_state,
        "taming_state": "wild",
    }


def stable_dragon_id_for_source(source_interaction_event_id: str) -> str:
    if not isinstance(source_interaction_event_id, str) or not source_interaction_event_id:
        raise DragonCandidateError("Source Interaction Event ID is invalid.")
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"dragon-world:new-dragon:{source_interaction_event_id}",
    )
    return f"dragon_{value.hex}"


def stable_first_encounter_event_id(source_interaction_event_id: str) -> str:
    if not isinstance(source_interaction_event_id, str) or not source_interaction_event_id:
        raise DragonCandidateError("Source Interaction Event ID is invalid.")
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"dragon-world:dragon-first-encounter:{source_interaction_event_id}",
    )
    return f"dragon_event_{value.hex}"


def _dragon_summary(dragon: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dragon_id": dragon["dragon_id"],
        "name": dragon["name"],
        "appearance": copy.deepcopy(dragon["appearance"]),
        "temperament_traits": list(dragon["temperament_traits"]),
        "current_location": dragon["current_location"],
        "behavior_state": dragon["behavior_state"],
        "taming_state": dragon["taming_state"],
    }


def _finalized_commit_result(
    *,
    provisional_decision: Mapping[str, Any],
    committed: Mapping[str, Any],
) -> dict[str, Any]:
    effective_decision = provisional_decision
    event_payload = committed["dragon_event"].get("event_payload")
    if committed["status"] == "already_applied":
        if not isinstance(event_payload, Mapping) or not isinstance(
            event_payload.get("provisional_decision"), Mapping
        ):
            raise DragonCandidateError(
                "Existing grounded encounter has no provisional decision audit."
            )
        effective_decision = event_payload["provisional_decision"]
        validate_provisional_new_dragon_decision(effective_decision)
    if not isinstance(event_payload, Mapping) or event_payload.get(
        "encounter_outcome"
    ) != effective_decision["outcome"]:
        raise DragonCandidateError(
            "Grounded encounter audit does not match its provisional outcome."
        )

    final_encounter = copy.deepcopy(dict(effective_decision))
    final_encounter.update(
        {
            "is_final": True,
            "requires_new_dragon": False,
            "dragon_id": committed["dragon"]["dragon_id"],
            "reason_code": f"new_dragon_committed_for_{effective_decision['outcome']}",
        }
    )
    validate_encounter_decision(final_encounter)
    return {
        "status": committed["status"],
        "encounter": final_encounter,
        "dragon": _dragon_summary(committed["dragon"]),
        "dragon_event": committed["dragon_event"],
    }


def commit_new_dragon_encounter(
    *,
    player_id: str,
    source_interaction_event_id: str,
    provisional_decision: Mapping[str, Any],
    encounter_location_id: str,
    persistence: PostgresPersistenceAdapter,
    candidate: Mapping[str, Any] | None = None,
    locations: Mapping[str, Any] | None = None,
    world_context: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
    provider_client: LLMProviderClient | None = None,
) -> dict[str, Any]:
    """Ground and atomically commit a provisional new-Dragon encounter."""

    validate_provisional_new_dragon_decision(provisional_decision)
    try:
        existing = persistence.get_grounded_dragon_encounter_by_source(
            player_id=player_id,
            source_interaction_event_id=source_interaction_event_id,
        )
    except PersistenceMappingError as exc:
        raise DragonCandidateError("Grounded Dragon retry lookup failed.") from exc
    if existing is not None:
        if existing["dragon"]["current_location"] != encounter_location_id:
            raise DragonCandidateError(
                "Existing grounded Dragon encounter has a different Location."
            )
        return _finalized_commit_result(
            provisional_decision=provisional_decision,
            committed=existing,
        )

    skeleton = load_world_skeleton()
    locations_value = dict(
        locations if locations is not None else skeleton["locations"]
    )
    candidate_value = dict(
        candidate
        if candidate is not None
        else generate_dragon_candidate(
            provisional_decision=provisional_decision,
            encounter_location_id=encounter_location_id,
            locations=locations_value,
            world_context=world_context,
            registry=registry,
            provider_client=provider_client,
        )
    )
    grounded = ground_dragon_candidate(
        candidate=candidate_value,
        provisional_decision=provisional_decision,
        encounter_location_id=encounter_location_id,
        locations=locations_value,
        registry=registry,
    )
    grounded["dragon_id"] = stable_dragon_id_for_source(
        source_interaction_event_id
    )
    event_payload = {
        "provisional_decision": copy.deepcopy(dict(provisional_decision)),
        "candidate": copy.deepcopy(candidate_value),
        "grounding": {
            "archetype_id": grounded["archetype_id"],
            "encounter_location_id": encounter_location_id,
            "taming_state": "wild",
        },
    }
    try:
        committed = persistence.commit_grounded_dragon_encounter(
            player_id=player_id,
            source_interaction_event_id=source_interaction_event_id,
            dragon=grounded,
            dragon_event_id=stable_first_encounter_event_id(
                source_interaction_event_id
            ),
            encounter_outcome=provisional_decision["outcome"],
            event_payload=event_payload,
        )
    except PersistenceMappingError as exc:
        raise DragonCandidateError("Grounded Dragon commit failed.") from exc

    return _finalized_commit_result(
        provisional_decision=provisional_decision,
        committed=committed,
    )
