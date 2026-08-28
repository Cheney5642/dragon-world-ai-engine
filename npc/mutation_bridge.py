"""Unified NPC Mutation Bridge v0.1.

The Bridge coordinates frozen Memory and Relationship persistence APIs. It
does not parse dialogue, call an LLM, or provide a cross-store transaction.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from npc.interaction_event import (
    NpcInteractionEventError,
    validate_interaction_event,
)
from npc.memory import (
    MEMORY_STORE_PATH,
    NpcMemoryError,
    build_memory_preview,
    commit_memory_preview,
    load_memory_schema,
    validate_memory_record,
)
from npc.relationship import (
    NpcRelationshipError,
    load_relationship_change_schema,
    load_relationship_schema,
    validate_relationship_change,
)
from npc.relationship_store import (
    RELATIONSHIP_STORE_PATH,
    NpcRelationshipPersistenceError,
    build_persistent_relationship_preview,
    commit_relationship_event,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MUTATION_PLAN_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_interaction_mutation_plan.schema.json"
)


class NpcMutationBridgeError(Exception):
    """Raised when a safe Mutation Plan cannot be prepared or committed."""


class MutationUnavailableError(NpcMutationBridgeError):
    """Raised when a requested domain has no commit-capable Preview."""


def load_npc_mutation_plan_schema(
    path: Path = MUTATION_PLAN_SCHEMA_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise NpcMutationBridgeError(
            f"NPC Interaction Mutation Plan Schema does not exist: {path}"
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcMutationBridgeError(
            f"NPC Interaction Mutation Plan Schema is not valid JSON: {path}"
        ) from exc
    if not isinstance(schema, dict):
        raise NpcMutationBridgeError(
            "NPC Interaction Mutation Plan Schema must be a JSON object."
        )
    return schema


def _plan_schema_registry() -> Registry:
    schemas = (
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


def validate_npc_mutation_plan(
    plan: dict[str, Any],
    interaction_event: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_npc_mutation_plan_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            registry=_plan_schema_registry(),
        ).validate(plan)
    except (SchemaError, ValidationError, Unresolvable) as exc:
        message = getattr(exc, "message", str(exc))
        raise NpcMutationBridgeError(
            f"NPC Interaction Mutation Plan failed Schema validation: {message}"
        ) from exc

    memory = plan["memory"]
    relationship = plan["relationship"]
    if memory["preview"] is not None:
        validate_memory_record(memory["preview"])
        if memory["preview"]["source_event_id"] != plan["event_id"]:
            raise NpcMutationBridgeError(
                "Memory Preview source_event_id does not match Mutation Plan."
            )
    if relationship["preview"] is not None:
        validate_relationship_change(relationship["preview"])
        if relationship["preview"]["source_event_id"] != plan["event_id"]:
            raise NpcMutationBridgeError(
                "Relationship Preview source_event_id does not match Mutation Plan."
            )
        expected_available = relationship["preview"]["decision"] == "change_proposed"
        if relationship["commit_available"] is not expected_available:
            raise NpcMutationBridgeError(
                "Relationship commit availability does not match its Preview decision."
            )

    expected_any = memory["commit_available"] or relationship["commit_available"]
    if plan["has_any_mutation"] is not expected_any:
        raise NpcMutationBridgeError(
            "has_any_mutation must be derived from domain commit availability."
        )

    if interaction_event is None:
        return
    try:
        validate_interaction_event(interaction_event)
    except NpcInteractionEventError as exc:
        raise NpcMutationBridgeError(
            f"Mutation Plan source Interaction Event is invalid: {exc}"
        ) from exc
    for plan_field, event_field in (
        ("event_id", "event_id"),
        ("npc_id", "npc_id"),
        ("player_id", "player_id"),
    ):
        if plan[plan_field] != interaction_event[event_field]:
            raise NpcMutationBridgeError(
                f"Mutation Plan {plan_field} does not match Interaction Event."
            )
    if memory["candidate"] is not interaction_event["memory_candidate"]:
        raise NpcMutationBridgeError(
            "Memory candidate must be derived from Interaction Event."
        )
    if relationship["signal"] != interaction_event["relationship_signal"]:
        raise NpcMutationBridgeError(
            "Relationship signal must be derived from Interaction Event."
        )


def prepare_npc_mutation_plan(
    interaction_event: dict[str, Any],
    *,
    relationship_store_path: Path = RELATIONSHIP_STORE_PATH,
    relationship_store_document: dict[str, Any] | None = None,
    plan_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build both independent domain Previews without writing either Store."""

    try:
        validate_interaction_event(interaction_event)
    except NpcInteractionEventError as exc:
        raise NpcMutationBridgeError(
            f"Mutation Bridge requires a validated Interaction Event: {exc}"
        ) from exc

    memory_candidate = interaction_event["memory_candidate"]
    memory_preview = None
    if memory_candidate:
        try:
            memory_preview = build_memory_preview(interaction_event)
        except NpcMemoryError as exc:
            raise NpcMutationBridgeError(
                f"Memory Preview could not be prepared: {exc}"
            ) from exc

    relationship_signal = interaction_event["relationship_signal"]
    relationship_preview = None
    relationship_commit_available = False
    if relationship_signal != "none":
        try:
            relationship_preview = build_persistent_relationship_preview(
                interaction_event,
                relationship_store_path,
                store_document=relationship_store_document,
            )
        except NpcRelationshipPersistenceError as exc:
            raise NpcMutationBridgeError(
                f"Relationship Preview could not be prepared: {exc}"
            ) from exc
        relationship_commit_available = (
            relationship_preview["decision"] == "change_proposed"
        )

    plan = {
        "event_id": interaction_event["event_id"],
        "npc_id": interaction_event["npc_id"],
        "player_id": interaction_event["player_id"],
        "memory": {
            "candidate": memory_candidate,
            "preview": memory_preview,
            "commit_available": memory_candidate,
        },
        "relationship": {
            "signal": relationship_signal,
            "preview": relationship_preview,
            "commit_available": relationship_commit_available,
        },
        "has_any_mutation": memory_candidate or relationship_commit_available,
    }
    validate_npc_mutation_plan(plan, interaction_event, plan_schema)
    return plan


