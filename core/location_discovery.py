"""D5 controlled dynamic location discovery without a second world engine."""

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

from core.free_action_interpreter import validate_action_interpretation
from core.free_action_resolution import validate_resolution_result
from llm import LLMProviderClient, create_llm_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = PROJECT_ROOT / "prompts" / "location_candidate_system.md"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "location_candidate.schema.json"
DYNAMIC_LOCATION_REGISTRY_STATE_ID = "world.dynamic_locations.v1"

_DRAGON_TERMS = ("龙", "dragon")
_DISCOVERY_TERMS = (
    "未知",
    "未探索",
    "没去过",
    "从未去过",
    "新地方",
    "新地点",
    "道路",
    "路径",
    "深处",
    "海岸",
    "山脊",
    "unknown",
    "unexplored",
    "new place",
    "new location",
    "path",
    "route",
    "deeper",
    "coast",
    "ridge",
)
_FORBIDDEN_WORLD_TRUTH_PATTERNS = (
    "属于玩家",
    "我的领地",
    "玩家拥有",
    "玩家统治",
    "国王",
    "王国",
    "派系",
    "部落",
    "居民",
    "村民",
    "商人居住",
    "任务",
    "龙穴",
    "龙巢",
    "巨龙",
    "龙群",
    "owned by",
    "belongs to the player",
    "player rules",
    "kingdom",
    "faction",
    "inhabitants",
    "villagers",
    "quest",
    "dragon",
)


class LocationDiscoveryError(RuntimeError):
    """A location Candidate or Registry operation is not safely grounded."""


def load_location_candidate_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise LocationDiscoveryError("Location Candidate Schema must be an object.")
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise LocationDiscoveryError("Location Candidate Schema could not be loaded.") from exc
    return schema


def validate_location_candidate(
    candidate: Any,
    schema: Mapping[str, Any] | None = None,
) -> None:
    try:
        Draft202012Validator(dict(schema or load_location_candidate_schema())).validate(
            candidate
        )
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise LocationDiscoveryError(
            f"Location Candidate failed Schema validation at {location}."
        ) from exc


def _action_text(structured_action: Mapping[str, Any]) -> str:
    return " ".join(
        str(structured_action.get(field) or "")
        for field in ("action", "target", "direction", "intent", "method")
    ).casefold()


def is_location_discovery_eligible(
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
) -> bool:
    """Strictly gate unknown-world exploration before any Candidate call."""

    validate_action_interpretation(structured_action)
    validate_resolution_result(resolution)
    if (
        resolution["status"] not in {"success", "partial"}
        or resolution["domain_route"] is not None
        or structured_action["needs_clarification"]
        or structured_action["explicit_goal"] is not None
        or structured_action["destination"] is not None
    ):
        return False

    text = _action_text(structured_action)
    if any(term in text for term in _DRAGON_TERMS):
        return False

    family = structured_action["action_family"]
    direction = structured_action["direction"]
    if family == "explore":
        return isinstance(direction, str) and bool(direction.strip())
    if family == "observe_search":
        return (
            isinstance(direction, str)
            and bool(direction.strip())
            and any(term in text for term in _DISCOVERY_TERMS)
        )
    return False


def build_location_candidate_user_message(
    *,
    structured_action: Mapping[str, Any],
    current_location_id: str,
    locations: Mapping[str, Any],
) -> str:
    location = locations.get(current_location_id)
    if not isinstance(location, Mapping):
        raise LocationDiscoveryError("Current Location is not grounded World Truth.")
    context = {
        "current_location": {
            "location_id": current_location_id,
            "name": location.get("name"),
            "location_type": location.get("type"),
            "short_description": location.get("description"),
        },
        "exploration": {
            field: copy.deepcopy(structured_action.get(field))
            for field in ("action", "target", "direction", "intent", "method")
        },
        "world_tone": "low-magic northern dark fantasy",
    }
    return json.dumps(context, ensure_ascii=False)


def generate_location_candidate(
    *,
    structured_action: Mapping[str, Any],
    current_location_id: str,
    locations: Mapping[str, Any],
    provider_client: LLMProviderClient | None = None,
) -> dict[str, Any]:
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LocationDiscoveryError("Location Candidate Prompt could not be read.") from exc
    if not prompt:
        raise LocationDiscoveryError("Location Candidate Prompt is empty.")
    schema = load_location_candidate_schema()
    client = provider_client or create_llm_client()
    output = client.create_structured_output(
        system_prompt=prompt,
        user_message=build_location_candidate_user_message(
            structured_action=structured_action,
            current_location_id=current_location_id,
            locations=locations,
        ),
        schema=schema,
        schema_name="location_candidate",
    )
    if not isinstance(output, str):
        raise LocationDiscoveryError("Location Candidate output must be JSON text.")
    try:
        candidate = json.loads(output)
    except ValueError as exc:
        raise LocationDiscoveryError("Location Candidate output is not valid JSON.") from exc
    validate_location_candidate(candidate, schema)
    return candidate


