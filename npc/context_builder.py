"""Deterministic, read-only minimum-context builder for Generic NPCs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
PROFILE_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_profile.schema.json"
CONTEXT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_context.schema.json"


class NpcContextError(Exception):
    """Raised when a safe, schema-valid NPC Context cannot be built."""


def _load_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise NpcContextError(f"{label} does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcContextError(f"{label} could not be read as valid JSON: {path}") from exc


def load_anchor_profiles(path: Path = PROFILES_PATH) -> dict[str, Any]:
    document = _load_json(path, "Anchor NPC Profile data")
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), list):
        raise NpcContextError("Anchor NPC Profile data must contain a profiles array.")
    return document


def load_profile_schema(path: Path = PROFILE_SCHEMA_PATH) -> dict[str, Any]:
    schema = _load_json(path, "NPC Profile Schema")
    if not isinstance(schema, dict):
        raise NpcContextError("NPC Profile Schema must be a JSON object.")
    return schema


def load_context_schema(path: Path = CONTEXT_SCHEMA_PATH) -> dict[str, Any]:
    schema = _load_json(path, "NPC Context Schema")
    if not isinstance(schema, dict):
        raise NpcContextError("NPC Context Schema must be a JSON object.")
    return schema


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    except (SchemaError, ValidationError) as exc:
        raise NpcContextError(f"{label} failed JSON Schema validation: {exc.message}") from exc


def _find_profile(npc_id: str, document: dict[str, Any]) -> dict[str, Any]:
    matches = [
        profile
        for profile in document["profiles"]
        if isinstance(profile, dict) and profile.get("id") == npc_id
    ]
    if not matches:
        raise NpcContextError(f"Unknown NPC Profile id: {npc_id}")
    if len(matches) != 1:
        raise NpcContextError(f"NPC Profile id is not unique: {npc_id}")
    return matches[0]


def _npc_states_by_id(world_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    npc_collection = world_state.get("npcs")
    if not isinstance(npc_collection, dict):
        raise NpcContextError("World State does not contain a valid NPC registry.")

    resolved: dict[str, dict[str, Any]] = {}
    for npc in npc_collection.values():
        if not isinstance(npc, dict) or not isinstance(npc.get("id"), str):
            raise NpcContextError("World State contains an NPC without a valid id.")
        npc_id = npc["id"]
        if npc_id in resolved:
            raise NpcContextError(f"World State NPC id is not unique: {npc_id}")
        resolved[npc_id] = npc
    return resolved


def _locations_by_id(world_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    locations = world_state.get("locations")
    if not isinstance(locations, dict):
        raise NpcContextError("World State does not contain a valid Location registry.")
    if not all(isinstance(value, dict) for value in locations.values()):
        raise NpcContextError("World State contains an invalid Location record.")
    return locations


def _location_summary(
    location_id: str,
    locations: dict[str, dict[str, Any]],
) -> dict[str, str]:
    location = locations.get(location_id)
    if location is None:
        raise NpcContextError(f"Unknown Location id in NPC Context: {location_id}")
    for field in ("name", "type", "description"):
        if not isinstance(location.get(field), str) or not location[field]:
            raise NpcContextError(
                f"Location {location_id} is missing public field: {field}"
            )
    return {
        "id": location_id,
        "name": location["name"],
        "type": location["type"],
        "public_summary": location["description"],
    }


def _public_entity_summary(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entity.get("id"),
        "name": entity.get("name"),
        "species": entity.get("species"),
        "occupation": entity.get("occupation"),
    }


def build_npc_context(
    npc_id: str,
    world_state: dict[str, Any],
    player_id: str = "player_001",
    *,
    profiles_document: dict[str, Any] | None = None,
    profile_schema: dict[str, Any] | None = None,
    context_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one minimal NPC Context without mutating any input or world data."""

    if not isinstance(npc_id, str) or not npc_id:
        raise NpcContextError("npc_id must be a non-empty string.")
    if not isinstance(world_state, dict):
        raise NpcContextError("world_state must be a JSON object.")

    profiles_document = profiles_document or load_anchor_profiles()
    profile_schema = profile_schema or load_profile_schema()
    context_schema = context_schema or load_context_schema()

    profile = _find_profile(npc_id, profiles_document)
    _validate(profile, profile_schema, f"NPC Profile {npc_id}")

    npc_states = _npc_states_by_id(world_state)
    npc_state = npc_states.get(npc_id)
    if npc_state is None:
        raise NpcContextError(
            f"NPC Profile id {npc_id} does not resolve to Persistent World State."
        )
    if npc_state.get("id") != profile.get("id"):
        raise NpcContextError(f"NPC Profile and World State id mismatch: {npc_id}")

    player = world_state.get("player")
    if not isinstance(player, dict) or player.get("id") != player_id:
        raise NpcContextError(
            f"Player id {player_id} does not resolve to Persistent World State."
        )

    locations = _locations_by_id(world_state)
    npc_location_id = npc_state.get("current_location")
    player_location_id = player.get("current_location")
    if not isinstance(npc_location_id, str):
        raise NpcContextError(f"NPC {npc_id} has no valid current_location.")
    if not isinstance(player_location_id, str):
        raise NpcContextError(f"Player {player_id} has no valid current_location.")
    npc_location_summary = _location_summary(npc_location_id, locations)
    _location_summary(player_location_id, locations)

    current_activity = npc_state.get("current_activity")
    mood = npc_state.get("mood")
    if current_activity is not None and not isinstance(current_activity, str):
        raise NpcContextError(f"NPC {npc_id} has an invalid current_activity.")
    if mood is not None and not isinstance(mood, str):
        raise NpcContextError(f"NPC {npc_id} has an invalid mood.")

    known_entities: list[dict[str, Any]] = []
    for known_id in profile["knowledge"]["known_entities"]:
        if known_id == player_id:
            known_entity = player
        else:
            known_entity = npc_states.get(known_id)
        if known_entity is None:
            raise NpcContextError(
                f"NPC Profile {npc_id} references unknown Entity id: {known_id}"
            )
        known_entities.append(_public_entity_summary(known_entity))

    known_locations = [
        _location_summary(location_id, locations)
        for location_id in profile["knowledge"]["known_locations"]
    ]

    world = world_state.get("world")
    if not isinstance(world, dict):
        raise NpcContextError("World State does not contain valid world data.")

    context = {
        "npc": {
            "id": profile["id"],
            "name": profile["name"],
            "species": profile["species"],
            "occupation": profile["occupation"],
            "background": profile["background"],
            "personality": copy.deepcopy(profile["personality"]),
            "goals": copy.deepcopy(profile["goals"]),
        },
        "runtime_state": {
            "current_location": npc_location_id,
            "current_activity": current_activity,
            "mood": mood,
        },
        "player": {
            "id": player["id"],
            "name": player.get("name"),
            "species": player.get("species"),
            "occupation": player.get("occupation"),
            "current_location": player_location_id,
        },
        "shared_context": {
            "same_location": npc_location_id == player_location_id,
            "world_day": world.get("day"),
            "world_hour": world.get("hour"),
            "weather": world.get("weather"),
            "current_location_summary": npc_location_summary,
        },
        "knowledge": {
            "known_entities": known_entities,
            "known_locations": known_locations,
            "known_facts": copy.deepcopy(profile["knowledge"]["known_facts"]),
        },
    }
    _validate(context, context_schema, f"NPC Context {npc_id}")
    return context
