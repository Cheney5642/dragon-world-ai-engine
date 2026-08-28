"""Read-only Relationship Context loader for NPC Response Runtime v0.3."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from npc.relationship_store import (
    RELATIONSHIP_STORE_PATH,
    RelationshipStoreError,
    load_relationship_store,
    resolve_current_relationship,
    validate_relationship_store,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELATIONSHIP_CONTEXT_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_relationship_context.schema.json"
)


class NpcRelationshipContextError(Exception):
    """Raised when a safe Relationship Context cannot be produced."""


def load_relationship_context_schema(
    path: Path = RELATIONSHIP_CONTEXT_SCHEMA_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise NpcRelationshipContextError(
            f"NPC Relationship Context Schema does not exist: {path}"
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcRelationshipContextError(
            f"NPC Relationship Context Schema is not valid JSON: {path}"
        ) from exc
    if not isinstance(schema, dict):
        raise NpcRelationshipContextError(
            "NPC Relationship Context Schema must be a JSON object."
        )
    return schema


def validate_relationship_context(
    relationship_context: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_relationship_context_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(relationship_context)
    except (SchemaError, ValidationError) as exc:
        raise NpcRelationshipContextError(
            "NPC Relationship Context failed JSON Schema validation: "
            f"{exc.message}"
        ) from exc


def build_relationship_context(
    npc_id: str,
    player_id: str,
    relationship_store: dict[str, Any] | None = None,
    *,
    store_path: Path = RELATIONSHIP_STORE_PATH,
    context_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one exact NPC/Player pair without writing a default record."""

    if not isinstance(npc_id, str) or not npc_id.startswith("npc_"):
        raise NpcRelationshipContextError("npc_id must be a valid NPC Entity ID.")
    if not isinstance(player_id, str) or not player_id:
        raise NpcRelationshipContextError("player_id must be a non-empty string.")

    try:
        if relationship_store is None:
            store = load_relationship_store(store_path)
        else:
            store = copy.deepcopy(relationship_store)
            validate_relationship_store(store)
        relationship, persisted = resolve_current_relationship(
            store,
            npc_id,
            player_id,
        )
    except RelationshipStoreError as exc:
        raise NpcRelationshipContextError(
            f"NPC Relationship Store could not be resolved: {exc}"
        ) from exc

    context = {
        **copy.deepcopy(relationship),
        "relationship_exists": persisted,
    }
    validate_relationship_context(context, context_schema)
    return context