def commit_npc_mutation_plan(
    interaction_event: dict[str, Any],
    mutation_plan: dict[str, Any],
    *,
    commit_memory: bool,
    commit_relationship: bool,
    memory_store_path: Path = MEMORY_STORE_PATH,
    relationship_store_path: Path = RELATIONSHIP_STORE_PATH,
) -> dict[str, Any]:
    """Commit independently confirmed domains through their frozen safe paths.

    Each JSON Store commit is atomic on its own. This function intentionally
    provides no cross-store rollback or global transaction.
    """

    if not isinstance(commit_memory, bool) or not isinstance(commit_relationship, bool):
        raise NpcMutationBridgeError("Commit selections must be booleans.")
    validate_npc_mutation_plan(mutation_plan, interaction_event)

    if commit_memory and not mutation_plan["memory"]["commit_available"]:
        raise MutationUnavailableError("No Memory mutation is available to commit.")
    if commit_relationship and not mutation_plan["relationship"]["commit_available"]:
        raise MutationUnavailableError(
            "No Relationship mutation is available to commit."
        )

    result = {
        "event_id": interaction_event["event_id"],
        "memory": {
            "requested": commit_memory,
            "committed": False,
            "record": None,
        },
        "relationship": {
            "requested": commit_relationship,
            "committed": False,
            "record": None,
        },
        "cross_store_transaction": False,
    }

    # Independent domain commits deliberately preserve the existing order and
    # failure semantics. A later failure cannot roll back an earlier Store.
    if commit_memory:
        memory_record = commit_memory_preview(
            copy.deepcopy(mutation_plan["memory"]["preview"]),
            memory_store_path,
        )
        result["memory"] = {
            "requested": True,
            "committed": True,
            "record": memory_record,
        }

    if commit_relationship:
        relationship_record, _ = commit_relationship_event(
            interaction_event,
            copy.deepcopy(mutation_plan["relationship"]["preview"]),
            relationship_store_path,
        )
        result["relationship"] = {
            "requested": True,
            "committed": True,
            "record": relationship_record,
        }

    return result
