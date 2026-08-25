"""Shared orchestration for Dragon World action interpretation and execution.

The frozen Interpreter, Validator, and Executor modules remain the owners of
their business rules. This module composes those same functions so CLI entry
points and HTTP endpoints cannot drift into separate implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from dotenv import load_dotenv

from llm import LLMProviderClient, create_llm_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ActionPipelineResources:
    """Validated prompts, schemas, and the configured provider client."""

    provider_client: LLMProviderClient
    action_prompt: str
    action_schema: dict[str, Any]
    validation_prompt: str | None = None
    validation_schema: dict[str, Any] = field(default_factory=dict)
    execution_schema: dict[str, Any] = field(default_factory=dict)


def _default_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    from scripts import execute_action
    from scripts import interpret_action
    from scripts import validate_action

    return interpret_action, validate_action, execute_action


def load_pipeline_resources(
    *,
    interpreter_module: ModuleType | None = None,
    validator_module: ModuleType | None = None,
    executor_module: ModuleType | None = None,
) -> ActionPipelineResources:
    """Load the exact frozen resources used by both CLI and Web API."""

    if (
        interpreter_module is None
        or validator_module is None
        or executor_module is None
    ):
        defaults = _default_modules()
        interpreter_module = interpreter_module or defaults[0]
        validator_module = validator_module or defaults[1]
        executor_module = executor_module or defaults[2]

    load_dotenv(PROJECT_ROOT / ".env")
    return ActionPipelineResources(
        provider_client=create_llm_client(),
        action_prompt=interpreter_module.load_text_file(
            interpreter_module.PROMPT_PATH,
            "Action Interpreter System Prompt",
        ),
        action_schema=interpreter_module.load_schema(),
        validation_prompt=interpreter_module.load_text_file(
            validator_module.VALIDATION_PROMPT_PATH,
            "World Validator System Prompt",
        ),
        validation_schema=validator_module.load_validation_schema(),
        execution_schema=executor_module.load_execution_schema(),
    )


def interpret_action(
    raw_input: str,
    world_state: dict[str, Any],
    resources: ActionPipelineResources,
    *,
    interpreter_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Interpret intent and apply the frozen schema/entity validation."""

    if interpreter_module is None:
        interpreter_module = _default_modules()[0]
    result = interpreter_module.request_action_interpretation(
        resources.provider_client,
        raw_input,
        world_state,
        resources.action_prompt,
        resources.action_schema,
    )
    interpreter_module.validate_result(
        result,
        resources.action_schema,
        world_state,
        raw_input,
    )
    return result


