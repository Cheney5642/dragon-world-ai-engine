"""Recover the minimal formal Dragon World demo state after a clean restore.

This is a one-time, idempotent recovery utility. It uses the frozen ORM
mappings inside one PostgreSQL transaction, never changes schema, and refuses
to overwrite conflicting rows.
"""

from __future__ import annotations

import copy
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.location_discovery import (  # noqa: E402
    DYNAMIC_LOCATION_REGISTRY_STATE_ID,
    merge_location_registries,
    stable_location_id_for_source,
)
from database.connection import (  # noqa: E402
    DatabaseConfigurationError,
    create_database_engine,
)
from database.models import (  # noqa: E402
    Dragon,
    DragonEvent,
    InteractionEvent,
    Npc,
    NpcMemory,
    NpcRelationship,
    Player,
    PlayerDragonBond,
    PlayerState,
    WorldStateEntry,
)
from database.persistence import (  # noqa: E402
    PersistenceMappingError,
    _dynamic_location_registry_value,
    _dynamic_location_value,
)


PLAYER_ID = "player_001"
DRAGON_ID = "dragon_909cf832bd2e5a3599a191bc8cb52edb"
DRAGON_ARCHETYPE_ID = "balanced_wild"
DRAGON_LOCATION_ID = "stormcliff"
RECOVERY_NAMESPACE = "dragon-world:recovery-step-4"
DYNAMIC_LOCATION_SOURCE_ID = "recovery_step_4_mist_eroded_cove"
DYNAMIC_LOCATION_NAME = "雾蚀凹湾"

FIRST_ENCOUNTER_EVENT_ID = f"dragon_event_{uuid.uuid5(uuid.NAMESPACE_URL, f'{RECOVERY_NAMESPACE}:dragon_first_encounter').hex}"
TAMED_EVENT_ID = f"dragon_event_{uuid.uuid5(uuid.NAMESPACE_URL, f'{RECOVERY_NAMESPACE}:dragon_tamed').hex}"
DYNAMIC_LOCATION_ID = stable_location_id_for_source(DYNAMIC_LOCATION_SOURCE_ID)

TABLE_MODELS = (
    Player,
    PlayerState,
    Npc,
    NpcMemory,
    NpcRelationship,
    Dragon,
    PlayerDragonBond,
    DragonEvent,
    InteractionEvent,
    WorldStateEntry,
)


class RecoveryConflictError(RuntimeError):
    """A formal row exists but differs from the recovery baseline."""


@dataclass
class RecoveryResult:
    created: list[str] = field(default_factory=list)
    already_applied: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "already_applied" if not self.created else "applied"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryConflictError(f"Cannot read formal authored data: {path.name}") from exc
    if not isinstance(value, dict):
        raise RecoveryConflictError(f"Formal authored data is not an object: {path.name}")
    return value


