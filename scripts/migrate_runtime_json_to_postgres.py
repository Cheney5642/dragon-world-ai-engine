"""One-time migration of the existing JSON runtime snapshot (C7-B).

JSON remains the runtime source of truth. Run --dry-run before --apply.
Development exports and Golden Fixtures are not authenticated history and are
not imported as Interaction Events. Existing database Events may resolve a
Memory reference only when they satisfy the Frozen NPC Event Contract.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from database.connection import (  # noqa: E402
    DatabaseConfigurationError,
    create_database_engine,
    create_session_factory,
)
from database.models import (  # noqa: E402
    InteractionEvent, Npc, NpcMemory, NpcRelationship, Player, PlayerState,
)
from database.persistence import PostgresPersistenceAdapter  # noqa: E402

SOURCES = {
    "world": "data/saves/current_world.json",
    "memories": "data/saves/npc_memories.json",
    "relationships": "data/saves/npc_relationships.json",
    "profiles": "data/npcs/anchor_npcs.json",
    "seed": "data/world_seed.json",
}
MODELS = {
    "players": Player,
    "npcs": Npc,
    "player_states": PlayerState,
    "npc_relationships": NpcRelationship,
    "interaction_events": InteractionEvent,
    "npc_memories": NpcMemory,
}


class MigrationError(ValueError):
    """Safe diagnostic without connection strings or SQL parameter dumps."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MigrationError(message)


def read_json(relative: str, hashes: dict[str, str]) -> Any:
    raw = (PROJECT_ROOT / relative).read_bytes()
    hashes[relative] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def assert_sources_unchanged(hashes: dict[str, str]) -> None:
    for relative, expected in hashes.items():
        actual = hashlib.sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest()
        require(actual == expected, f"Source changed during migration: {relative}")


def validate(value: Any, schema: dict[str, Any], label: str) -> None:
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        error = errors[0]
        path = "/".join(map(str, error.absolute_path)) or "<root>"
        raise MigrationError(f"{label}: Frozen Contract violation at {path} ({error.validator}).")


def load_sources() -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    hashes: dict[str, str] = {}
    sources = {key: read_json(path, hashes) for key, path in SOURCES.items()}
    schema_names = (
        "player_creation", "npc_profile", "npc_memory", "npc_memory_store",
        "npc_relationship_store", "npc_interaction_event",
    )
    schemas = {
        name: read_json(f"schemas/{name}.schema.json", hashes)
        for name in schema_names
    }
    world = sources["world"]
    require(isinstance(world, dict), "Current World must be an object.")
    require(all(key in world for key in ("world", "player", "npcs", "locations", "global_state")),
            "Current World is missing required sections.")
    player = world["player"]
    require(isinstance(player.get("id"), str) and bool(player["id"].strip()), "Player ID is missing.")
    player_schema = schemas["player_creation"]["properties"]["player"]
    validate({key: player[key] for key in player_schema["properties"]}, player_schema, "Player")
    require(isinstance(player["inventory"], list), "Player inventory must be an array.")
    locations = sources["seed"]["locations"]
    require(player["current_location"] in locations and player["current_location"] in world["locations"],
            "Player location does not resolve to configuration.")
    profiles = sources["profiles"]["profiles"]
    profile_by_id = {}
    for profile in profiles:
        validate(profile, schemas["npc_profile"], "NPC Profile")
        require(profile["id"] not in profile_by_id, "Duplicate NPC Profile ID.")
        profile_by_id[profile["id"]] = profile
    npc_ids = set()
    for npc in world["npcs"].values():
        npc_id = npc["id"]
        require(npc_id not in npc_ids, "Duplicate NPC registry ID.")
        npc_ids.add(npc_id)
        require(npc_id in profile_by_id, f"NPC does not resolve to Profile: {npc_id}")
        require(npc["current_location"] in locations, f"Unknown location for {npc_id}")
        for field in ("name", "species", "occupation"):
            require(npc[field] == profile_by_id[npc_id][field], f"NPC/Profile conflict: {npc_id}.{field}")
        for field in ("current_activity", "current_goal", "mood"):
            require(npc.get(field) is None or isinstance(npc[field], str), f"Invalid NPC {field}.")

    store_schema = copy.deepcopy(schemas["npc_memory_store"])
    store_schema["properties"]["memories"]["items"] = schemas["npc_memory"]
    validate(sources["memories"], store_schema, "Memory Store")
    validate(sources["relationships"], schemas["npc_relationship_store"], "Relationship Store")
    memory_ids, memory_events, relationship_ids = set(), set(), set()
    for memory in sources["memories"]["memories"]:
        require(memory["memory_id"] not in memory_ids, "Duplicate Memory ID.")
        memory_ids.add(memory["memory_id"])
        event_key = (memory["npc_id"], memory["source_event_id"])
        require(event_key not in memory_events, "Duplicate NPC/Memory source event.")
        memory_events.add(event_key)
        require(memory["world_context"]["location_id"] in locations, "Unknown Memory location.")
    for relationship in sources["relationships"]["relationships"]:
        key = (relationship["player_id"], relationship["npc_id"])
        require(key not in relationship_ids, "Duplicate Relationship identity.")
        relationship_ids.add(key)
        require(relationship["last_source_event_id"] in relationship["applied_event_ids"],
                "Relationship last event is missing from its audit history.")
    for record in sources["memories"]["memories"] + sources["relationships"]["relationships"]:
        require(record["player_id"] == player["id"], "Referenced Player does not exist in source registry.")
        require(record["npc_id"] in npc_ids, "Referenced NPC does not exist in source registry.")
    return sources, hashes, schemas