def validate_action(
    action_intent: dict[str, Any],
    world_state: dict[str, Any],
    resources: ActionPipelineResources,
    *,
    validator_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Run LLM validation and overlay authoritative deterministic checks."""

    if validator_module is None:
        validator_module = _default_modules()[1]
    if not resources.validation_prompt or not resources.validation_schema:
        raise RuntimeError("World Validation resources were not loaded.")
    assessment = validator_module.build_deterministic_assessment(
        action_intent,
        world_state,
    )
    result = validator_module.request_world_validation(
        resources.provider_client,
        action_intent,
        world_state,
        assessment,
        resources.validation_prompt,
        resources.validation_schema,
    )
    validator_module.validate_world_validation_schema(
        result,
        resources.validation_schema,
    )
    result = validator_module.apply_deterministic_validation(result, assessment)
    validator_module.validate_world_validation_result(
        result,
        resources.validation_schema,
        assessment,
    )
    return result


def build_execution_plan(
    action_intent: dict[str, Any],
    validation_result: dict[str, Any],
    world_state: dict[str, Any],
    resources: ActionPipelineResources,
    *,
    executor_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Build and locally validate a read-only execution plan preview."""

    if executor_module is None:
        executor_module = _default_modules()[2]
    if not resources.execution_schema:
        raise RuntimeError("Action Execution Schema was not loaded.")
    plan = executor_module.build_execution_plan(
        action_intent,
        validation_result,
        world_state,
    )
    executor_module.validate_execution_schema(plan, resources.execution_schema)
    if plan.get("can_execute") is True:
        executor_module.validate_mutation_plan(
            plan,
            validation_result,
            world_state,
        )
    return plan


def preview_action(
    raw_input: str,
    world_state: dict[str, Any],
    resources: ActionPipelineResources,
    *,
    interpreter_module: ModuleType | None = None,
    validator_module: ModuleType | None = None,
    executor_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Run the three-layer preview without mutating Persistent World State."""

    if (
        interpreter_module is None
        or validator_module is None
        or executor_module is None
    ):
        defaults = _default_modules()
        interpreter_module = interpreter_module or defaults[0]
        validator_module = validator_module or defaults[1]
        executor_module = executor_module or defaults[2]

    interpretation = interpret_action(
        raw_input,
        world_state,
        resources,
        interpreter_module=interpreter_module,
    )
    preview: dict[str, Any] = {
        "interpretation": interpretation,
        "validation": None,
        "execution_plan": None,
        "pipeline_status": "needs_clarification",
    }
    if interpretation.get("needs_clarification") is True:
        return preview

    validation = validate_action(
        interpretation,
        world_state,
        resources,
        validator_module=validator_module,
    )
    preview["validation"] = validation

    eligibility = executor_module.eligibility_message(validation)
    if eligibility:
        preview["pipeline_status"] = str(
            validation.get("overall_status") or "not_executable"
        )
        return preview

    plan = build_execution_plan(
        interpretation,
        validation,
        world_state,
        resources,
        executor_module=executor_module,
    )
    preview["execution_plan"] = plan
    preview["pipeline_status"] = (
        "ready" if plan.get("can_execute") is True else "unsupported"
    )
    return preview


def commit_execution(
    plan: dict[str, Any],
    validation_result: dict[str, Any],
    resources: ActionPipelineResources,
    *,
    save_path: Path,
    executor_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Re-read the Save and atomically commit only an allowlisted mutation."""

    if executor_module is None:
        executor_module = _default_modules()[2]
    if not resources.execution_schema:
        raise RuntimeError("Action Execution Schema was not loaded.")
    return executor_module.commit_execution_plan(
        plan,
        validation_result,
        save_path=save_path,
        execution_schema=resources.execution_schema,
    )


def confirm_and_commit_execution(
    plan: dict[str, Any],
    validation_result: dict[str, Any],
    resources: ActionPipelineResources,
    *,
    save_path: Path,
    executor_module: ModuleType | None = None,
) -> dict[str, Any] | None:
    """Preserve the CLI confirmation gate while using the shared core."""

    if executor_module is None:
        executor_module = _default_modules()[2]
    if not resources.execution_schema:
        raise RuntimeError("Action Execution Schema was not loaded.")
    return executor_module.confirm_and_commit_execution(
        plan,
        validation_result,
        save_path=save_path,
        execution_schema=resources.execution_schema,
    )


def rerun_and_commit_action(
    raw_input: str,
    resources: ActionPipelineResources,
    *,
    save_path: Path,
    interpreter_module: ModuleType | None = None,
    validator_module: ModuleType | None = None,
    executor_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Re-run the trusted pipeline from raw input before an API commit.

    The caller never supplies proposed mutations. A POST to the commit endpoint
    is the explicit confirmation; this function still re-reads and validates
    the latest Save immediately before the atomic write.
    """

    if (
        interpreter_module is None
        or validator_module is None
        or executor_module is None
    ):
        defaults = _default_modules()
        interpreter_module = interpreter_module or defaults[0]
        validator_module = validator_module or defaults[1]
        executor_module = executor_module or defaults[2]

    world_state = interpreter_module.load_current_world(save_path)
    preview = preview_action(
        raw_input,
        world_state,
        resources,
        interpreter_module=interpreter_module,
        validator_module=validator_module,
        executor_module=executor_module,
    )
    result = {**preview, "committed": False, "player": None}
    if preview["pipeline_status"] != "ready":
        return result

    plan = preview["execution_plan"]
    validation = preview["validation"]
    if not isinstance(plan, dict) or not isinstance(validation, dict):
        return result
    if not plan.get("proposed_mutations"):
        result["pipeline_status"] = "no_mutation"
        return result

    result["player"] = commit_execution(
        plan,
        validation,
        resources,
        save_path=save_path,
        executor_module=executor_module,
    )
    result["committed"] = True
    result["pipeline_status"] = "committed"
    return result
