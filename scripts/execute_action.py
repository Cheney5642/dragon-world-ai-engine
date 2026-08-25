"""Execute a narrowly allowed Dragon World action after explicit confirmation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from llm import LLMProviderError, create_llm_client
    from scripts import create_player
    from scripts import interpret_action as action_interpreter
    from scripts import validate_action as world_validator
except ImportError as exc:
    missing_package = getattr(exc, "name", "a required package")
    print(
        f"Missing dependency: {missing_package}. "
        "Run 'python -m pip install -r requirements.txt' from the project root."
    )
    raise SystemExit(1) from None

EXECUTION_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "action_execution.schema.json"
)
EXECUTION_TEST_CASES_PATH = (
    PROJECT_ROOT / "data" / "action_execution_test_cases.json"
)
SAVE_PATH = action_interpreter.SAVE_PATH
WORLD_SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
PLAYER_MUTATION_ALLOWLIST = {"current_location"}
ENCOUNTER_VERB_PATTERNS = (
    "find",
    "look for",
    "locate",
    "seek",
    "search for",
    "approach",
)
MOVEMENT_VERB_PATTERNS = (
    "go",
    "move",
    "travel",
    "walk",
    "run",
    "ride",
    "fly",
    "head",
)


class ActionExecutionError(Exception):
    """A user-facing Action Execution runtime error."""


class ExecutionEligibilityError(ActionExecutionError):
    """World Validation does not permit this action to enter execution."""


def load_execution_schema() -> dict[str, Any]:
    schema = action_interpreter.load_json_object(
        EXECUTION_SCHEMA_PATH, "Action Execution Schema"
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ActionExecutionError(
            f"action_execution.schema.json is not a valid schema: {exc.message}"
        ) from exc
    return schema


def validate_execution_schema(
    plan: dict[str, Any], schema: dict[str, Any]
) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(plan), key=lambda error: repr(list(error.path))
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "root"
    raise ActionExecutionError(
        f"Action Execution Schema failed at '{location}': {first.message}"
    )


def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(
        value.casefold().replace("-", " ").replace("_", " ").split()
    )


def contains_pattern(value: Any, patterns: tuple[str, ...]) -> bool:
    normalized = f" {normalize_text(value)} "
    return any(f" {normalize_text(pattern)} " in normalized for pattern in patterns)


def action_steps(action_intent: dict[str, Any]) -> list[dict[str, Any]]:
    steps = action_intent.get("steps", [])
    return [step for step in steps if isinstance(step, dict)]


def step_target(step: dict[str, Any]) -> dict[str, Any] | None:
    target = step.get("target")
    return target if isinstance(target, dict) else None


def known_npcs(world_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for npc in world_state["npcs"].values():
        if isinstance(npc, dict) and isinstance(npc.get("id"), str):
            result[npc["id"]] = npc
    return result


def eligibility_message(validation_result: dict[str, Any]) -> str | None:
    status = validation_result.get("overall_status")
    if status == "conditional":
        return "Action requires further resolution before execution."
    if status == "blocked":
        return "Action is blocked by current world state."
    if status == "needs_clarification":
        return "This action requires clarification before execution."
    if status != "allowed":
        return "Action has an invalid World Validation status."
    if validation_result.get("requires_npc_decision") is True:
        return "Action requires an NPC Decision before execution."
    missing = validation_result.get("missing_requirements")
    if not isinstance(missing, list) or missing:
        return "Action has unresolved requirements and cannot execute."
    conflicts = validation_result.get("conflicts")
    if not isinstance(conflicts, list) or conflicts:
        return "Action has unresolved conflicts and cannot execute."
    return None


def ensure_execution_eligible(validation_result: dict[str, Any]) -> None:
    message = eligibility_message(validation_result)
    if message:
        raise ExecutionEligibilityError(message)


def resolved_entity(
    entity_type: str, entity_id: str, name: str
) -> dict[str, str]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "name": name,
    }


def build_execution_plan(
    action_intent: dict[str, Any],
    validation_result: dict[str, Any],
    world_state: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic v0.1 plan; this function never mutates state."""

    ensure_execution_eligible(validation_result)
    player = world_state["player"]
    player_id = player.get("id")
    player_location = player.get("current_location")
    locations = world_state["locations"]
    npcs = known_npcs(world_state)

    if action_intent.get("action_kind") in {"speech", "self_expression"}:
        return {
            "execution_type": "speech",
            "can_execute": True,
            "resolved_entities": [],
            "proposed_mutations": [],
            "execution_notes": (
                "Speech is ready for future nearby NPC processing; no World State mutation is proposed."
            ),
            "requires_next_system": "nearby_npc_processing",
        }

    for step in action_steps(action_intent):
        target = step_target(step)
        if not target or target.get("id") not in npcs:
            continue
        if not contains_pattern(step.get("verb"), ENCOUNTER_VERB_PATTERNS):
            continue
        npc = npcs[target["id"]]
        if npc.get("current_location") != player_location:
            raise ActionExecutionError(
                "Encounter execution requires the Player and NPC to share the same current Location."
            )
        return {
            "execution_type": "encounter",
            "can_execute": True,
            "resolved_entities": [
                resolved_entity(
                    "npc",
                    str(npc["id"]),
                    str(npc.get("name", target.get("name"))),
                )
            ],
            "proposed_mutations": [],
            "execution_notes": (
                "The known NPC is in the Player's current Location; NPC Interaction is the next system."
            ),
            "requires_next_system": "npc_interaction",
        }

    for step in action_steps(action_intent):
        target = step_target(step)
        if not target or target.get("id") not in locations:
            continue
        is_movement = (
            action_intent.get("action_kind") == "movement"
            or contains_pattern(step.get("verb"), MOVEMENT_VERB_PATTERNS)
        )
        if not is_movement:
            continue
        location_id = str(target["id"])
        location = locations[location_id]
        mutations: list[dict[str, str]] = []
        if location_id != player_location:
            mutations.append(
                {
                    "entity_type": "player",
                    "entity_id": str(player_id),
                    "field": "current_location",
                    "old_value": str(player_location),
                    "new_value": location_id,
                }
            )
        return {
            "execution_type": "movement",
            "can_execute": True,
            "resolved_entities": [
                resolved_entity(
                    "location",
                    location_id,
                    str(location.get("name", target.get("name"))),
                )
            ],
            "proposed_mutations": mutations,
            "execution_notes": (
                "The plan proposes a Player location update after Mutation Validation and explicit confirmation."
                if mutations
                else "The Player is already in the target Location; no State Mutation is proposed."
            ),
            "requires_next_system": None,
        }

    return {
        "execution_type": "unsupported",
        "can_execute": False,
        "resolved_entities": [],
        "proposed_mutations": [],
        "execution_notes": (
            "The Action Intent is outside the deterministic execution types supported by v0.1."
        ),
        "requires_next_system": "future_action_resolver",
    }