def stable_location_id_for_source(source_interaction_event_id: str) -> str:
    if not isinstance(source_interaction_event_id, str) or not source_interaction_event_id:
        raise LocationDiscoveryError("Source Interaction Event ID is invalid.")
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"dragon-world:dynamic-location:{source_interaction_event_id}",
    )
    return f"location_{value.hex}"


def _normalized_name(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def ground_location_candidate(
    *,
    candidate: Mapping[str, Any],
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
    source_interaction_event_id: str,
    current_location_id: str,
    locations: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert creative text into a runtime-owned dynamic Location proposal."""

    if not is_location_discovery_eligible(structured_action, resolution):
        raise LocationDiscoveryError("Action is not eligible for Location discovery.")
    validate_location_candidate(candidate)
    if current_location_id not in locations or not isinstance(
        locations[current_location_id], Mapping
    ):
        raise LocationDiscoveryError("Current Location is not grounded World Truth.")

    values = [
        candidate["name"],
        candidate["short_description"],
        candidate["discovery_reason"],
        *candidate["environment_tags"],
    ]
    cleaned = [str(value).strip() for value in values]
    if any(not value for value in cleaned):
        raise LocationDiscoveryError("Location Candidate contains blank narrative text.")
    candidate_text = " ".join(cleaned).casefold()
    if any(pattern in candidate_text for pattern in _FORBIDDEN_WORLD_TRUTH_PATTERNS):
        raise LocationDiscoveryError(
            "Location Candidate asserts entities, ownership, faction, quest, or Dragon facts."
        )

    name = str(candidate["name"]).strip()
    wanted_name = _normalized_name(name)
    for location in locations.values():
        if not isinstance(location, Mapping):
            raise LocationDiscoveryError("Location Registry contains an invalid entry.")
        existing_name = location.get("name")
        if isinstance(existing_name, str) and _normalized_name(existing_name) == wanted_name:
            raise LocationDiscoveryError("Location Candidate name already exists.")

    location_id = stable_location_id_for_source(source_interaction_event_id)
    if location_id in locations:
        raise LocationDiscoveryError("Stable Dynamic Location ID already exists.")
    return {
        "location_id": location_id,
        "name": name,
        "location_type": str(candidate["location_type"]).strip(),
        "short_description": str(candidate["short_description"]).strip(),
        "environment_tags": [
            str(value).strip() for value in candidate["environment_tags"]
        ],
        "discovery_reason": str(candidate["discovery_reason"]).strip(),
        "origin": "dynamic",
        "discovery_status": "discovered",
        "source_interaction_event_id": source_interaction_event_id,
        "discovered_from_location_id": current_location_id,
        "connections": [current_location_id],
    }


def empty_dynamic_location_registry() -> dict[str, Any]:
    return {"version": 1, "locations": {}}


def validate_dynamic_location_registry(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {"version", "locations"}:
        raise LocationDiscoveryError("Dynamic Location Registry fields are invalid.")
    if value["version"] != 1 or not isinstance(value["locations"], Mapping):
        raise LocationDiscoveryError("Dynamic Location Registry version is invalid.")
    for location_id, location in value["locations"].items():
        if not isinstance(location_id, str) or not isinstance(location, Mapping):
            raise LocationDiscoveryError("Dynamic Location Registry entry is invalid.")
        required = {
            "location_id", "name", "location_type", "short_description",
            "environment_tags", "discovery_reason", "origin",
            "discovery_status", "source_interaction_event_id",
            "discovered_from_location_id", "connections",
        }
        if set(location) != required or location.get("location_id") != location_id:
            raise LocationDiscoveryError("Dynamic Location Registry contract is invalid.")
        if location.get("origin") != "dynamic" or location.get("discovery_status") != "discovered":
            raise LocationDiscoveryError("Dynamic Location Registry truth state is invalid.")
        if not isinstance(location.get("connections"), list):
            raise LocationDiscoveryError("Dynamic Location connections are invalid.")


def merge_location_registries(
    authored_locations: Mapping[str, Any],
    dynamic_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge PostgreSQL overlay into the authored directed graph."""

    validate_dynamic_location_registry(dynamic_registry)
    merged = copy.deepcopy(dict(authored_locations))
    dynamic_locations = dynamic_registry["locations"]
    for location_id, location in dynamic_locations.items():
        if location_id in merged:
            raise LocationDiscoveryError("Dynamic Location ID conflicts with authored World.")
        merged[location_id] = {
            "name": location["name"],
            "type": location["location_type"],
            "description": location["short_description"],
            "environment_tags": list(location["environment_tags"]),
            "origin": "dynamic",
            "connections": list(location["connections"]),
        }
    for location_id, location in dynamic_locations.items():
        source_id = location["discovered_from_location_id"]
        if source_id not in merged:
            raise LocationDiscoveryError("Dynamic Location source is not grounded.")
        source_connections = merged[source_id].get("connections")
        if not isinstance(source_connections, list):
            raise LocationDiscoveryError("Location connections are invalid.")
        if location_id not in source_connections:
            source_connections.append(location_id)
        if any(connection not in merged for connection in location["connections"]):
            raise LocationDiscoveryError("Dynamic Location references an unknown connection.")
    return merged
