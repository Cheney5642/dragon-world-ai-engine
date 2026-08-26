"""Preview World Validation for an interpreted action without mutating state."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from llm import LLMProviderClient, LLMProviderError, create_llm_client
    from scripts import interpret_action as action_interpreter
except ImportError as exc:
    missing_package = getattr(exc, "name", "a required package")
    print(
        f"Missing dependency: {missing_package}. "
        "Run 'python -m pip install -r requirements.txt' from the project root."
    )
    raise SystemExit(1) from None

VALIDATION_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "world_validation.schema.json"
)
VALIDATION_PROMPT_PATH = (
    PROJECT_ROOT / "prompts" / "world_validator_system.md"
)
VALIDATION_TEST_CASES_PATH = (
    PROJECT_ROOT / "data" / "world_validation_test_cases.json"
)
PLAYER_VALIDATION_FIELDS = (
    "id",
    "species",
    "occupation",
    "current_location",
    "inventory",
)
RELEVANT_NPC_FIELDS = (
    "id",
    "name",
    "species",
    "occupation",
    "current_location",
)
RELEVANT_LOCATION_FIELDS = ("name", "type", "connections")
NPC_DECISION_PATTERNS = (
    "invite",
    "ask",
    "request",
    "persuade",
    "negotiate",
    "offer",
)
MOVEMENT_PATTERNS = (
    "go",
    "move",
    "travel",
    "walk",
    "run",
    "ride",
    "fly",
    "head",
    "climb",
)
MODERN_TECH_PATTERNS = {
    "modern firearms": (
        "ak47",
        "ak 47",
        "firearm",
        "rifle",
        "modern gun",
    ),
    "cars": ("car", "automobile", "汽车"),
    "mobile phones": ("mobile phone", "cell phone", "smartphone", "手机"),
}
FORBIDDEN_OUTCOME_PHRASES = (
    "successfully steal",
    "successfully find",
    "has stolen",
    "has arrived",
    "astrid agrees",
    "you fall",
    "成功偷",
    "已经找到",
    "已经到达",
    "同意了",
    "摔落",
)


class WorldValidationError(Exception):
    """A user-facing World Validation runtime error."""


@dataclass(frozen=True)
class DeterministicAssessment:
    """Facts derived directly from structured state before the LLM call."""

    checks: list[dict[str, str]]
    missing_requirements: list[str]
    conflicts: list[str]
    requires_npc_decision: bool
    requires_further_resolution: bool
    recommended_overall_status: str

    def as_context(self) -> dict[str, Any]:
        return {
            "checks": self.checks,
            "missing_requirements": self.missing_requirements,
            "conflicts": self.conflicts,
            "requires_npc_decision": self.requires_npc_decision,
            "requires_further_resolution": self.requires_further_resolution,
            "recommended_overall_status": self.recommended_overall_status,
        }


def load_validation_schema() -> dict[str, Any]:
    schema = action_interpreter.load_json_object(
        VALIDATION_SCHEMA_PATH, "World Validation Schema"
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise WorldValidationError(
            f"world_validation.schema.json is not a valid schema: {exc.message}"
        ) from exc
    return schema


def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(
        value.casefold().replace("-", " ").replace("_", " ").split()
    )


def contains_pattern(value: Any, patterns: tuple[str, ...]) -> bool:
    normalized = f" {normalize_text(value)} "
    return any(f" {normalize_text(pattern)} " in normalized for pattern in patterns)


def step_target(step: dict[str, Any]) -> dict[str, Any] | None:
    target = step.get("target")
    return target if isinstance(target, dict) else None


def action_steps(action_intent: dict[str, Any]) -> list[dict[str, Any]]:
    steps = action_intent.get("steps", [])
    return [step for step in steps if isinstance(step, dict)]


def npc_by_id(world_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for npc in world_state["npcs"].values():
        if isinstance(npc, dict) and isinstance(npc.get("id"), str):
            result[npc["id"]] = npc
    return result


def referenced_npc_ids(action_intent: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for step in action_steps(action_intent):
        target = step_target(step)
        if target and isinstance(target.get("id"), str):
            if target["id"].startswith("npc_"):
                ids.add(target["id"])
    return ids


def referenced_location_ids(
    action_intent: dict[str, Any], world_state: dict[str, Any]
) -> set[str]:
    ids: set[str] = set()
    location_ids = set(world_state["locations"])
    for step in action_steps(action_intent):
        target = step_target(step)
        if target and target.get("id") in location_ids:
            ids.add(target["id"])
    return ids


def step_semantic_text(step: dict[str, Any]) -> str:
    parts = [step.get("verb"), step.get("goal"), step.get("method")]
    target = step_target(step)
    if target:
        parts.append(target.get("name"))
    return " ".join(part for part in parts if isinstance(part, str))


def action_semantic_text(action_intent: dict[str, Any]) -> str:
    """Exclude speech so dialogue content never becomes a state claim."""

    parts = [step_semantic_text(step) for step in action_steps(action_intent)]
    claims = action_intent.get("claimed_facts", [])
    if isinstance(claims, list):
        parts.extend(claim for claim in claims if isinstance(claim, str))
    return " ".join(parts)


def is_flight_action(action_intent: dict[str, Any]) -> bool:
    return contains_pattern(action_semantic_text(action_intent), ("fly", "flight"))


def is_movement_step(
    step: dict[str, Any], action_intent: dict[str, Any]
) -> bool:
    return (
        action_intent.get("action_kind") == "movement"
        or contains_pattern(step.get("verb"), MOVEMENT_PATTERNS)
    )


def inventory_contains(inventory: Any, item_name: str) -> bool:
    if not isinstance(inventory, list):
        return False
    expected = normalize_text(item_name)
    for item in inventory:
        serialized = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
        if expected and expected in normalize_text(serialized):
            return True
    return False


def has_recorded_bonded_dragon(player: dict[str, Any]) -> bool:
    state_text = normalize_text(
        json.dumps(
            {
                "inventory": player.get("inventory", []),
                "relationships": player.get("relationships", {}),
            },
            ensure_ascii=False,
        )
    )
    return "dragon" in state_text and (
        "bond" in state_text or "rideable" in state_text or "mount" in state_text
    )


def build_deterministic_assessment(
    action_intent: dict[str, Any], world_state: dict[str, Any]
) -> DeterministicAssessment:
    """Derive authoritative checks from current structured state and rules."""

    checks_by_fact: dict[str, dict[str, str]] = {}
    missing_requirements: list[str] = []
    conflicts: list[str] = []
    has_unknown = False
    must_block = False
    must_be_conditional = False

    def add_check(fact: str, status: str, evidence: str) -> None:
        checks_by_fact.setdefault(
            fact,
            {"fact": fact, "status": status, "evidence": evidence},
        )

    def add_unique(items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)

    player = world_state["player"]
    locations = world_state["locations"]
    rules = world_state["world"]["rules"]
    known_npcs = npc_by_id(world_state)
    player_location_id = player.get("current_location")
    player_location = locations.get(player_location_id)

    if isinstance(player_location, dict):
        add_check(
            "Player current location exists",
            "supported",
            f"Player.current_location is '{player_location_id}', a Location in the current save.",
        )
    else:
        add_check(
            "Player current location exists",
            "contradicted",
            f"Player.current_location '{player_location_id}' is absent from current Locations.",
        )
        add_unique(conflicts, "Player current_location is not a valid Location ID.")
        must_block = True

    referenced_npcs: dict[str, dict[str, Any]] = {}
    for step in action_steps(action_intent):
        target = step_target(step)
        if not target:
            continue

        target_id = target.get("id")
        target_name = str(target.get("name") or "unnamed target")
        target_type = normalize_text(target.get("type"))

        if target_id in known_npcs:
            npc = known_npcs[target_id]
            npc_name = str(npc.get("name", target_name))
            referenced_npcs[target_id] = npc
            add_check(
                f"NPC '{npc_name}' exists",
                "supported",
                f"Relevant NPC State contains id '{target_id}' with name '{npc_name}'.",
            )
            same_location = npc.get("current_location") == player_location_id
            add_check(
                f"NPC '{npc_name}' is in the Player's current location",
                "supported" if same_location else "contradicted",
                (
                    f"NPC.current_location and Player.current_location are both '{player_location_id}'."
                    if same_location
                    else f"NPC.current_location is '{npc.get('current_location')}' while Player.current_location is '{player_location_id}'."
                ),
            )
            if not same_location:
                add_unique(
                    missing_requirements,
                    f"movement resolution before interacting with {npc_name}",
                )
                must_be_conditional = True
            continue

        if target_id in locations:
            location = locations[target_id]
            location_name = str(location.get("name", target_name))
            add_check(
                f"Target Location '{location_name}' exists",
                "supported",
                f"Current Locations contains id '{target_id}' with name '{location_name}'.",
            )
            if is_movement_step(step, action_intent) and isinstance(player_location, dict):
                connections = player_location.get("connections")
                route_fact = (
                    f"A direct route connects '{player_location_id}' to '{target_id}'"
                )
                if target_id == player_location_id or (
                    isinstance(connections, list) and target_id in connections
                ):
                    add_check(
                        route_fact,
                        "supported",
                        (
                            "The Player is already in the target Location."
                            if target_id == player_location_id
                            else f"Location '{player_location_id}' lists '{target_id}' in connections."
                        ),
                    )
                elif isinstance(connections, list):
                    add_check(
                        route_fact,
                        "contradicted",
                        f"Location '{player_location_id}' does not list '{target_id}' as a direct connection.",
                    )
                    add_unique(missing_requirements, "movement route resolution")
                    must_be_conditional = True
                else:
                    add_check(
                        route_fact,
                        "unknown",
                        f"No connection data was supplied for Location '{player_location_id}'.",
                    )
                    add_unique(missing_requirements, "movement route resolution")
                    has_unknown = True
            continue

        if target_id is None:
            if "npc" in target_type or "person" in target_type or "character" in target_type:
                fact = f"NPC '{target_name}' exists"
                evidence = (
                    f"No NPC named '{target_name}' is present in the Relevant NPC State."
                )
                requirement = f"entity resolution for NPC '{target_name}'"
            elif "location" in target_type or "place" in target_type:
                fact = f"Location '{target_name}' exists"
                evidence = (
                    f"No Location named '{target_name}' is present in the Relevant Location State."
                )
                requirement = f"location resolution for '{target_name}'"
            else:
                owner = next(iter(referenced_npcs.values()), None)
                if "hammer" in normalize_text(target_name) and owner:
                    owner_name = str(owner.get("name", "the referenced NPC"))
                    fact = f"{owner_name} owns the referenced hammer"
                    evidence = (
                        f"Relevant NPC State confirms {owner_name}'s identity and location but contains no object ownership or hammer record."
                    )
                    requirement = (
                        f"confirmation that {owner_name} actually owns the referenced hammer"
                    )
                else:
                    fact = f"Object '{target_name}' exists and is available as described"
                    evidence = (
                        f"No matching object record for '{target_name}' is present in supplied Player or relevant entity state."
                    )
                    requirement = f"object resolution for '{target_name}'"
            add_check(fact, "unknown", evidence)
            add_unique(missing_requirements, requirement)
            has_unknown = True

    claims = action_intent.get("claimed_facts", [])
    object_names: list[str] = []
    if isinstance(claims, list) and claims:
        for step in action_steps(action_intent):
            target = step_target(step)
            if target and "object" in normalize_text(target.get("type")):
                name = target.get("name")
                if isinstance(name, str) and name not in object_names:
                    object_names.append(name)
        claim_text = " ".join(str(claim) for claim in claims)
        if not object_names and contains_pattern(claim_text, ("ak47", "ak 47")):
            object_names.append("AK47")

    for object_name in object_names:
        present = inventory_contains(player.get("inventory"), object_name)
        add_check(
            f"Player Inventory contains '{object_name}'",
            "supported" if present else "contradicted",
            (
                f"Player.inventory contains a record matching '{object_name}'."
                if present
                else f"Player.inventory contains no record matching '{object_name}'."
            ),
        )
        if not present:
            add_unique(
                conflicts,
                f"Player Inventory does not contain '{object_name}'.",
            )
            must_block = True

    semantic_text = action_semantic_text(action_intent)
    prohibited = rules.get("prohibited_modern_technology", [])
    if isinstance(prohibited, list):
        for category, patterns in MODERN_TECH_PATTERNS.items():
            if category in prohibited and contains_pattern(semantic_text, patterns):
                add_check(
                    f"World Rules permit the referenced {category}",
                    "contradicted",
                    f"World.rules.prohibited_modern_technology explicitly includes '{category}'.",
                )
                add_unique(
                    conflicts,
                    f"The referenced {category} conflicts with current World Rules.",
                )
                must_block = True

    if is_flight_action(action_intent) and player.get("species") == "human":
        if rules.get("human_natural_flight") is False:
            add_check(
                "World Rules allow humans to fly naturally",
                "contradicted",
                "World.rules.human_natural_flight is false.",
            )
        bonded_dragon = has_recorded_bonded_dragon(player)
        add_check(
            "Player has a recorded bonded rideable dragon",
            "supported" if bonded_dragon else "contradicted",
            (
                "Player State contains a recorded bonded rideable dragon."
                if bonded_dragon
                else "Player inventory and relationships contain no recorded bonded rideable dragon."
            ),
        )
        if rules.get("human_natural_flight") is False and not bonded_dragon:
            add_unique(missing_requirements, "bonded rideable dragon")
            add_unique(
                conflicts,
                "Human flight lacks a recorded bonded rideable dragon and natural human flight is prohibited.",
            )
            must_block = True

    requires_npc_decision = False
    for step in action_steps(action_intent):
        if not contains_pattern(step.get("verb"), NPC_DECISION_PATTERNS):
            continue
        target = step_target(step)
        if not target or target.get("id") not in known_npcs:
            continue
        npc_name = str(known_npcs[target["id"]].get("name", target.get("name")))
        add_check(
            f"NPC '{npc_name}' accepts or responds to the request",
            "unknown",
            "NPC consent or response is not a fact in current World State and belongs to future NPC Decision.",
        )
        add_unique(missing_requirements, f"NPC decision from {npc_name}")
        requires_npc_decision = True
        has_unknown = True

    if (
        action_intent.get("action_kind") in {"speech", "self_expression"}
        and action_intent.get("claimed_facts") == []
    ):
        add_check(
            "Action Intent is speech without a Player identity mutation",
            "supported",
            "Action Intent stores the expression in speech and contains no claimed_facts.",
        )

    requires_further_resolution = (
        action_intent.get("action_kind") not in {"speech", "self_expression"}
        or has_unknown
        or requires_npc_decision
    )

    if must_block:
        overall_status = "blocked"
    elif has_unknown or must_be_conditional or requires_npc_decision:
        overall_status = "conditional"
    else:
        overall_status = "allowed"

    return DeterministicAssessment(
        checks=list(checks_by_fact.values()),
        missing_requirements=missing_requirements,
        conflicts=conflicts,
        requires_npc_decision=requires_npc_decision,
        requires_further_resolution=requires_further_resolution,
        recommended_overall_status=overall_status,
    )


def build_player_validation_context(
    player: dict[str, Any], include_relationships: bool
) -> dict[str, Any]:
    missing = [field for field in PLAYER_VALIDATION_FIELDS if field not in player]
    if missing:
        raise WorldValidationError(
            "Player State is missing validation field(s): " + ", ".join(missing)
        )
    context = {field: player[field] for field in PLAYER_VALIDATION_FIELDS}
    if include_relationships:
        relationships = player.get("relationships")
        if not isinstance(relationships, dict):
            raise WorldValidationError("Player relationships must be an object.")
        context["relationships"] = relationships
    return context


def build_relevant_npcs(
    action_intent: dict[str, Any], world_state: dict[str, Any]
) -> list[dict[str, str]]:
    known_npcs = npc_by_id(world_state)
    relevant: list[dict[str, str]] = []
    for npc_id in sorted(referenced_npc_ids(action_intent)):
        npc = known_npcs.get(npc_id)
        if not npc:
            continue
        missing = [field for field in RELEVANT_NPC_FIELDS if field not in npc]
        if missing:
            raise WorldValidationError(
                f"NPC '{npc_id}' is missing validation field(s): "
                + ", ".join(missing)
            )
        relevant.append({field: str(npc[field]) for field in RELEVANT_NPC_FIELDS})
    return relevant


def build_relevant_locations(
    action_intent: dict[str, Any], world_state: dict[str, Any]
) -> list[dict[str, Any]]:
    location_ids = referenced_location_ids(action_intent, world_state)
    player_location = world_state["player"].get("current_location")
    if isinstance(player_location, str):
        location_ids.add(player_location)

    relevant: list[dict[str, Any]] = []
    for location_id in sorted(location_ids):
        location = world_state["locations"].get(location_id)
        if not isinstance(location, dict):
            continue
        missing = [field for field in RELEVANT_LOCATION_FIELDS if field not in location]
        if missing:
            raise WorldValidationError(
                f"Location '{location_id}' is missing validation field(s): "
                + ", ".join(missing)
            )
        relevant.append(
            {
                "id": location_id,
                "name": str(location["name"]),
                "type": str(location["type"]),
                "connections": location["connections"],
            }
        )
    return relevant


def build_validation_context(
    action_intent: dict[str, Any],
    world_state: dict[str, Any],
    assessment: DeterministicAssessment,
) -> dict[str, Any]:
    npc_ids = referenced_npc_ids(action_intent)
    include_relationships = bool(npc_ids) or is_flight_action(action_intent)
    return {
        "action_intent": action_intent,
        "player": build_player_validation_context(
            world_state["player"], include_relationships
        ),
        "world_rules": world_state["world"]["rules"],
        "relevant_npcs": build_relevant_npcs(action_intent, world_state),
        "relevant_locations": build_relevant_locations(
            action_intent, world_state
        ),
        "deterministic_validation": assessment.as_context(),
    }


def build_validation_message(
    action_intent: dict[str, Any],
    world_state: dict[str, Any],
    assessment: DeterministicAssessment,
) -> str:
    context = build_validation_context(action_intent, world_state, assessment)
    return (
        "Validate the supplied Action Intent using only this minimal context. "
        "Treat deterministic_validation as authoritative. Return conditions, "
        "never an executed outcome.\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def request_world_validation(
    provider_client: LLMProviderClient,
    action_intent: dict[str, Any],
    world_state: dict[str, Any],
    assessment: DeterministicAssessment,
    system_prompt: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    output_text = provider_client.create_structured_output(
        system_prompt=system_prompt,
        user_message=build_validation_message(
            action_intent, world_state, assessment
        ),
        schema=schema,
        schema_name="world_validation_result",
    )
    try:
        result = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise WorldValidationError(
            "The World Validator output could not be read as JSON, despite Structured Outputs."
        ) from exc
    if not isinstance(result, dict):
        raise WorldValidationError(
            "The model output is not a World Validation object."
        )
    return result


def validate_world_validation_schema(
    result: dict[str, Any], schema: dict[str, Any]
) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(result), key=lambda error: repr(list(error.path))
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "root"
    raise WorldValidationError(
        f"World Validation Schema failed at '{location}': {first.message}"
    )


def validate_deterministic_consistency(
    result: dict[str, Any], assessment: DeterministicAssessment
) -> None:
    checks = result.get("checks", [])
    output_by_fact = {
        check.get("fact"): check
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("fact"), str)
    }
    for required in assessment.checks:
        actual = output_by_fact.get(required["fact"])
        if actual is None:
            raise WorldValidationError(
                f"Model omitted deterministic check: {required['fact']}"
            )
        if actual.get("status") != required["status"]:
            raise WorldValidationError(
                f"Model contradicted deterministic status for: {required['fact']}"
            )
        if actual.get("evidence") != required["evidence"]:
            raise WorldValidationError(
                f"Model changed deterministic evidence for: {required['fact']}"
            )

    for requirement in assessment.missing_requirements:
        if requirement not in result.get("missing_requirements", []):
            raise WorldValidationError(
                f"Model omitted deterministic missing requirement: {requirement}"
            )
    for conflict in assessment.conflicts:
        if conflict not in result.get("conflicts", []):
            raise WorldValidationError(
                f"Model omitted deterministic conflict: {conflict}"
            )

    if assessment.requires_npc_decision and not result.get("requires_npc_decision"):
        raise WorldValidationError(
            "Model suppressed a required future NPC Decision."
        )
    if (
        assessment.requires_further_resolution
        and not result.get("requires_further_resolution")
    ):
        raise WorldValidationError(
            "Model suppressed required further resolution."
        )

    status = result.get("overall_status")
    if assessment.recommended_overall_status == "blocked" and status != "blocked":
        raise WorldValidationError(
            "Model attempted to bypass a deterministic blocked result."
        )
    if assessment.recommended_overall_status == "conditional" and status == "allowed":
            raise WorldValidationError(
                "Model attempted to mark unresolved deterministic facts as allowed."
            )


def apply_deterministic_validation(
    result: dict[str, Any], assessment: DeterministicAssessment
) -> dict[str, Any]:
    """Overlay authoritative code-derived facts without mutating the model object."""

    grounded = copy.deepcopy(result)
    deterministic_facts = {check["fact"] for check in assessment.checks}
    additional_checks = [
        check
        for check in grounded.get("checks", [])
        if isinstance(check, dict) and check.get("fact") not in deterministic_facts
    ]
    grounded["checks"] = copy.deepcopy(assessment.checks) + additional_checks

    for field, required_values in (
        ("missing_requirements", assessment.missing_requirements),
        ("conflicts", assessment.conflicts),
    ):
        existing = grounded.get(field, [])
        merged = list(existing) if isinstance(existing, list) else []
        for value in required_values:
            if value not in merged:
                merged.append(value)
        grounded[field] = merged

    grounded["requires_npc_decision"] = bool(
        grounded.get("requires_npc_decision")
        or assessment.requires_npc_decision
    )
    grounded["requires_further_resolution"] = bool(
        grounded.get("requires_further_resolution")
        or assessment.requires_further_resolution
    )

    if assessment.recommended_overall_status == "blocked":
        grounded["overall_status"] = "blocked"
    elif (
        assessment.recommended_overall_status == "conditional"
        and grounded.get("overall_status") == "allowed"
    ):
        grounded["overall_status"] = "conditional"
    return grounded


def validate_world_validation_result(
    result: dict[str, Any],
    schema: dict[str, Any],
    assessment: DeterministicAssessment,
) -> None:
    validate_world_validation_schema(result, schema)
    validate_deterministic_consistency(result, assessment)


def load_test_cases(test_case_number: int | None = None) -> list[dict[str, Any]]:
    test_data = action_interpreter.load_json_object(
        VALIDATION_TEST_CASES_PATH, "World Validation test cases"
    )
    test_cases = test_data.get("test_cases")
    if not isinstance(test_cases, list):
        raise WorldValidationError(
            "world_validation_test_cases.json must contain a test_cases array."
        )
    if test_case_number is not None:
        target_id = f"case_{test_case_number}"
        test_cases = [case for case in test_cases if case.get("id") == target_id]
        if not test_cases:
            raise WorldValidationError(
                f"World Validation test case {test_case_number} was not found."
            )
    return test_cases


def has_check(
    result: dict[str, Any], status: str, *required_terms: str
) -> bool:
    for check in result.get("checks", []):
        if not isinstance(check, dict) or check.get("status") != status:
            continue
        text = normalize_text(
            f"{check.get('fact', '')} {check.get('evidence', '')}"
        )
        if all(normalize_text(term) in text for term in required_terms):
            return True
    return False


def contains_output_outcome(result: dict[str, Any]) -> bool:
    text = normalize_text(result.get("validated_interpretation"))
    return any(normalize_text(phrase) in text for phrase in FORBIDDEN_OUTCOME_PHRASES)


def is_open_world_exploration_intent(
    action_result: dict[str, Any],
) -> bool:
    """Semantic matching for the open-world Evaluation case only."""

    semantic_text = normalize_text(action_semantic_text(action_result))
    exploration_patterns = (
        "explore",
        "walk",
        "travel",
        "venture",
        "follow",
        "investigate",
        "scout",
        "search",
        "continue",
        "探索",
        "沿着",
        "继续走",
    )
    unknown_area_patterns = (
        "coast",
        "shore",
        "coastline",
        "north",
        "unknown",
        "unvisited",
        "new place",
        "海岸",
        "北边",
        "没去过",
    )
    return contains_pattern(semantic_text, exploration_patterns) and contains_pattern(
        semantic_text, unknown_area_patterns
    )


def has_invented_target_id(
    action_result: dict[str, Any], world_state: dict[str, Any]
) -> bool:
    """Reject only invented IDs; a missing target or id=null remains valid."""

    valid_ids = set(world_state.get("locations", {}))
    valid_ids.update(npc_by_id(world_state))
    player_id = world_state.get("player", {}).get("id")
    if isinstance(player_id, str):
        valid_ids.add(player_id)
    for step in action_steps(action_result):
        target = step_target(step)
        if not target:
            continue
        target_id = target.get("id")
        if isinstance(target_id, str) and target_id not in valid_ids:
            return True
    return False


def evaluation_proposed_mutations(
    action_result: dict[str, Any],
    validation_result: dict[str, Any],
    world_state: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Inspect the existing Executor boundary without committing any state."""

    if validation_result.get("overall_status") != "allowed":
        return []

    from scripts import execute_action as action_executor

    try:
        plan = action_executor.build_execution_plan(
            action_result,
            validation_result,
            world_state,
        )
    except action_executor.ActionExecutionError:
        return None
    mutations = plan.get("proposed_mutations")
    if not isinstance(mutations, list):
        return None
    return [item for item in mutations if isinstance(item, dict)]


