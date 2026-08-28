"""Persistent NPC Relationship Store v0.1 with safe, explicit commit."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from npc.interaction_event import NpcInteractionEventError, validate_interaction_event
from npc.relationship import (
    NpcRelationshipError,
    create_initial_relationship,
    evaluate_relationship_change,
    validate_relationship,
    validate_relationship_change,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELATIONSHIP_STORE_PATH = (
    PROJECT_ROOT / "data" / "saves" / "npc_relationships.json"
)
RELATIONSHIP_STORE_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_relationship_store.schema.json"
)

# Current vertical-demo policy: Astrid and the initial Player are ordinary
# acquaintances. Missing pairs otherwise start as strangers. This creates only
# an in-memory default until a real relationship mutation is committed.
DEFAULT_ACQUAINTED_PAIRS = frozenset({("npc_astrid", "player_001")})


class NpcRelationshipPersistenceError(Exception):
    """Base error for safe Relationship Store operations."""


class RelationshipStoreError(NpcRelationshipPersistenceError):
    """Raised when the Relationship Store is invalid or cannot be written."""


class NoRelationshipChangeRequiredError(NpcRelationshipPersistenceError):
    """Raised when the frozen Evaluator produces no_change."""


class DuplicateRelationshipEventError(NpcRelationshipPersistenceError):
    """Raised when one NPC/Player pair already applied the source Event."""


class StaleRelationshipPreviewError(NpcRelationshipPersistenceError):
    """Raised when Persistent State changed after the displayed Preview."""


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise RelationshipStoreError(f"{label} does not exist: {path}")
    if not path.is_file():
        raise RelationshipStoreError(f"{label} path is not a file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RelationshipStoreError(
            f"{label} is not valid readable JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise RelationshipStoreError(f"{label} must contain a JSON object: {path}")
    return value


def load_relationship_store_schema(
    path: Path = RELATIONSHIP_STORE_SCHEMA_PATH,
) -> dict[str, Any]:
    return _load_json_object(path, "NPC Relationship Store Schema")


def validate_relationship_store(
    store: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_relationship_store_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(store)
    except (SchemaError, ValidationError) as exc:
        raise RelationshipStoreError(
            f"NPC Relationship Store failed JSON Schema validation: {exc.message}"
        ) from exc

    pair_keys: set[tuple[str, str]] = set()
    for record in store["relationships"]:
        pair_key = (record["npc_id"], record["player_id"])
        if pair_key in pair_keys:
            raise RelationshipStoreError(
                "Duplicate NPC/Player relationship in Store: "
                f"{pair_key[0]} + {pair_key[1]}"
            )
        if record["last_source_event_id"] not in record["applied_event_ids"]:
            raise RelationshipStoreError(
                "last_source_event_id must appear in applied_event_ids for "
                f"{pair_key[0]} + {pair_key[1]}."
            )
        pair_keys.add(pair_key)


def load_relationship_store(
    store_path: Path = RELATIONSHIP_STORE_PATH,
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = _load_json_object(store_path, "NPC Relationship Store")
    validate_relationship_store(store, schema)
    return store


def write_relationship_store_atomically(
    store: dict[str, Any],
    store_path: Path = RELATIONSHIP_STORE_PATH,
    *,
    schema: dict[str, Any] | None = None,
) -> None:
    """Validate a temporary file before replacing only the Relationship Store."""

    schema = schema or load_relationship_store_schema()
    validate_relationship_store(store, schema)
    store_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{store_path.name}.",
            suffix=".tmp",
            dir=store_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(store, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        load_relationship_store(temporary_path, schema=schema)
        os.replace(temporary_path, store_path)
        temporary_path = None
        load_relationship_store(store_path, schema=schema)
    except (PermissionError, OSError) as exc:
        raise RelationshipStoreError(
            f"Could not safely write NPC Relationship Store: {store_path} ({exc})"
        ) from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def initialize_relationship_store(
    store_path: Path = RELATIONSHIP_STORE_PATH,
) -> dict[str, Any]:
    if store_path.exists():
        return load_relationship_store(store_path)
    empty_store = {"version": "0.1", "relationships": []}
    write_relationship_store_atomically(empty_store, store_path)
    return empty_store


def _find_record(
    store: dict[str, Any],
    npc_id: str,
    player_id: str,
) -> dict[str, Any] | None:
    matches = [
        record
        for record in store["relationships"]
        if record["npc_id"] == npc_id and record["player_id"] == player_id
    ]
    if len(matches) > 1:
        raise RelationshipStoreError(
            f"Relationship pair is not unique: {npc_id} + {player_id}"
        )
    return matches[0] if matches else None


def relationship_state_from_record(record: dict[str, Any]) -> dict[str, Any]:
    relationship = {
        "npc_id": record["npc_id"],
        "player_id": record["player_id"],
        "familiarity": record["familiarity"],
        "trust": record["trust"],
        "attitude": record["attitude"],
    }
    validate_relationship(relationship)
    return relationship


def resolve_current_relationship(
    store: dict[str, Any],
    npc_id: str,
    player_id: str,
) -> tuple[dict[str, Any], bool]:
    """Return Persistent State or a non-persisted conservative default."""

    validate_relationship_store(store)
    record = _find_record(store, npc_id, player_id)
    if record is not None:
        return relationship_state_from_record(record), True
    relationship = create_initial_relationship(
        npc_id,
        player_id,
        acquainted=(npc_id, player_id) in DEFAULT_ACQUAINTED_PAIRS,
    )
    return relationship, False


def _event_already_applied(
    store: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    record = _find_record(store, event["npc_id"], event["player_id"])
    return (
        record is not None
        and event["event_id"] in record["applied_event_ids"]
    )


def _validate_runtime_event(interaction_event: dict[str, Any]) -> None:
    try:
        validate_interaction_event(interaction_event)
    except NpcInteractionEventError as exc:
        raise NpcRelationshipPersistenceError(
            f"Runtime Interaction Event is invalid: {exc}"
        ) from exc


def _load_or_copy_store(
    store_path: Path,
    store_document: dict[str, Any] | None,
) -> dict[str, Any]:
    if store_document is None:
        return load_relationship_store(store_path)
    store = copy.deepcopy(store_document)
    validate_relationship_store(store)
    return store


def build_persistent_relationship_preview(
    interaction_event: dict[str, Any],
    store_path: Path = RELATIONSHIP_STORE_PATH,
    *,
    store_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read current state and evaluate without writing a default or mutation."""

    _validate_runtime_event(interaction_event)
    store = _load_or_copy_store(store_path, store_document)
    if _event_already_applied(store, interaction_event):
        raise DuplicateRelationshipEventError(
            "Relationship change for this interaction event already applied."
        )
    current, _ = resolve_current_relationship(
        store,
        interaction_event["npc_id"],
        interaction_event["player_id"],
    )
    try:
        return evaluate_relationship_change(current, interaction_event)
    except NpcRelationshipError as exc:
        raise NpcRelationshipPersistenceError(
            f"Relationship Change Preview could not be built: {exc}"
        ) from exc


