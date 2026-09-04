"""Thin PostgreSQL persistence adapter for the Step 6.7-C7-A scope.

The JSON runtime remains the source of truth in this phase. This adapter is a
preparation layer only: it does not dual-write, migrate JSON, or change any
runtime call path. Callers must supply already validated registry/domain data.

The Frozen ``npc_memories`` schema has no ``created_at`` column. The adapter
therefore does not invent one or hide it in metadata; interaction record time
is represented separately by ``interaction_events.recorded_at``.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from database.models import (
    InteractionEvent,
    Npc,
    NpcMemory,
    NpcRelationship,
    Player,
    PlayerState,
)


class PersistenceMappingError(ValueError):
    """Raised when input cannot map to the Frozen PostgreSQL schema."""


class PostgresPersistenceAdapter:
    """Minimal explicit CRUD boundary over the existing SQLAlchemy Session."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _read_session(self) -> Generator[Session, None, None]:
        with self._session_factory() as session:
            yield session

    @contextmanager
    def _write_session(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_player(self, player_id: str) -> dict[str, Any] | None:
        """Read one Player registry row without producing a mutation."""

        with self._read_session() as session:
            record = session.get(Player, player_id)
            return _player_record(record) if record is not None else None

    def ensure_player(
        self,
        *,
        player_id: str,
        name: str | None,
        species: str | None,
        occupation: str | None,
        background: str | None,
        traits: Sequence[str],
    ) -> dict[str, Any]:
        """Create a supplied Player registry row only when it does not exist."""

        with self._write_session() as session:
            record = session.get(Player, player_id)
            if record is None:
                record = Player(
                    player_id=player_id,
                    name=name,
                    species=species,
                    occupation=occupation,
                    background=background,
                    traits=list(traits),
                )
                session.add(record)
                session.flush()
            return _player_record(record)

    def get_npc(self, npc_id: str) -> dict[str, Any] | None:
        """Read one NPC registry/runtime row without producing a mutation."""

        with self._read_session() as session:
            record = session.get(Npc, npc_id)
            return _npc_record(record) if record is not None else None

    def ensure_npc(
        self,
        *,
        npc_id: str,
        current_location: str,
        current_activity: str | None = None,
        current_goal: str | None = None,
        mood: str | None = None,
    ) -> dict[str, Any]:
        """Create a supplied NPC registry row only when it does not exist."""

        with self._write_session() as session:
            record = session.get(Npc, npc_id)
            if record is None:
                record = Npc(
                    npc_id=npc_id,
                    current_location=current_location,
                    current_activity=current_activity,
                    current_goal=current_goal,
                    mood=mood,
                )
                session.add(record)
                session.flush()
            return _npc_record(record)

    def get_player_state(self, player_id: str) -> dict[str, Any] | None:
        """Read current Player State without creating a missing row."""

        with self._read_session() as session:
            record = session.get(PlayerState, player_id)
            return _player_state_record(record) if record is not None else None

    def upsert_player_state(
        self,
        *,
        player_id: str,
        current_location: str,
        inventory: Sequence[Any],
        goals: Sequence[str],
    ) -> dict[str, Any]:
        """Insert or update the single current state row for a known Player."""

        with self._write_session() as session:
            record = session.get(PlayerState, player_id)
            if record is None:
                record = PlayerState(
                    player_id=player_id,
                    current_location=current_location,
                    inventory=list(inventory),
                    goals=list(goals),
                )
                session.add(record)
            else:
                record.current_location = current_location
                record.inventory = list(inventory)
                record.goals = list(goals)
            session.flush()
            return _player_state_record(record)

    def list_npc_memories(
        self,
        npc_id: str,
        player_id: str,
    ) -> list[dict[str, Any]]:
        """Read relevant persisted records; this method never writes."""

        statement = (
            select(NpcMemory)
            .where(
                NpcMemory.npc_id == npc_id,
                NpcMemory.player_id == player_id,
            )
            .order_by(
                NpcMemory.world_day,
                NpcMemory.world_hour,
                NpcMemory.memory_id,
            )
        )
        with self._read_session() as session:
            return [
                _npc_memory_record(record)
                for record in session.scalars(statement).all()
            ]

    def insert_npc_memory(
        self,
        memory: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Insert one Frozen NPC Memory record with explicit field mapping."""

        if "created_at" in memory:
            raise PersistenceMappingError(
                "Frozen npc_memories v0.1 has no created_at column."
            )
        world_context = _required_mapping(memory, "world_context")
        metadata = memory.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise PersistenceMappingError("memory metadata must be an object or null.")

        with self._write_session() as session:
            record = NpcMemory(
                memory_id=memory["memory_id"],
                npc_id=memory["npc_id"],
                player_id=memory["player_id"],
                source_event_id=memory.get("source_event_id"),
                memory_type=memory["memory_type"],
                content=memory["content"],
                epistemic_status=memory["epistemic_status"],
                world_day=world_context["world_day"],
                world_hour=world_context["world_hour"],
                location_id=world_context["location_id"],
                created_from_topic=memory["created_from_topic"],
                memory_metadata=dict(metadata) if metadata is not None else None,
            )
            session.add(record)
            session.flush()
            return _npc_memory_record(record)

    def get_npc_relationship(
        self,
        player_id: str,
        npc_id: str,
    ) -> dict[str, Any] | None:
        """Read the composite-key relationship without creating a default."""

        with self._read_session() as session:
            record = session.get(NpcRelationship, (player_id, npc_id))
            return _npc_relationship_record(record) if record is not None else None

    def upsert_npc_relationship(
        self,
        relationship: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Insert or update an already evaluated Frozen Relationship State."""

        key = (relationship["player_id"], relationship["npc_id"])
        with self._write_session() as session:
            record = session.get(NpcRelationship, key)
            if record is None:
                record = NpcRelationship(
                    player_id=relationship["player_id"],
                    npc_id=relationship["npc_id"],
                    familiarity=relationship["familiarity"],
                    trust=relationship["trust"],
                    attitude=relationship["attitude"],
                    applied_event_ids=list(relationship["applied_event_ids"]),
                    last_source_event_id=relationship["last_source_event_id"],
                )
                session.add(record)
            else:
                record.familiarity = relationship["familiarity"]
                record.trust = relationship["trust"]
                record.attitude = relationship["attitude"]
                record.applied_event_ids = list(relationship["applied_event_ids"])
                record.last_source_event_id = relationship["last_source_event_id"]
            session.flush()
            return _npc_relationship_record(record)

    def insert_interaction_event(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Insert one existing Frozen Interaction Event without reinterpreting it."""

        world_context = _required_mapping(event, "world_context")
        npc_response = event.get("npc_response")
        if npc_response is not None and not isinstance(npc_response, Mapping):
            raise PersistenceMappingError(
                "interaction event npc_response must be an object or null."
            )
        event_payload = event.get("event_payload")
        if event_payload is not None and not isinstance(event_payload, Mapping):
            raise PersistenceMappingError(
                "interaction event event_payload must be an object or null."
            )

        with self._write_session() as session:
            record = InteractionEvent(
                event_id=event["event_id"],
                event_type=event["event_type"],
                player_id=event["player_id"],
                npc_id=event.get("npc_id"),
                world_day=world_context["world_day"],
                world_hour=world_context["world_hour"],
                location_id=world_context["location_id"],
                player_utterance=event["player_utterance"],
                npc_response=(
                    dict(npc_response) if npc_response is not None else None
                ),
                topic=event.get("topic"),
                player_claims=list(event.get("player_claims", [])),
                memory_candidate=event.get("memory_candidate"),
                relationship_signal=event.get("relationship_signal"),
                event_payload=(
                    dict(event_payload) if event_payload is not None else None
                ),
            )
            session.add(record)
            session.flush()
            session.refresh(record)
            return _interaction_event_record(record)


def _required_mapping(
    value: Mapping[str, Any],
    key: str,
) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise PersistenceMappingError(f"{key} must be an object.")
    return nested


def _player_record(record: Player) -> dict[str, Any]:
    return {
        "player_id": record.player_id,
        "name": record.name,
        "species": record.species,
        "occupation": record.occupation,
        "background": record.background,
        "traits": list(record.traits),
    }


def _npc_record(record: Npc) -> dict[str, Any]:
    return {
        "npc_id": record.npc_id,
        "current_location": record.current_location,
        "current_activity": record.current_activity,
        "current_goal": record.current_goal,
        "mood": record.mood,
    }


def _player_state_record(record: PlayerState) -> dict[str, Any]:
    return {
        "player_id": record.player_id,
        "current_location": record.current_location,
        "inventory": list(record.inventory),
        "goals": list(record.goals),
    }


def _npc_memory_record(record: NpcMemory) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "npc_id": record.npc_id,
        "player_id": record.player_id,
        "source_event_id": record.source_event_id,
        "memory_type": record.memory_type,
        "content": record.content,
        "epistemic_status": record.epistemic_status,
        "world_context": {
            "world_day": record.world_day,
            "world_hour": record.world_hour,
            "location_id": record.location_id,
        },
        "created_from_topic": record.created_from_topic,
        "metadata": (
            dict(record.memory_metadata)
            if record.memory_metadata is not None
            else None
        ),
    }


def _npc_relationship_record(record: NpcRelationship) -> dict[str, Any]:
    return {
        "player_id": record.player_id,
        "npc_id": record.npc_id,
        "familiarity": record.familiarity,
        "trust": record.trust,
        "attitude": record.attitude,
        "applied_event_ids": list(record.applied_event_ids),
        "last_source_event_id": record.last_source_event_id,
    }


def _interaction_event_record(record: InteractionEvent) -> dict[str, Any]:
    return {
        "event_id": record.event_id,
        "event_type": record.event_type,
        "npc_id": record.npc_id,
        "player_id": record.player_id,
        "world_context": {
            "world_day": record.world_day,
            "world_hour": record.world_hour,
            "location_id": record.location_id,
        },
        "player_utterance": record.player_utterance,
        "npc_response": (
            dict(record.npc_response) if record.npc_response is not None else None
        ),
        "topic": record.topic,
        "player_claims": list(record.player_claims),
        "memory_candidate": record.memory_candidate,
        "relationship_signal": record.relationship_signal,
        "event_payload": (
            dict(record.event_payload) if record.event_payload is not None else None
        ),
        "recorded_at": record.recorded_at.isoformat(),
    }
