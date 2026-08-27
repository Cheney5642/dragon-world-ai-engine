"""Persistent NPC Memory v0.1: preview, validation, and safe commit."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from npc.interaction_event import (
    NpcInteractionEventError,
    validate_interaction_event,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_memory.schema.json"
STORE_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_memory_store.schema.json"
MEMORY_STORE_PATH = PROJECT_ROOT / "data" / "saves" / "npc_memories.json"


class NpcMemoryError(Exception):
    """Base error for safe NPC Memory operations."""


class NoPersistentMemoryRequiredError(NpcMemoryError):
    """Raised when an Interaction Event is not a Memory Candidate."""


class DuplicateMemoryError(NpcMemoryError):
    """Raised when the same NPC has already stored the source Interaction Event."""


class MemoryStoreError(NpcMemoryError):
    """Raised when the persistent Memory Store is invalid or cannot be written."""


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise MemoryStoreError(f"{label} does not exist: {path}")
    if not path.is_file():
        raise MemoryStoreError(f"{label} path is not a file: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryStoreError(f"{label} is not valid readable JSON: {path}") from exc
    if not isinstance(document, dict):
        raise MemoryStoreError(f"{label} must contain a JSON object: {path}")
    return document


def load_memory_schema(path: Path = MEMORY_SCHEMA_PATH) -> dict[str, Any]:
    return _load_json_object(path, "NPC Memory Schema")


def load_memory_store_schema(path: Path = STORE_SCHEMA_PATH) -> dict[str, Any]:
    return _load_json_object(path, "NPC Memory Store Schema")


def validate_memory_record(
    memory: dict[str, Any],
    memory_schema: dict[str, Any] | None = None,
) -> None:
    schema = memory_schema or load_memory_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(memory)
    except (SchemaError, ValidationError) as exc:
        raise NpcMemoryError(
            f"NPC Memory failed JSON Schema validation: {exc.message}"
        ) from exc


def _resolved_store_schema(
    store_schema: dict[str, Any],
    memory_schema: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the local record reference without network or external resolution."""

    resolved = copy.deepcopy(store_schema)
    resolved["properties"]["memories"]["items"] = copy.deepcopy(memory_schema)
    return resolved


def validate_memory_store(
    store: dict[str, Any],
    *,
    store_schema: dict[str, Any] | None = None,
    memory_schema: dict[str, Any] | None = None,
) -> None:
    store_schema = store_schema or load_memory_store_schema()
    memory_schema = memory_schema or load_memory_schema()
    resolved_schema = _resolved_store_schema(store_schema, memory_schema)
    try:
        Draft202012Validator.check_schema(resolved_schema)
        Draft202012Validator(resolved_schema).validate(store)
    except (SchemaError, ValidationError) as exc:
        raise MemoryStoreError(
            f"NPC Memory Store failed JSON Schema validation: {exc.message}"
        ) from exc

    memory_ids: set[str] = set()
    provenance_keys: set[tuple[str, str]] = set()
    for memory in store["memories"]:
        memory_id = memory["memory_id"]
        provenance_key = (memory["npc_id"], memory["source_event_id"])
        if memory_id in memory_ids:
            raise MemoryStoreError(f"Duplicate memory_id in NPC Memory Store: {memory_id}")
        if provenance_key in provenance_keys:
            raise MemoryStoreError(
                "Duplicate NPC/source event pair in NPC Memory Store: "
                f"{provenance_key[0]} + {provenance_key[1]}"
            )
        memory_ids.add(memory_id)
        provenance_keys.add(provenance_key)


