"""D2-B: interpret player language without resolving or mutating the world."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from llm import LLMProviderClient, create_llm_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = PROJECT_ROOT / "prompts" / "free_action_interpreter_system.md"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "free_action_interpretation.schema.json"


class ActionInterpretationError(Exception):
    """An input or model output cannot satisfy the D2 action contract."""


def load_action_schema() -> dict[str, Any]:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ActionInterpretationError("Action Schema must be an object.")
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise ActionInterpretationError("Action Schema could not be loaded.") from exc
    return schema


def validate_action_interpretation(result: Any) -> None:
    """Fail closed; never repair, coerce or resolve a candidate action."""

    try:
        Draft202012Validator(load_action_schema()).validate(result)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "root"
        # Do not include raw player/model content in the public error.
        raise ActionInterpretationError(
            f"Invalid action output at {location}: {exc.validator} validation failed."
        ) from exc
    for field in ("action", "target", "destination", "direction", "intent", "method"):
        if isinstance(result[field], str) and not result[field].strip():
            raise ActionInterpretationError(f"Action field {field} must not be blank.")
    goal = result["explicit_goal"]
    if goal is not None and not goal["goal"].strip():
        raise ActionInterpretationError("Explicit goal must not be blank.")
    if result["destination"] is not None and result["direction"] is not None:
        raise ActionInterpretationError("Destination and direction are mutually exclusive.")


def interpret_action(
    player_input: str,
    *,
    provider_client: LLMProviderClient | None = None,
) -> dict[str, Any]:
    """Return unverified intent, using only text and shared LLM infrastructure.

    The explicit D2-B flat contract supersedes the steps-based D2-A sketch for
    this new interpreter. The frozen Step 5 interpreter remains unchanged.
    No database, world registry, Identity logic or execution path is consulted.
    """

    if not isinstance(player_input, str) or not player_input.strip():
        raise ActionInterpretationError("Player input must be a non-empty string.")
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ActionInterpretationError("Action Prompt could not be read.") from exc
    if not prompt:
        raise ActionInterpretationError("Action Prompt must not be empty.")
    schema = load_action_schema()
    client = provider_client if provider_client is not None else create_llm_client()
    output = client.create_structured_output(
        system_prompt=prompt,
        user_message=json.dumps({"player_input": player_input}, ensure_ascii=False),
        schema=schema,
        schema_name="free_action_interpretation",
    )
    if not isinstance(output, str):
        raise ActionInterpretationError("Model output must be JSON text.")
    try:
        result = json.loads(output)
    except ValueError as exc:
        raise ActionInterpretationError("Model output is not valid JSON.") from exc
    validate_action_interpretation(result)
    return result
