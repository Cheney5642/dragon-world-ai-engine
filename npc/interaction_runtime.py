"""Unified, read-only NPC Interaction Runtime v0.1.

The Orchestrator coordinates frozen domain modules. It does not reimplement
Knowledge, Memory, Relationship, Response, or Interaction Event rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from llm import LLMProviderClient, create_llm_client
from npc.context_builder import load_context_schema
from npc.interaction_event import (
    NpcInteractionEventError,
    build_interaction_event,
    load_interaction_event_schema,
    validate_interaction_event,
)
from npc.memory import MEMORY_STORE_PATH
from npc.memory_retriever import (
    MAX_RETRIEVAL_LIMIT,
    load_memory_recall_schema,
    validate_memory_recall_context,
)
from npc.relationship_context import (
    load_relationship_context_schema,
    validate_relationship_context,
)
from npc.relationship_store import RELATIONSHIP_STORE_PATH
from npc.response_runtime import (
    NpcInteractionUnavailableError,
    NpcResponseError,
    load_response_schema,
)
from npc.response_runtime_v0_3 import (
    load_relationship_response_prompt,
    prepare_relationship_aware_context,
    request_relationship_aware_response,
    validate_relationship_aware_response,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_RESULT_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_interaction_runtime_result.schema.json"
)


class StructuredOutputProvider(Protocol):
    """Small provider boundary shared by the real client and offline mocks."""

    def create_structured_output(
        self,
        *,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> str: ...


class NpcInteractionRuntimeError(Exception):
    """Raised when the Orchestrator cannot produce a valid unified result."""


def load_interaction_runtime_result_schema(
    path: Path = RUNTIME_RESULT_SCHEMA_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise NpcInteractionRuntimeError(
            f"NPC Interaction Runtime Result Schema does not exist: {path}"
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcInteractionRuntimeError(
            f"NPC Interaction Runtime Result Schema is not valid JSON: {path}"
        ) from exc
    if not isinstance(schema, dict):
        raise NpcInteractionRuntimeError(
            "NPC Interaction Runtime Result Schema must be a JSON object."
        )
    return schema


def _result_schema_registry() -> Registry:
    referenced_schemas = (
        load_context_schema(),
        load_memory_recall_schema(),
        load_relationship_context_schema(),
        load_response_schema(),
        load_interaction_event_schema(),
    )
    registry = Registry()
    for schema in referenced_schemas:
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )
    return registry


def validate_interaction_runtime_result(
    result: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_interaction_runtime_result_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            registry=_result_schema_registry(),
        ).validate(result)
    except (SchemaError, ValidationError, Unresolvable) as exc:
        message = getattr(exc, "message", str(exc))
        raise NpcInteractionRuntimeError(
            f"NPC Interaction Runtime Result failed Schema validation: {message}"
        ) from exc

    if result["interaction_available"] is False:
        return

    npc_context = result["npc_context"]
    recall_context = result["memory_recall_context"]
    relationship_context = result["relationship_context"]
    response = result["npc_response"]
    event = result["interaction_event"]

    # Frozen validators remain the authority for each referenced domain.
    validate_memory_recall_context(recall_context)
    validate_relationship_context(relationship_context)
    validate_relationship_aware_response(
        response,
        load_response_schema(),
        npc_context,
        recall_context,
        relationship_context,
    )
    validate_interaction_event(event)

    if result["npc_id"] != npc_context["npc"]["id"]:
        raise NpcInteractionRuntimeError("Runtime Result NPC identity is inconsistent.")
    if result["player_id"] != npc_context["player"]["id"]:
        raise NpcInteractionRuntimeError(
            "Runtime Result Player identity is inconsistent."
        )
    if event["npc_id"] != result["npc_id"] or event["player_id"] != result["player_id"]:
        raise NpcInteractionRuntimeError(
            "Interaction Event identity does not match Runtime Result."
        )
    if result["memory_candidate"] != event["memory_candidate"]:
        raise NpcInteractionRuntimeError(
            "memory_candidate must be derived from Interaction Event."
        )
    if result["relationship_signal"] != event["relationship_signal"]:
        raise NpcInteractionRuntimeError(
            "relationship_signal must be derived from Interaction Event."
        )


def _unavailable_result(
    npc_id: str,
    player_id: str,
    reason: str,
    result_schema: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "npc_id": npc_id,
        "player_id": player_id,
        "interaction_available": False,
        "unavailable_reason": reason,
        "npc_context": None,
        "memory_recall_context": None,
        "relationship_context": None,
        "npc_response": None,
        "interaction_event": None,
        "memory_candidate": False,
        "relationship_signal": "none",
    }
    validate_interaction_runtime_result(result, result_schema)
    return result


def run_npc_interaction(
    npc_id: str,
    player_id: str,
    player_utterance: str,
    world_state: dict[str, Any],
    *,
    limit: int = MAX_RETRIEVAL_LIMIT,
    memory_store_path: Path = MEMORY_STORE_PATH,
    memory_store_document: dict[str, Any] | None = None,
    relationship_store_path: Path = RELATIONSHIP_STORE_PATH,
    relationship_store_document: dict[str, Any] | None = None,
    provider_client: StructuredOutputProvider | LLMProviderClient | None = None,
    system_prompt: str | None = None,
    response_schema: dict[str, Any] | None = None,
    event_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one complete NPC Response + Interaction Event pipeline, read-only."""

    result_schema = result_schema or load_interaction_runtime_result_schema()
    try:
        npc_context, recall_context, relationship_context = (
            prepare_relationship_aware_context(
                npc_id,
                player_utterance,
                world_state,
                player_id,
                limit=limit,
                memory_store_path=memory_store_path,
                memory_store_document=memory_store_document,
                relationship_store_path=relationship_store_path,
                relationship_store_document=relationship_store_document,
            )
        )
    except NpcInteractionUnavailableError as exc:
        # The frozen v0.3 precondition guard runs before provider creation/call.
        return _unavailable_result(npc_id, player_id, str(exc), result_schema)

    response_schema = response_schema or load_response_schema()
    event_schema = event_schema or load_interaction_event_schema()
    system_prompt = system_prompt or load_relationship_response_prompt()
    provider_client = provider_client or create_llm_client()

    try:
        response = request_relationship_aware_response(
            provider_client,  # type: ignore[arg-type]
            npc_context,
            recall_context,
            relationship_context,
            player_utterance.strip(),
            system_prompt,
            response_schema,
        )
        validate_relationship_aware_response(
            response,
            response_schema,
            npc_context,
            recall_context,
            relationship_context,
        )
        event = build_interaction_event(
            npc_context,
            player_utterance.strip(),
            response,
            event_schema=event_schema,
        )
    except (NpcResponseError, NpcInteractionEventError) as exc:
        raise NpcInteractionRuntimeError(
            f"Unified NPC Interaction failed: {exc}"
        ) from exc

    result = {
        "npc_id": npc_id,
        "player_id": player_id,
        "interaction_available": True,
        "unavailable_reason": None,
        "npc_context": npc_context,
        "memory_recall_context": recall_context,
        "relationship_context": relationship_context,
        "npc_response": response,
        "interaction_event": event,
        "memory_candidate": event["memory_candidate"],
        "relationship_signal": event["relationship_signal"],
    }
    validate_interaction_runtime_result(result, result_schema)
    return result