def validate_resolved_entities(
    plan: dict[str, Any], world_state: dict[str, Any]
) -> None:
    player = world_state["player"]
    valid_by_type = {
        "player": {player.get("id")},
        "npc": set(known_npcs(world_state)),
        "location": set(world_state["locations"]),
    }
    for entity in plan.get("resolved_entities", []):
        entity_type = entity.get("entity_type")
        entity_id = entity.get("entity_id")
        if entity_id not in valid_by_type.get(entity_type, set()):
            raise ActionExecutionError(
                f"Resolved entity does not exist: {entity_type}:{entity_id}"
            )


def validate_mutation_plan(
    plan: dict[str, Any],
    validation_result: dict[str, Any],
    world_state: dict[str, Any],
) -> None:
    """Enforce the write boundary against the latest Persistent Save."""

    ensure_execution_eligible(validation_result)
    if plan.get("can_execute") is not True:
        raise ActionExecutionError(
            "This Execution Plan is outside the v0.1 execution allowlist."
        )
    validate_resolved_entities(plan, world_state)

    mutations = plan.get("proposed_mutations")
    if not isinstance(mutations, list):
        raise ActionExecutionError("proposed_mutations must be an array.")
    if len(mutations) > 1:
        raise ActionExecutionError(
            "Action Execution v0.1 permits at most one State Mutation."
        )
    if mutations and plan.get("execution_type") != "movement":
        raise ActionExecutionError(
            "Only movement plans may propose a v0.1 State Mutation."
        )

    player = world_state["player"]
    locations = world_state["locations"]
    for mutation in mutations:
        if mutation.get("entity_type") != "player":
            raise ActionExecutionError(
                "Action Execution v0.1 may mutate only Player State."
            )
        if mutation.get("entity_id") != player.get("id"):
            raise ActionExecutionError(
                "Mutation entity_id does not match the Player in the current Save."
            )
        field = mutation.get("field")
        if field not in PLAYER_MUTATION_ALLOWLIST:
            raise ActionExecutionError(
                f"Mutation field is not allowed in v0.1: {field}"
            )
        if mutation.get("old_value") != player.get(field):
            raise ActionExecutionError(
                "Mutation old_value does not match the latest Persistent Save."
            )
        new_value = mutation.get("new_value")
        if new_value not in locations:
            raise ActionExecutionError(
                f"Mutation new_value is not a valid Location ID: {new_value}"
            )

        old_location = locations.get(player.get(field))
        if not isinstance(old_location, dict):
            raise ActionExecutionError(
                "The Player's current Location is invalid in the latest Save."
            )
        connections = old_location.get("connections")
        if (
            new_value != player.get(field)
            and (
                not isinstance(connections, list)
                or new_value not in connections
            )
        ):
            raise ActionExecutionError(
                "The proposed movement is not a direct connection from the latest Player Location."
            )