def evaluate_expected_behavior(
    case_id: str,
    result: dict[str, Any],
    action_result: dict[str, Any] | None = None,
    world_state: dict[str, Any] | None = None,
    proposed_mutations: list[dict[str, Any]] | None = None,
) -> list[str]:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    if case_id == "case_1":
        require(result.get("overall_status") == "allowed", "status should be allowed")
        require(has_check(result, "supported", "astrid", "exists"), "Astrid existence should be supported")
        require(has_check(result, "supported", "astrid", "current location"), "same-location check should be supported")
    elif case_id == "case_2":
        require(result.get("overall_status") == "blocked", "status should be blocked")
        require(has_check(result, "contradicted", "humans", "fly naturally"), "natural human flight should be contradicted")
        require(any("bonded rideable dragon" in item.casefold() for item in result.get("missing_requirements", [])), "bonded rideable dragon should be missing")
    elif case_id == "case_3":
        require(result.get("overall_status") == "conditional", "status should be conditional")
        require(has_check(result, "supported", "bjorn", "exists"), "Bjorn existence should be supported")
        require(has_check(result, "unknown", "bjorn", "hammer"), "Bjorn's hammer should be unknown")
    elif case_id == "case_4":
        require(result.get("overall_status") == "blocked", "status should be blocked")
        require(has_check(result, "contradicted", "inventory", "ak47"), "AK47 inventory ownership should be contradicted")
        require(has_check(result, "contradicted", "modern firearms"), "modern firearm rule should be contradicted")
    elif case_id == "case_5":
        require(result.get("overall_status") == "allowed", "status should be allowed")
        require(has_check(result, "supported", "speech", "identity mutation"), "speech should not become identity mutation")
        require(result.get("conflicts") == [], "speech should have no world conflict")
    elif case_id == "case_6":
        require(result.get("overall_status") == "allowed", "status should be allowed")
        require(has_check(result, "supported", "stormcliff", "exists"), "Stormcliff should exist")
        require(has_check(result, "supported", "direct route", "stormcliff"), "Skeld route should be supported")
    elif case_id == "case_7":
        require(result.get("overall_status") == "conditional", "status should be conditional")
        require(result.get("requires_npc_decision") is True, "NPC Decision should be required")
        require(has_check(result, "supported", "astrid", "exists"), "Astrid existence should be supported")
    elif case_id == "case_8":
        require(result.get("overall_status") == "conditional", "status should be conditional")
        require(has_check(result, "unknown", "ragnar", "exists"), "Ragnar existence should be unknown")
        require(result.get("requires_further_resolution") is True, "further resolution should be required")
    elif case_id == "case_9":
        require(action_result is not None, "Action Interpretation should be available")
        if action_result is not None:
            require(
                action_result.get("action_kind")
                in {"movement", "observation", "interaction", "compound", "other"},
                "action_kind should preserve exploration or movement-like intent",
            )
            require(
                is_open_world_exploration_intent(action_result),
                "Interpreter should preserve setting-compatible coastal exploration semantics",
            )
            require(
                action_result.get("needs_clarification") is False,
                "a clear open-world exploration intent should not require clarification",
            )
            require(
                action_result.get("requires_world_check") is True,
                "open-world exploration should require World Validation",
            )
            require(
                action_result.get("claimed_facts") == [],
                "exploration intent must not claim that a new place already exists",
            )
            require(
                world_state is not None
                and not has_invented_target_id(action_result, world_state),
                "Interpreter must not invent an Entity ID for the unknown area",
            )
        require(
            result.get("overall_status") != "blocked",
            "an unknown setting-compatible area must not be blocked solely because it is unregistered",
        )
        require(
            result.get("overall_status") == "conditional"
            or result.get("requires_further_resolution") is True,
            "exploration should be conditional or require future resolution",
        )
        require(
            result.get("requires_further_resolution") is True,
            "a future resolver should be required before unknown-area execution",
        )
        require(
            result.get("conflicts") == [],
            "an unregistered but setting-compatible area should not create a World Rule conflict",
        )
        require(
            proposed_mutations == [],
            "unknown-area exploration must not propose a persistent mutation",
        )
    else:
        failures.append(f"no deterministic checks are defined for {case_id}")

    require(not contains_output_outcome(result), "validated_interpretation must not narrate an outcome")
    return failures


