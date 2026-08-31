"""FastAPI-only adapter for the Frozen NPC Runtime and Mutation Bridge."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from llm import LLMProviderClient, LLMProviderError
from npc.interaction_event import (
    NpcInteractionEventError,
    load_interaction_event_schema,
    validate_interaction_event,
)
from npc.interaction_runtime import (
    NpcInteractionRuntimeError,
    StructuredOutputProvider,
    run_npc_interaction,
)
from npc.memory import (
    MEMORY_STORE_PATH,
    DuplicateMemoryError,
    MemoryStoreError,
    NpcMemoryError,
    load_memory_schema,
)
from npc.mutation_bridge import (
    MutationUnavailableError,
    NpcMutationBridgeError,
    commit_npc_mutation_plan,
    load_npc_mutation_plan_schema,
    prepare_npc_mutation_plan,
)
from npc.relationship import (
    load_relationship_change_schema,
    load_relationship_schema,
)
from npc.relationship_store import (
    RELATIONSHIP_STORE_PATH,
    DuplicateRelationshipEventError,
    NpcRelationshipPersistenceError,
    RelationshipStoreError,
)
from npc.response_runtime import NpcResponseError, load_response_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NPC_API_RESPONSE_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_interaction_api_response.schema.json"
)


class NpcInteractRequest(BaseModel):
    """Untrusted dialogue input; no mutation data is accepted."""

    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1, pattern=r"^npc_[a-z0-9_]+$")
    player_id: str = Field(min_length=1)
    utterance: str = Field(min_length=1)


class NpcCommitRequest(BaseModel):
    """A Frozen Interaction Event is revalidated; records and values are forbidden."""

    model_config = ConfigDict(extra="forbid")

    interaction_event: dict[str, Any]


class NpcInteractionApiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_available: bool
    unavailable_reason: str | None
    npc_response: dict[str, Any] | None
    interaction_event: dict[str, Any] | None
    mutation_plan: dict[str, Any] | None


class NpcCommitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    domain: Literal["memory", "relationship"]
    committed: bool
    record: dict[str, Any]
    cross_store_transaction: bool


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise NpcInteractionRuntimeError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcInteractionRuntimeError(
            f"{label} is not valid readable JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise NpcInteractionRuntimeError(f"{label} must contain a JSON object.")
    return value


def load_npc_api_response_schema(
    path: Path = NPC_API_RESPONSE_SCHEMA_PATH,
) -> dict[str, Any]:
    return _load_json_object(path, "NPC Interaction API Response Schema")


def _api_response_registry() -> Registry:
    schemas = (
        load_response_schema(),
        load_interaction_event_schema(),
        load_npc_mutation_plan_schema(),
        load_memory_schema(),
        load_relationship_change_schema(),
        load_relationship_schema(),
    )
    registry = Registry()
    for schema in schemas:
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )
    return registry


def validate_npc_api_response(
    response: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_npc_api_response_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            registry=_api_response_registry(),
        ).validate(response)
    except (SchemaError, ValidationError, Unresolvable) as exc:
        message = getattr(exc, "message", str(exc))
        raise NpcInteractionRuntimeError(
            f"NPC API Response failed Schema validation: {message}"
        ) from exc


def _error_detail(kind: str, code: str, message: str) -> dict[str, str]:
    return {"error_type": kind, "code": code, "message": message}


def _business_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_error_detail("business_rejection", code, message),
    )


def _system_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_error_detail("system_error", code, message),
    )


def _validate_entity_ids(
    world_state: dict[str, Any],
    npc_id: str,
    player_id: str,
) -> None:
    player = world_state.get("player")
    if not isinstance(player, dict) or player.get("id") != player_id:
        raise _business_error(404, "invalid_player", "Player does not exist.")

    npcs = world_state.get("npcs")
    known_npc_ids = {
        npc.get("id")
        for npc in npcs.values()
        if isinstance(npcs, dict) and isinstance(npc, dict)
    } if isinstance(npcs, dict) else set()
    if npc_id not in known_npc_ids:
        raise _business_error(404, "invalid_npc", "NPC does not exist.")


def _raise_npc_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, LLMProviderError):
        raise _system_error(
            502,
            "provider_failure",
            "The configured LLM provider could not produce an NPC response.",
        ) from exc
    if isinstance(exc, (DuplicateMemoryError, DuplicateRelationshipEventError)):
        raise _business_error(
            409,
            "duplicate_event",
            "This interaction event has already been applied to this domain.",
        ) from exc
    if "already applied" in str(exc) or "already exists" in str(exc):
        raise _business_error(
            409,
            "duplicate_event",
            "This interaction event has already been applied to this domain.",
        ) from exc
    if isinstance(exc, MutationUnavailableError):
        raise _business_error(
            409,
            "no_mutation_available",
            "No approved mutation is available for this domain.",
        ) from exc
    if isinstance(exc, NpcInteractionEventError):
        raise _business_error(
            422,
            "invalid_interaction_event",
            "The supplied Interaction Event is invalid.",
        ) from exc
    if isinstance(exc, (MemoryStoreError, RelationshipStoreError)):
        raise _system_error(
            500,
            "persistent_store_failure",
            "An NPC persistent store is invalid or unavailable.",
        ) from exc
    if isinstance(exc, (NpcResponseError, NpcInteractionRuntimeError)):
        raise _system_error(
            502,
            "npc_runtime_failure",
            "The NPC runtime could not produce a valid grounded response.",
        ) from exc
    if isinstance(
        exc,
        (NpcMemoryError, NpcRelationshipPersistenceError, NpcMutationBridgeError),
    ):
        raise _system_error(
            500,
            "npc_mutation_failure",
            "The NPC mutation layer could not safely process this event.",
        ) from exc
    raise _system_error(
        500,
        "internal_error",
        "An internal Dragon World NPC API error occurred.",
    ) from exc


def _clean_utterance(request: NpcInteractRequest) -> str:
    if not request.utterance.strip():
        raise _business_error(400, "empty_utterance", "Utterance must not be empty.")
    return request.utterance


def register_npc_routes(
    application: FastAPI,
    *,
    load_world: Callable[[], dict[str, Any]],
    memory_store_path: Path = MEMORY_STORE_PATH,
    relationship_store_path: Path = RELATIONSHIP_STORE_PATH,
    provider_client: StructuredOutputProvider | LLMProviderClient | None = None,
) -> None:
    """Register thin HTTP adapters without copying any Frozen domain rules."""

    @application.post(
        "/api/npc/interact",
        response_model=NpcInteractionApiResponse,
    )
    def interact_with_npc(request: NpcInteractRequest) -> dict[str, Any]:
        world_state = load_world()
        _validate_entity_ids(world_state, request.npc_id, request.player_id)
        try:
            runtime_result = run_npc_interaction(
                request.npc_id,
                request.player_id,
                _clean_utterance(request),
                world_state,
                memory_store_path=memory_store_path,
                relationship_store_path=relationship_store_path,
                provider_client=provider_client,
            )
            if runtime_result["interaction_available"] is not True:
                response = {
                    "interaction_available": False,
                    "unavailable_reason": runtime_result["unavailable_reason"],
                    "npc_response": None,
                    "interaction_event": None,
                    "mutation_plan": None,
                }
            else:
                event = runtime_result["interaction_event"]
                mutation_plan = prepare_npc_mutation_plan(
                    event,
                    relationship_store_path=relationship_store_path,
                )
                response = {
                    "interaction_available": True,
                    "unavailable_reason": None,
                    "npc_response": runtime_result["npc_response"],
                    "interaction_event": event,
                    "mutation_plan": mutation_plan,
                }
            validate_npc_api_response(response)
            return response
        except Exception as exc:
            _raise_npc_http_error(exc)

    def commit_domain(
        request: NpcCommitRequest,
        domain: Literal["memory", "relationship"],
    ) -> dict[str, Any]:
        event = copy.deepcopy(request.interaction_event)
        try:
            validate_interaction_event(event)
            world_state = load_world()
            _validate_entity_ids(
                world_state,
                event["npc_id"],
                event["player_id"],
            )
            plan = prepare_npc_mutation_plan(
                event,
                relationship_store_path=relationship_store_path,
            )
            if not plan[domain]["commit_available"]:
                raise MutationUnavailableError(
                    f"No {domain.title()} mutation is available to commit."
                )
            result = commit_npc_mutation_plan(
                event,
                plan,
                commit_memory=domain == "memory",
                commit_relationship=domain == "relationship",
                memory_store_path=memory_store_path,
                relationship_store_path=relationship_store_path,
            )
            domain_result = result[domain]
            return {
                "event_id": result["event_id"],
                "domain": domain,
                "committed": domain_result["committed"],
                "record": domain_result["record"],
                "cross_store_transaction": result["cross_store_transaction"],
            }
        except Exception as exc:
            _raise_npc_http_error(exc)

    @application.post(
        "/api/npc/memory/commit",
        response_model=NpcCommitResponse,
    )
    def commit_npc_memory(request: NpcCommitRequest) -> dict[str, Any]:
        return commit_domain(request, "memory")

    @application.post(
        "/api/npc/relationship/commit",
        response_model=NpcCommitResponse,
    )
    def commit_npc_relationship(request: NpcCommitRequest) -> dict[str, Any]:
        return commit_domain(request, "relationship")