def _assert_expected_preview(
    fresh_preview: dict[str, Any],
    expected_preview: dict[str, Any],
) -> None:
    try:
        validate_relationship_change(expected_preview)
    except NpcRelationshipError as exc:
        raise StaleRelationshipPreviewError(
            f"Displayed Relationship Preview is invalid: {exc}"
        ) from exc
    comparable_fields = (
        "npc_id",
        "player_id",
        "source_event_id",
        "decision",
        "current_relationship",
        "proposed_relationship",
        "changes",
    )
    if any(
        fresh_preview[field] != expected_preview[field]
        for field in comparable_fields
    ):
        raise StaleRelationshipPreviewError(
            "Relationship Preview is stale. Rebuild Preview before Commit."
        )


def commit_relationship_event(
    interaction_event: dict[str, Any],
    expected_preview: dict[str, Any],
    store_path: Path = RELATIONSHIP_STORE_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-evaluate one Event and atomically persist only an allowed mutation."""

    _validate_runtime_event(interaction_event)
    store = load_relationship_store(store_path)
    if _event_already_applied(store, interaction_event):
        raise DuplicateRelationshipEventError(
            "Relationship change for this interaction event already applied."
        )
    fresh_preview = build_persistent_relationship_preview(
        interaction_event,
        store_path,
        store_document=store,
    )
    _assert_expected_preview(fresh_preview, expected_preview)
    if fresh_preview["decision"] != "change_proposed":
        raise NoRelationshipChangeRequiredError(
            "No persistent relationship change required."
        )

    updated_store = copy.deepcopy(store)
    record = _find_record(
        updated_store,
        interaction_event["npc_id"],
        interaction_event["player_id"],
    )
    proposed = fresh_preview["proposed_relationship"]
    if record is None:
        record = {
            **copy.deepcopy(proposed),
            "applied_event_ids": [interaction_event["event_id"]],
            "last_source_event_id": interaction_event["event_id"],
        }
        updated_store["relationships"].append(record)
    else:
        record["familiarity"] = proposed["familiarity"]
        record["trust"] = proposed["trust"]
        record["attitude"] = proposed["attitude"]
        record["applied_event_ids"].append(interaction_event["event_id"])
        record["last_source_event_id"] = interaction_event["event_id"]

    validate_relationship_store(updated_store)
    write_relationship_store_atomically(updated_store, store_path)
    committed_store = load_relationship_store(store_path)
    committed_record = _find_record(
        committed_store,
        interaction_event["npc_id"],
        interaction_event["player_id"],
    )
    if committed_record is None:
        raise RelationshipStoreError("Committed Relationship record is missing.")
    return copy.deepcopy(committed_record), fresh_preview


def confirm_and_commit_relationship(
    interaction_event: dict[str, Any],
    preview: dict[str, Any],
    store_path: Path = RELATIONSHIP_STORE_PATH,
    *,
    input_fn: Callable[[str], str] = input,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Commit only y/yes; all other responses cancel without writing."""

    _validate_runtime_event(interaction_event)
    try:
        validate_relationship_change(preview)
    except NpcRelationshipError as exc:
        raise NpcRelationshipPersistenceError(
            f"Relationship Change Preview is invalid: {exc}"
        ) from exc
    if preview["decision"] != "change_proposed":
        raise NoRelationshipChangeRequiredError(
            "No persistent relationship change required."
        )

    store = load_relationship_store(store_path)
    if _event_already_applied(store, interaction_event):
        raise DuplicateRelationshipEventError(
            "Relationship change for this interaction event already applied."
        )
    answer = input_fn("Commit this relationship change? [y/N]: ").strip().casefold()
    if answer not in {"y", "yes"}:
        return None
    return commit_relationship_event(interaction_event, preview, store_path)