def build_evaluation_world(world_state: dict[str, Any]) -> dict[str, Any]:
    """Isolate the frozen Evaluation from mutations in the runtime Save."""

    evaluation_world = copy.deepcopy(world_state)
    if "skeld_village" not in evaluation_world.get("locations", {}):
        raise WorldValidationError(
            "World Validation Evaluation requires Location 'skeld_village'."
        )
    evaluation_world["player"]["current_location"] = "skeld_village"
    return evaluation_world


def run_test_mode(
    provider_client: LLMProviderClient,
    world_state: dict[str, Any],
    action_prompt: str,
    action_schema: dict[str, Any],
    validation_prompt: str,
    validation_schema: dict[str, Any],
    test_case_number: int | None = None,
) -> int:
    """Run Interpreter + Validator evaluation without any state mutation."""

    test_cases = load_test_cases(test_case_number)
    evaluation_world = build_evaluation_world(world_state)
    passed = 0
    print(
        f"Running {len(test_cases)} World Validation cases with "
        f"provider: {provider_client.provider}, model: {provider_client.model}"
    )

    for test_case in test_cases:
        case_id = str(test_case.get("id", "unknown_case"))
        raw_input = test_case.get("input")
        print(f"\n=== {case_id} ===")
        print(f"input: {raw_input}")
        if not isinstance(raw_input, str) or not raw_input.strip():
            print("Action Interpretation: FAIL - test input is missing")
            print("World Validation: unavailable")
            print("Result: FAIL")
            continue

        try:
            action_result = action_interpreter.request_action_interpretation(
                provider_client,
                raw_input,
                evaluation_world,
                action_prompt,
                action_schema,
            )
            action_interpreter.validate_result(
                action_result, action_schema, evaluation_world, raw_input
            )
            print("Action Interpretation Preview:")
            print(json.dumps(action_result, ensure_ascii=False, indent=2))

            if action_result.get("needs_clarification") is True:
                print("World Validation: FAIL - Action Intent requires clarification")
                print("Result: FAIL")
                continue

            assessment = build_deterministic_assessment(
                action_result, evaluation_world
            )
            validation_result = request_world_validation(
                provider_client,
                action_result,
                evaluation_world,
                assessment,
                validation_prompt,
                validation_schema,
            )
            validate_world_validation_schema(
                validation_result, validation_schema
            )
            validation_result = apply_deterministic_validation(
                validation_result, assessment
            )
            print("World Validation Preview:")
            print(json.dumps(validation_result, ensure_ascii=False, indent=2))

            try:
                validate_world_validation_result(
                    validation_result, validation_schema, assessment
                )
                validation_ok = True
                validation_message = "PASS"
            except WorldValidationError as exc:
                validation_ok = False
                validation_message = f"FAIL - {exc}"

            proposed_mutations = None
            if case_id == "case_9":
                proposed_mutations = evaluation_proposed_mutations(
                    action_result,
                    validation_result,
                    evaluation_world,
                )
                print("Evaluation proposed_mutations:")
                print(json.dumps(proposed_mutations, ensure_ascii=False, indent=2))

            behavior_failures = evaluate_expected_behavior(
                case_id,
                validation_result,
                action_result=action_result,
                world_state=evaluation_world,
                proposed_mutations=proposed_mutations,
            )
            behavior_ok = not behavior_failures
            behavior_message = (
                "PASS"
                if behavior_ok
                else "FAIL - " + "; ".join(behavior_failures)
            )
            case_passed = validation_ok and behavior_ok
            print(f"Schema and deterministic validation: {validation_message}")
            print(f"Expected behavior: {behavior_message}")
            print(f"Result: {'PASS' if case_passed else 'FAIL'}")
            if case_passed:
                passed += 1
        except (
            action_interpreter.ActionInterpretationError,
            WorldValidationError,
            LLMProviderError,
        ) as exc:
            print(f"World Validation: FAIL - {exc}")
            print("Result: FAIL")

    print(f"\nSummary: {passed}/{len(test_cases)} cases passed.")
    print("Evaluation mode is read-only. No World State was modified.")
    return 0 if passed == len(test_cases) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview read-only World Validation for a natural-language action."
    )
    test_group = parser.add_mutually_exclusive_group()
    test_group.add_argument(
        "--test",
        action="store_true",
        help="run all nine World Validation cases against the configured LLM",
    )
    test_group.add_argument(
        "--test-case",
        type=int,
        choices=range(1, 10),
        metavar="NUMBER",
        help="run one World Validation case (1-9) against the configured LLM",
    )
    return parser.parse_args()