def load_memory_store(
    store_path: Path = MEMORY_STORE_PATH,
    *,
    store_schema: dict[str, Any] | None = None,
    memory_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = _load_json_object(store_path, "NPC Memory Store")
    validate_memory_store(
        store,
        store_schema=store_schema,
        memory_schema=memory_schema,
    )
    return store


def write_memory_store_atomically(
    store: dict[str, Any],
    store_path: Path = MEMORY_STORE_PATH,
    *,
    store_schema: dict[str, Any] | None = None,
    memory_schema: dict[str, Any] | None = None,
) -> None:
    """Validate a temporary file before atomically replacing only the Memory Store."""

    store_schema = store_schema or load_memory_store_schema()
    memory_schema = memory_schema or load_memory_schema()
    validate_memory_store(
        store,
        store_schema=store_schema,
        memory_schema=memory_schema,
    )
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

        load_memory_store(
            temporary_path,
            store_schema=store_schema,
            memory_schema=memory_schema,
        )
        os.replace(temporary_path, store_path)
        temporary_path = None
        load_memory_store(
            store_path,
            store_schema=store_schema,
            memory_schema=memory_schema,
        )
    except (PermissionError, OSError) as exc:
        raise MemoryStoreError(
            f"Could not safely write NPC Memory Store: {store_path} ({exc})"
        ) from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def initialize_memory_store(store_path: Path = MEMORY_STORE_PATH) -> dict[str, Any]:
    """Create a schema-valid empty Memory Store only when one does not exist."""

    if store_path.exists():
        return load_memory_store(store_path)
    empty_store = {"version": "0.1", "memories": []}
    write_memory_store_atomically(empty_store, store_path)
    return empty_store


def _classify_memory(player_claims: list[str]) -> tuple[str, str, str]:
    if not player_claims:
        return (
            "interaction",
            "A significant interaction occurred.",
            "observed_interaction",
        )

    content = player_claims[0]
    normalized = content.casefold()
    intention_markers = (
        " intends ",
        " wants ",
        " plans ",
        "states an intention",
    )
    memory_type = (
        "player_intention"
        if any(marker in normalized for marker in intention_markers)
        else "player_claim"
    )
    return memory_type, content, "reported_by_player"


def build_memory_preview(
    interaction_event: dict[str, Any],
    *,
    memory_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only Memory Preview from one validated Interaction Event."""

    try:
        validate_interaction_event(interaction_event)
    except NpcInteractionEventError as exc:
        raise NpcMemoryError(f"Interaction Event is invalid: {exc}") from exc

    if interaction_event["memory_candidate"] is not True:
        raise NoPersistentMemoryRequiredError("No persistent memory required.")

    memory_type, content, epistemic_status = _classify_memory(
        interaction_event["player_claims"]
    )
    memory = {
        "memory_id": f"npc_memory_{uuid.uuid4().hex}",
        "npc_id": interaction_event["npc_id"],
        "player_id": interaction_event["player_id"],
        "source_event_id": interaction_event["event_id"],
        "memory_type": memory_type,
        "content": content,
        "epistemic_status": epistemic_status,
        "world_context": copy.deepcopy(interaction_event["world_context"]),
        "created_from_topic": interaction_event["topic"],
    }
    validate_memory_record(memory, memory_schema)
    return memory


def _ensure_not_duplicate(memory: dict[str, Any], store: dict[str, Any]) -> None:
    for existing in store["memories"]:
        if (
            existing["npc_id"] == memory["npc_id"]
            and existing["source_event_id"] == memory["source_event_id"]
        ):
            raise DuplicateMemoryError(
                "Memory for this interaction event already exists."
            )


def commit_memory_preview(
    memory: dict[str, Any],
    store_path: Path = MEMORY_STORE_PATH,
) -> dict[str, Any]:
    """Commit one validated, non-duplicate Memory to the independent Store."""

    validate_memory_record(memory)
    store = load_memory_store(store_path)
    _ensure_not_duplicate(memory, store)
    updated_store = copy.deepcopy(store)
    updated_store["memories"].append(copy.deepcopy(memory))
    write_memory_store_atomically(updated_store, store_path)
    return copy.deepcopy(memory)


def confirm_and_commit_memory(
    memory: dict[str, Any],
    store_path: Path = MEMORY_STORE_PATH,
    input_fn: Callable[[str], str] = input,
) -> dict[str, Any] | None:
    """Require explicit confirmation, then revalidate and safely commit Memory."""

    validate_memory_record(memory)
    current_store = load_memory_store(store_path)
    _ensure_not_duplicate(memory, current_store)
    try:
        answer = input_fn("Commit this memory to the NPC memory store? [y/N]: ")
    except EOFError:
        answer = ""
    if answer.strip().casefold() not in {"y", "yes"}:
        return None
    return commit_memory_preview(memory, store_path)