def prepare_rows(sources: dict[str, Any], session: Any, event_schema: dict[str, Any]) -> dict[str, list]:
    player = sources["world"]["player"]
    rows: dict[str, list] = {table: [] for table in MODELS}
    rows["players"] = [{"player_id": player["id"], **{
        field: player[field] for field in ("name", "species", "occupation", "background", "traits")
    }}]
    rows["player_states"] = [{"player_id": player["id"], **{
        field: player[field] for field in ("current_location", "inventory", "goals")
    }}]
    rows["npcs"] = [
        {"npc_id": npc["id"], "current_location": npc["current_location"],
         **{field: npc.get(field) for field in ("current_activity", "current_goal", "mood")}}
        for npc in sources["world"]["npcs"].values()
    ]
    rows["npc_relationships"] = copy.deepcopy(sources["relationships"]["relationships"])
    for original in sources["memories"]["memories"]:
        memory = copy.deepcopy(original)
        event = session.get(InteractionEvent, memory["source_event_id"])
        if event is None:
            memory["metadata"] = {"legacy_source_event_id": memory["source_event_id"]}
            memory["source_event_id"] = None
        else:
            # Do not infer Event contents from a Memory or from an ID alone.
            event_data = {field: getattr(event, field) for field in (
                "event_id", "event_type", "npc_id", "player_id", "player_utterance",
                "npc_response", "topic", "player_claims", "memory_candidate", "relationship_signal",
            )}
            event_data["world_context"] = {field: getattr(event, field) for field in (
                "world_day", "world_hour", "location_id",
            )}
            validate(event_data, event_schema, "Existing source Event")
            require(event.npc_id == memory["npc_id"] and event.player_id == memory["player_id"],
                    "Memory source Event identity mismatch.")
            require(event_data["world_context"] == memory["world_context"], "Memory source Event context mismatch.")
            memory["metadata"] = None
        rows["npc_memories"].append(memory)
    return rows


def database_values(table: str, row: dict[str, Any]) -> dict[str, Any]:
    values = copy.deepcopy(row)
    if table == "npc_memories":
        values.update(values.pop("world_context"))
    return values


def check_existing(session: Any, table: str, row: dict[str, Any]) -> bool:
    model = MODELS[table]
    values = database_values(table, row)
    keys = tuple(values[column.name] for column in model.__table__.primary_key.columns)
    existing = session.get(model, keys)
    if existing is None:
        return False
    for column, expected in values.items():
        attribute = "memory_metadata" if table == "npc_memories" and column == "metadata" else column
        require(getattr(existing, attribute) == expected,
                f"Conflict in {table} ({', '.join(map(str, keys))}), field {column}; no overwrite allowed.")
    return True


def migrate(dry_run: bool) -> None:
    sources, hashes, schemas = load_sources()
    counts = {"world": 1, "memories": len(sources["memories"]["memories"]),
              "relationships": len(sources["relationships"]["relationships"]),
              "profiles": len(sources["profiles"]["profiles"]), "seed": 1}
    for key, path in SOURCES.items():
        print(f"Source: {path} | SHA-256: {hashes[path]} | Records: {counts[key]}")
    print("Interaction Events to import: 0 (no authenticated persistent Event history).")
    print("data/runtime development exports and Golden Fixtures are excluded.")
    engine = create_database_engine()
    try:
        with engine.begin() as connection:
            if dry_run:
                connection.execute(text("SET TRANSACTION READ ONLY"))
            else:
                # Serialize compatibility checks and writes; never silently
                # overwrite a concurrent registry/state insert via an upsert.
                connection.execute(text(
                    "LOCK TABLE public.players, public.npcs, public.player_states, "
                    "public.npc_relationships, public.interaction_events, public.npc_memories "
                    "IN SHARE ROW EXCLUSIVE MODE"
                ))
            require(connection.scalar(text("SELECT current_database()")) == "dragon_world",
                    "Unexpected target database.")
            factory = create_session_factory(engine)
            factory.configure(bind=connection, join_transaction_mode="create_savepoint")
            adapter = PostgresPersistenceAdapter(factory)
            with factory() as session:
                rows = prepare_rows(sources, session, schemas["npc_interaction_event"])
                pending = {table: [row for row in records if not check_existing(session, table, row)]
                           for table, records in rows.items()}
            for table, records in rows.items():
                print(f"{table}: Source={len(records)}, Insert={len(pending[table])}, Skip={len(records)-len(pending[table])}")
            print("Legacy Memory references mapped to NULL:",
                  sum(row["source_event_id"] is None for row in rows["npc_memories"]))
            assert_sources_unchanged(hashes)
            if not dry_run:
                for row in pending["players"]:
                    adapter.ensure_player(**row)
                for row in pending["npcs"]:
                    adapter.ensure_npc(**row)
                for row in pending["player_states"]:
                    adapter.upsert_player_state(**row)
                for row in pending["npc_relationships"]:
                    adapter.upsert_npc_relationship(row)
                # No Event rows are invented; referenced DB Events already exist.
                for row in pending["npc_memories"]:
                    adapter.insert_npc_memory(row)
                with factory() as session:
                    for table, records in rows.items():
                        for row in records:
                            require(check_existing(session, table, row), f"Post-write record missing in {table}.")
                assert_sources_unchanged(hashes)
            print("All source records/FK identities and destination compatibility: PASS")
        print("Dry Run: PASS (no database writes)" if dry_run else "Migration: COMMITTED")
        print("Source hash check: PASS; Runtime source of truth remains JSON.")
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        migrate(args.dry_run)
    except (MigrationError, DatabaseConfigurationError) as exc:
        print(f"Migration stopped: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Migration failed: database connection/constraint error. Transaction rolled back; credentials and SQL parameters withheld.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Migration stopped: invalid or unreadable source/configuration ({type(exc).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