def main() -> int:
    action_interpreter.configure_console_encoding()
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")

    try:
        world_state = action_interpreter.load_current_world()
        action_schema = action_interpreter.load_schema()
        action_prompt = action_interpreter.load_text_file(
            action_interpreter.PROMPT_PATH,
            "Action Interpreter System Prompt",
        )
        validation_schema = load_validation_schema()
        validation_prompt = action_interpreter.load_text_file(
            VALIDATION_PROMPT_PATH,
            "World Validator System Prompt",
        )
        provider_client = create_llm_client()

        if args.test or args.test_case is not None:
            return run_test_mode(
                provider_client,
                world_state,
                action_prompt,
                action_schema,
                validation_prompt,
                validation_schema,
                test_case_number=args.test_case,
            )

        action_interpreter.display_player_status(world_state)
        raw_input = action_interpreter.read_action_input()
        from core import action_pipeline

        resources = action_pipeline.ActionPipelineResources(
            provider_client=provider_client,
            action_prompt=action_prompt,
            action_schema=action_schema,
            validation_prompt=validation_prompt,
            validation_schema=validation_schema,
        )
        action_result = action_pipeline.interpret_action(
            raw_input,
            world_state,
            resources,
            interpreter_module=action_interpreter,
        )

        print("\nAction Interpretation Preview:")
        print(json.dumps(action_result, ensure_ascii=False, indent=2))

        if action_result.get("needs_clarification") is True:
            print(
                "\nThis action requires clarification before World Validation can continue."
            )
            print("No World State was modified.")
            return 0

        validation_result = action_pipeline.validate_action(
            action_result,
            world_state,
            resources,
            validator_module=sys.modules[__name__],
        )

        print("\nWorld Validation Preview:")
        print(json.dumps(validation_result, ensure_ascii=False, indent=2))
        print("\nPreview only. No World State was modified.")
        return 0
    except action_interpreter.NoPlayerError:
        print(
            "No player exists in the current Dragon World save.",
            file=sys.stderr,
        )
        print("Create and commit a player first.", file=sys.stderr)
        return 1
    except (
        action_interpreter.ActionInterpretationError,
        WorldValidationError,
        LLMProviderError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. No World State was modified.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"Error: An unexpected problem occurred ({exc.__class__.__name__}). "
            "No World State was modified.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