def _expected_rows() -> dict[str, Any]:
    seed = _read_json(PROJECT_ROOT / "data" / "world_seed.json")
    archetypes = _read_json(PROJECT_ROOT / "data" / "dragon_archetypes.json")

    try:
        player = seed["player"]
        locations = seed["locations"]
        npcs = seed["npcs"]
        archetype = archetypes["archetypes"][DRAGON_ARCHETYPE_ID]
        dragon_defaults = archetype["runtime_defaults"]
        temperament = archetype["behavioral_tendencies"]
    except (KeyError, TypeError) as exc:
        raise RecoveryConflictError("Formal authored seed is missing required recovery data.") from exc

    if player.get("id") != PLAYER_ID:
        raise RecoveryConflictError("Formal authored Player is not player_001.")
    if DRAGON_LOCATION_ID not in locations:
        raise RecoveryConflictError("Formal authored world does not contain stormcliff.")

    expected_npcs: list[dict[str, Any]] = []
    for key in ("astrid", "bjorn", "haldor"):
        try:
            npc = npcs[key]
        except (KeyError, TypeError) as exc:
            raise RecoveryConflictError(f"Formal authored NPC is missing: {key}") from exc
        expected_npcs.append(
            {
                "npc_id": npc["id"],
                "current_location": npc["current_location"],
                "current_activity": npc.get("current_activity"),
                "current_goal": npc.get("current_goal"),
                "mood": npc.get("mood"),
            }
        )

    player_row = {
        "player_id": player["id"],
        "name": player.get("name"),
        "species": player.get("species"),
        "occupation": player.get("occupation"),
        "background": player.get("background"),
        "traits": copy.deepcopy(player["traits"]),
    }
    player_state_row = {
        "player_id": player["id"],
        "current_location": player["current_location"],
        "inventory": copy.deepcopy(player["inventory"]),
        "goals": copy.deepcopy(player["goals"]),
        "identity_context": None,
    }
    dragon_row = {
        "dragon_id": DRAGON_ID,
        "archetype_id": DRAGON_ARCHETYPE_ID,
        "name": "Kael",
        "sex": None,
        "age_stage": dragon_defaults["age_stage"],
        # Kael's original generated appearance was not Git-tracked. An empty
        # object preserves "unknown" without fabricating lost narrative facts.
        "appearance": {},
        "temperament_traits": copy.deepcopy(temperament),
        "current_location": DRAGON_LOCATION_ID,
        "health_state": dragon_defaults["health_state"],
        "energy": dragon_defaults["energy"],
        "hunger": dragon_defaults["hunger"],
        "alertness": dragon_defaults["alertness"],
        "behavior_state": dragon_defaults["behavior_state"],
        "taming_state": "tamed",
    }
    first_event = {
        "event_id": FIRST_ENCOUNTER_EVENT_ID,
        "event_type": "dragon_first_encounter",
        "dragon_id": DRAGON_ID,
        "player_id": PLAYER_ID,
        "source_interaction_event_id": None,
        "world_day": seed["world"]["day"],
        "world_hour": seed["world"]["hour"],
        "location_id": DRAGON_LOCATION_ID,
        "milestone_key": "first_encounter",
        "event_payload": {"recovery_baseline": "step_4"},
    }
    tamed_event = {
        "event_id": TAMED_EVENT_ID,
        "event_type": "dragon_tamed",
        "dragon_id": DRAGON_ID,
        "player_id": PLAYER_ID,
        "source_interaction_event_id": None,
        "world_day": seed["world"]["day"],
        "world_hour": seed["world"]["hour"],
        "location_id": DRAGON_LOCATION_ID,
        "milestone_key": "tamed",
        "event_payload": {"recovery_baseline": "step_4"},
    }
    bond_row = {
        "player_id": PLAYER_ID,
        "dragon_id": DRAGON_ID,
        "familiarity": 5,
        "trust": 5,
        "fear": 0,
        "bond": 2,
        "riding_unlocked": False,
        "last_significant_event_id": TAMED_EVENT_ID,
    }
    dynamic_location = _dynamic_location_value(
        {
            "location_id": DYNAMIC_LOCATION_ID,
            "name": DYNAMIC_LOCATION_NAME,
            "location_type": "cove",
            "short_description": "一处被寒雾遮蔽、受海风侵蚀的隐蔽凹湾。",
            "environment_tags": ["海雾", "岩岸", "寒风"],
            "discovery_reason": "沿 Skeld 海岸探索时发现了通往凹湾的隐蔽路径。",
            "origin": "dynamic",
            "discovery_status": "discovered",
            "source_interaction_event_id": DYNAMIC_LOCATION_SOURCE_ID,
            "discovered_from_location_id": "skeld_village",
            "connections": ["skeld_village"],
        }
    )
    return {
        "seed": seed,
        "player": player_row,
        "player_state": player_state_row,
        "npcs": expected_npcs,
        "dragon": dragon_row,
        "dragon_events": [first_event, tamed_event],
        "bond": bond_row,
        "dynamic_location": dynamic_location,
    }


def _record_values(record: Any, expected: dict[str, Any]) -> dict[str, Any]:
    return {field: getattr(record, field) for field in expected}


def _ensure_exact(
    session: Session,
    model: type[Any],
    identity: Any,
    expected: dict[str, Any],
    label: str,
    result: RecoveryResult,
) -> Any:
    record = session.get(model, identity)
    if record is None:
        create_values = copy.deepcopy(expected)
        if model is PlayerState and create_values.get("identity_context") is None:
            # Explicit Python None on JSONB is encoded as JSON null. Omitting
            # the nullable column produces the SQL NULL required by the check.
            create_values.pop("identity_context")
        record = model(**create_values)
        session.add(record)
        session.flush()
        result.created.append(label)
        return record
    actual = _record_values(record, expected)
    if actual != expected:
        differing = sorted(key for key in expected if actual[key] != expected[key])
        raise RecoveryConflictError(
            f"Conflict in {label}; no overwrite allowed (fields: {', '.join(differing)})."
        )
    result.already_applied.append(label)
    return record