def apply_execution_plan_in_memory(
    plan: dict[str, Any],
    validation_result: dict[str, Any],
    world_state: dict[str, Any],
) -> dict[str, Any]:
    validate_mutation_plan(plan, validation_result, world_state)
    updated = copy.deepcopy(world_state)
    for mutation in plan["proposed_mutations"]:
        updated["player"][mutation["field"]] = copy.deepcopy(
            mutation["new_value"]
        )
    return updated


def ensure_not_world_seed(save_path: Path) -> None:
    if save_path.resolve() == WORLD_SEED_PATH.resolve():
        raise ActionExecutionError(
            "Action Execution must never write to data/world_seed.json."
        )


def commit_execution_plan(
    plan: dict[str, Any],
    validation_result: dict[str, Any],
    save_path: Path = SAVE_PATH,
    execution_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-read, validate, and atomically commit only allowlisted mutations."""

    ensure_not_world_seed(save_path)
    schema = execution_schema or load_execution_schema()
    validate_execution_schema(plan, schema)
    latest_world = action_interpreter.load_current_world(save_path)
    updated_world = apply_execution_plan_in_memory(
        plan, validation_result, latest_world
    )
    create_player.write_save_atomically(updated_world, save_path)
    return copy.deepcopy(updated_world["player"])


def is_affirmative_confirmation(value: str) -> bool:
    return value.strip().casefold() in {"y", "yes"}


def confirm_and_commit_execution(
    plan: dict[str, Any],
    validation_result: dict[str, Any],
    save_path: Path = SAVE_PATH,
    input_fn: Callable[[str], str] = input,
    execution_schema: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ensure_not_world_seed(save_path)
    schema = execution_schema or load_execution_schema()
    validate_execution_schema(plan, schema)
    latest_world = action_interpreter.load_current_world(save_path)
    validate_mutation_plan(plan, validation_result, latest_world)
    if not plan["proposed_mutations"]:
        return copy.deepcopy(latest_world["player"])

    try:
        answer = input_fn(
            "Commit this action to the current Dragon World save? [y/N]: "
        )
    except EOFError:
        answer = ""
    if not is_affirmative_confirmation(answer):
        return None
    return commit_execution_plan(
        plan,
        validation_result,
        save_path,
        execution_schema=schema,
    )


def display_execution_plan(plan: dict[str, Any]) -> None:
    print("\nExecution Plan Preview:")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


def display_next_system(plan: dict[str, Any]) -> None:
    messages = {
        "npc_interaction": "NPC Interaction required.",
        "nearby_npc_processing": "Nearby NPC processing required.",
        "future_action_resolver": "Future Action Resolver required.",
    }
    next_system = plan.get("requires_next_system")
    print(messages.get(next_system, "No State Mutation is required."))


def display_player_summary(
    player: dict[str, Any], world_state: dict[str, Any]
) -> None:
    location_id = player.get("current_location")
    location = world_state["locations"].get(location_id, {})
    location_name = (
        location.get("name", location_id)
        if isinstance(location, dict)
        else location_id
    )
    print("Latest Player State:")
    print(f"Name: {player.get('name')}")
    print(f"Species: {player.get('species')}")
    print(f"Occupation: {player.get('occupation')}")
    print(f"Location: {location_name}")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_execution_test_cases(
    test_case_number: int | None = None,
) -> list[dict[str, Any]]:
    data = action_interpreter.load_json_object(
        EXECUTION_TEST_CASES_PATH, "Action Execution test cases"
    )
    cases = data.get("test_cases")
    if not isinstance(cases, list):
        raise ActionExecutionError(
            "action_execution_test_cases.json must contain a test_cases array."
        )
    if test_case_number is not None:
        target_id = f"case_{test_case_number}"
        cases = [case for case in cases if case.get("id") == target_id]
        if not cases:
            raise ActionExecutionError(
                f"Action Execution test case {test_case_number} was not found."
            )
    return cases


def fixture_target(
    target_type: str, entity_id: str | None, name: str
) -> dict[str, Any]:
    return {"type": target_type, "id": entity_id, "name": name}


def fixture_step(
    verb: str, target: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"verb": verb, "target": target, "goal": None, "method": None}


def fixture_action(
    action_kind: str,
    steps: list[dict[str, Any]],
    *,
    speech: str | None = None,
) -> dict[str, Any]:
    return {
        "raw_input": "offline execution fixture",
        "action_kind": action_kind,
        "steps": steps,
        "speech": speech,
        "claimed_facts": [],
        "requires_world_check": action_kind not in {"speech", "self_expression"},
        "needs_clarification": False,
    }


def fixture_validation(status: str = "allowed") -> dict[str, Any]:
    return {
        "overall_status": status,
        "checks": [
            {
                "fact": "Offline execution fixture preconditions",
                "status": "supported" if status == "allowed" else "unknown",
                "evidence": "Offline deterministic test fixture.",
            }
        ],
        "missing_requirements": [] if status == "allowed" else ["future resolution"],
        "conflicts": [],
        "requires_npc_decision": False,
        "requires_further_resolution": status != "allowed",
        "validated_interpretation": "Offline deterministic validation fixture.",
    }


def build_offline_test_world(world_state: dict[str, Any]) -> dict[str, Any]:
    fixture = copy.deepcopy(world_state)
    fixture["player"]["current_location"] = "skeld_village"
    return fixture


def evaluate_execution_case(
    case_id: str,
    world_state: dict[str, Any],
    execution_schema: dict[str, Any],
    seed_hash_before: str,
    save_hash_before: str,
) -> list[str]:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    allowed = fixture_validation("allowed")
    movement = fixture_action(
        "movement",
        [fixture_step("go", fixture_target("location", "stormcliff", "Stormcliff"))],
    )

    if case_id == "case_1":
        plan = build_execution_plan(movement, allowed, world_state)
        validate_execution_schema(plan, execution_schema)
        validate_mutation_plan(plan, allowed, world_state)
        require(plan["execution_type"] == "movement", "execution_type should be movement")
        require(len(plan["proposed_mutations"]) == 1, "movement should propose one mutation")
        mutation = plan["proposed_mutations"][0]
        require(mutation["field"] == "current_location", "only current_location may change")
        require(mutation["old_value"] == "skeld_village", "old location should be Skeld")
        require(mutation["new_value"] == "stormcliff", "new location should be Stormcliff")
    elif case_id == "case_2":
        plan = build_execution_plan(movement, allowed, world_state)
        updated = apply_execution_plan_in_memory(plan, allowed, world_state)
        require(updated["player"]["current_location"] == "stormcliff", "in-memory Player location should update")
        for section in ("world", "locations", "npcs", "global_state"):
            require(updated[section] == world_state[section], f"{section} must not change")
    elif case_id == "case_3":
        require(not is_affirmative_confirmation(""), "empty input must cancel")
        require(not is_affirmative_confirmation("n"), "n must cancel")
        require(not is_affirmative_confirmation("anything"), "other input must cancel")
    elif case_id == "case_4":
        try:
            build_execution_plan(movement, fixture_validation("blocked"), world_state)
        except ExecutionEligibilityError:
            pass
        else:
            failures.append("blocked action entered Executor")
    elif case_id == "case_5":
        try:
            build_execution_plan(movement, fixture_validation("conditional"), world_state)
        except ExecutionEligibilityError:
            pass
        else:
            failures.append("conditional action entered Executor")
    elif case_id == "case_6":
        encounter = fixture_action(
            "interaction",
            [fixture_step("go find", fixture_target("npc", "npc_astrid", "Astrid"))],
        )
        plan = build_execution_plan(encounter, allowed, world_state)
        validate_execution_schema(plan, execution_schema)
        validate_mutation_plan(plan, allowed, world_state)
        require(plan["execution_type"] == "encounter", "execution_type should be encounter")
        require(plan["proposed_mutations"] == [], "encounter must not mutate state")
        require(any(entity["entity_id"] == "npc_astrid" for entity in plan["resolved_entities"]), "Astrid should be resolved")
    elif case_id == "case_7":
        speech = fixture_action("speech", [fixture_step("say")], speech="我是奥丁！")
        before_player = copy.deepcopy(world_state["player"])
        plan = build_execution_plan(speech, allowed, world_state)
        validate_execution_schema(plan, execution_schema)
        updated = apply_execution_plan_in_memory(plan, allowed, world_state)
        require(plan["execution_type"] == "speech", "execution_type should be speech")
        require(plan["proposed_mutations"] == [], "speech must not mutate state")
        require(updated["player"] == before_player, "speech must not alter Player identity")
    elif case_id == "case_8":
        require(file_hash(WORLD_SEED_PATH) == seed_hash_before, "world_seed.json changed")
        require(file_hash(SAVE_PATH) == save_hash_before, "current_world.json changed")
    else:
        failures.append(f"no checks are defined for {case_id}")
    return failures


def run_execution_test_mode(
    world_state: dict[str, Any],
    execution_schema: dict[str, Any],
    test_case_number: int | None = None,
) -> int:
    """Run entirely offline and never call a provider or write a Save."""

    cases = load_execution_test_cases(test_case_number)
    fixture_world = build_offline_test_world(world_state)
    seed_before = file_hash(WORLD_SEED_PATH)
    save_before = file_hash(SAVE_PATH)
    passed = 0
    print(f"Running {len(cases)} offline Action Execution cases.")
    for case in cases:
        case_id = str(case.get("id", "unknown_case"))
        print(f"\n=== {case_id} ===")
        print(f"description: {case.get('description')}")
        try:
            failures = evaluate_execution_case(
                case_id,
                fixture_world,
                execution_schema,
                seed_before,
                save_before,
            )
            if failures:
                print("Result: FAIL - " + "; ".join(failures))
            else:
                print("Result: PASS")
                passed += 1
        except ActionExecutionError as exc:
            print(f"Result: FAIL - {exc}")

    if file_hash(WORLD_SEED_PATH) != seed_before or file_hash(SAVE_PATH) != save_before:
        raise ActionExecutionError(
            "Read-only Evaluation detected an unexpected persistent file change."
        )
    print(f"\nSummary: {passed}/{len(cases)} cases passed.")
    print("Evaluation mode is offline and read-only. No World State was modified.")
    return 0 if passed == len(cases) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely execute a validated Dragon World action."
    )
    test_group = parser.add_mutually_exclusive_group()
    test_group.add_argument(
        "--test",
        action="store_true",
        help="run all eight offline Action Execution cases",
    )
    test_group.add_argument(
        "--test-case",
        type=int,
        choices=range(1, 9),
        metavar="NUMBER",
        help="run one offline Action Execution case (1-8)",
    )
    return parser.parse_args()


def main() -> int:
    action_interpreter.configure_console_encoding()
    args = parse_args()

    try:
        world_state = action_interpreter.load_current_world()
        execution_schema = load_execution_schema()

        if args.test or args.test_case is not None:
            return run_execution_test_mode(
                world_state,
                execution_schema,
                test_case_number=args.test_case,
            )

        load_dotenv(PROJECT_ROOT / ".env")
        action_schema = action_interpreter.load_schema()
        action_prompt = action_interpreter.load_text_file(
            action_interpreter.PROMPT_PATH,
            "Action Interpreter System Prompt",
        )
        validation_schema = world_validator.load_validation_schema()
        validation_prompt = action_interpreter.load_text_file(
            world_validator.VALIDATION_PROMPT_PATH,
            "World Validator System Prompt",
        )
        provider_client = create_llm_client()

        action_interpreter.display_player_status(world_state)
        raw_input = action_interpreter.read_action_input()
        from core import action_pipeline

        resources = action_pipeline.ActionPipelineResources(
            provider_client=provider_client,
            action_prompt=action_prompt,
            action_schema=action_schema,
            validation_prompt=validation_prompt,
            validation_schema=validation_schema,
            execution_schema=execution_schema,
        )
        preview = action_pipeline.preview_action(
            raw_input,
            world_state,
            resources,
            interpreter_module=action_interpreter,
            validator_module=world_validator,
            executor_module=sys.modules[__name__],
        )
        action_result = preview["interpretation"]
        print("\nAction Interpretation Preview:")
        print(json.dumps(action_result, ensure_ascii=False, indent=2))

        if action_result.get("needs_clarification") is True:
            print("\nThis action requires clarification before execution.")
            print("Save was not modified.")
            return 0

        validation_result = preview["validation"]
        if not isinstance(validation_result, dict):
            raise ActionExecutionError(
                "World Validation did not return a structured result."
            )
        print("\nWorld Validation Preview:")
        print(json.dumps(validation_result, ensure_ascii=False, indent=2))

        message = eligibility_message(validation_result)
        if message:
            print(f"\n{message}")
            print("Save was not modified.")
            return 0

        plan = preview["execution_plan"]
        if not isinstance(plan, dict):
            raise ActionExecutionError(
                "Action Execution did not return a structured plan."
            )
        display_execution_plan(plan)

        if plan.get("can_execute") is not True:
            display_next_system(plan)
            print("Save was not modified.")
            return 0

        if not plan["proposed_mutations"]:
            display_next_system(plan)
            print("No World State Mutation was required.")
            return 0

        committed_player = action_pipeline.confirm_and_commit_execution(
            plan,
            validation_result,
            resources,
            save_path=SAVE_PATH,
            executor_module=sys.modules[__name__],
        )
        if committed_player is None:
            print("Action execution cancelled. Save was not modified.")
            return 0

        latest_world = action_interpreter.load_current_world()
        print("Action committed to Dragon World.")
        display_player_summary(committed_player, latest_world)
        print("Persistent save:")
        print("data/saves/current_world.json")
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
        world_validator.WorldValidationError,
        ActionExecutionError,
        LLMProviderError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Save was not modified.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"Error: An unexpected problem occurred ({exc.__class__.__name__}). "
            "Save was not modified.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