def _ensure_dynamic_location(
    session: Session,
    expected: dict[str, Any],
    authored_locations: dict[str, Any],
    result: RecoveryResult,
) -> None:
    record = session.get(WorldStateEntry, DYNAMIC_LOCATION_REGISTRY_STATE_ID)
    if record is None:
        registry = {"version": 1, "locations": {DYNAMIC_LOCATION_ID: expected}}
        _dynamic_location_registry_value(registry)
        merge_location_registries(authored_locations, registry)
        session.add(
            WorldStateEntry(
                state_id=DYNAMIC_LOCATION_REGISTRY_STATE_ID,
                state_value=registry,
                source_event_type=None,
                source_event_id=None,
            )
        )
        session.flush()
        result.created.append("dynamic_location:雾蚀凹湾")
        return

    registry = _dynamic_location_registry_value(record.state_value)
    locations = registry["locations"]
    by_name = [
        value for value in locations.values() if value["name"] == DYNAMIC_LOCATION_NAME
    ]
    existing = locations.get(DYNAMIC_LOCATION_ID)
    if existing is not None:
        if existing != expected or by_name != [existing]:
            raise RecoveryConflictError(
                "Conflict in dynamic_location:雾蚀凹湾; no overwrite allowed."
            )
        merge_location_registries(authored_locations, registry)
        result.already_applied.append("dynamic_location:雾蚀凹湾")
        return
    if by_name:
        raise RecoveryConflictError(
            "Dynamic Location name exists under another ID; no overwrite allowed."
        )
    locations[DYNAMIC_LOCATION_ID] = copy.deepcopy(expected)
    grounded_registry = _dynamic_location_registry_value(registry)
    merge_location_registries(authored_locations, grounded_registry)
    record.state_value = grounded_registry
    session.flush()
    result.created.append("dynamic_location:雾蚀凹湾")


def recover(session: Session) -> RecoveryResult:
    expected = _expected_rows()
    result = RecoveryResult()

    session.execute(
        text(
            "LOCK TABLE public.players, public.player_states, public.npcs, "
            "public.npc_memories, public.npc_relationships, public.dragons, "
            "public.dragon_events, public.player_dragon_bonds, "
            "public.interaction_events, public.world_state_entries "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )

    _ensure_exact(session, Player, PLAYER_ID, expected["player"], "player:player_001", result)
    _ensure_exact(
        session,
        PlayerState,
        PLAYER_ID,
        expected["player_state"],
        "player_state:player_001",
        result,
    )
    for npc in expected["npcs"]:
        _ensure_exact(session, Npc, npc["npc_id"], npc, f"npc:{npc['npc_id']}", result)
    _ensure_exact(session, Dragon, DRAGON_ID, expected["dragon"], f"dragon:{DRAGON_ID}", result)
    for event in expected["dragon_events"]:
        same_type = session.scalars(
            select(DragonEvent).where(
                DragonEvent.dragon_id == DRAGON_ID,
                DragonEvent.player_id == PLAYER_ID,
                DragonEvent.event_type == event["event_type"],
            )
        ).all()
        if same_type and any(row.event_id != event["event_id"] for row in same_type):
            raise RecoveryConflictError(
                f"Conflicting {event['event_type']} Event already exists for Kael."
            )
        _ensure_exact(
            session,
            DragonEvent,
            event["event_id"],
            event,
            f"dragon_event:{event['event_type']}",
            result,
        )
    _ensure_exact(
        session,
        PlayerDragonBond,
        (PLAYER_ID, DRAGON_ID),
        expected["bond"],
        "player_dragon_bond:player_001+Kael",
        result,
    )
    _ensure_dynamic_location(
        session,
        expected["dynamic_location"],
        expected["seed"]["locations"],
        result,
    )
    return result


def _counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in TABLE_MODELS
    }


def main() -> int:
    engine = None
    try:
        engine = create_database_engine()
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                database_name = session.scalar(text("SELECT current_database()"))
                if database_name != "dragon_world":
                    raise RecoveryConflictError("Unexpected target database; recovery refused.")
                result = recover(session)
                counts = _counts(session)
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "created": result.created,
                        "already_applied": result.already_applied,
                        "counts": counts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    except (DatabaseConfigurationError, PersistenceMappingError, RecoveryConflictError) as exc:
        print(f"Recovery failed; transaction rolled back: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"Recovery failed; transaction rolled back: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
