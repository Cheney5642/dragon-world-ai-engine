"""Thin PostgreSQL persistence adapter for the Dragon World runtime.

PostgreSQL is the runtime source of truth after the C7-C cutover. This module
keeps explicit domain-shaped operations and does not dual-write or fall back to
the legacy JSON migration artifacts. Callers must supply already validated
registry/domain data.

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
    Dragon,
    DragonEvent,
    InteractionEvent,
    Npc,
    NpcMemory,
    NpcRelationship,
    Player,
    PlayerDragonBond,
    PlayerState,
)


class PersistenceMappingError(ValueError):
    """Raised when input cannot map to the Frozen PostgreSQL schema."""


class IdentityAlreadyInitializedError(PersistenceMappingError):
    """Raised when a different Origin Identity would overwrite an existing one."""


class IdentityFacetBackfillConflictError(PersistenceMappingError):
    """Raised when a Facet backfill would overwrite existing Facets."""


_IDENTITY_CONTEXT_UNSET = object()


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

    def has_rideable_dragon(self, player_id: str) -> bool:
        """Read the existing Dragon/Bond authorization without mutation."""

        statement = (
            select(PlayerDragonBond.player_id)
            .join(Dragon, Dragon.dragon_id == PlayerDragonBond.dragon_id)
            .where(
                PlayerDragonBond.player_id == player_id,
                PlayerDragonBond.riding_unlocked.is_(True),
                Dragon.taming_state == "tamed",
            )
            .limit(1)
        )
        with self._read_session() as session:
            return session.scalar(statement) is not None

    def list_dragons_at_location(
        self,
        location_id: str,
    ) -> list[dict[str, Any]]:
        """Read committed Dragons at one authored Location without mutation."""

        statement = (
            select(Dragon)
            .where(Dragon.current_location == location_id)
            .order_by(Dragon.dragon_id)
        )
        with self._read_session() as session:
            return [
                _dragon_record(record)
                for record in session.scalars(statement).all()
            ]

    def get_dragon(self, dragon_id: str) -> dict[str, Any] | None:
        """Read one committed Dragon without producing a mutation."""

        with self._read_session() as session:
            record = session.get(Dragon, dragon_id)
            return _dragon_record(record) if record is not None else None

    def list_recent_dragon_encounter_decisions(
        self,
        player_id: str,
        *,
        location_id: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Read the bounded recent D3 decision history without writing it."""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise PersistenceMappingError("Encounter history limit must be positive.")
        statement = select(InteractionEvent).where(
            InteractionEvent.player_id == player_id,
            InteractionEvent.event_type == "dragon_encounter_decision",
        )
        if location_id is not None:
            statement = statement.where(
                InteractionEvent.location_id == location_id
            )
        statement = statement.order_by(
            InteractionEvent.recorded_at.desc(),
            InteractionEvent.event_id.desc(),
        ).limit(limit)
        with self._read_session() as session:
            return [
                _interaction_event_record(record)
                for record in session.scalars(statement).all()
            ]

    def get_grounded_dragon_encounter_by_source(
        self,
        *,
        player_id: str,
        source_interaction_event_id: str,
    ) -> dict[str, Any] | None:
        """Read an already committed first encounter for idempotent retry."""

        statement = (
            select(DragonEvent)
            .where(
                DragonEvent.player_id == player_id,
                DragonEvent.source_interaction_event_id
                == source_interaction_event_id,
                DragonEvent.event_type == "dragon_first_encounter",
            )
            .order_by(DragonEvent.event_id)
            .limit(2)
        )
        with self._read_session() as session:
            events = session.scalars(statement).all()
            if len(events) > 1:
                raise PersistenceMappingError(
                    "Source encounter maps to multiple first Dragon events."
                )
            if not events:
                return None
            dragon = session.get(Dragon, events[0].dragon_id)
            if dragon is None:
                raise PersistenceMappingError(
                    "Grounded Dragon Event references a missing Dragon."
                )
            return {
                "status": "already_applied",
                "dragon": _dragon_record(dragon),
                "dragon_event": _dragon_event_record(events[0]),
            }

    def commit_grounded_dragon_encounter(
        self,
        *,
        player_id: str,
        source_interaction_event_id: str,
        dragon: Mapping[str, Any],
        dragon_event_id: str,
        encounter_outcome: str,
        event_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically insert one Dragon and its grounded first encounter event."""

        dragon_fields = {
            "dragon_id",
            "archetype_id",
            "name",
            "sex",
            "age_stage",
            "appearance",
            "temperament_traits",
            "current_location",
            "health_state",
            "energy",
            "hunger",
            "alertness",
            "behavior_state",
            "taming_state",
        }
        if set(dragon) != dragon_fields:
            raise PersistenceMappingError("Grounded Dragon fields are invalid.")
        if encounter_outcome not in {"sighting", "direct_encounter"}:
            raise PersistenceMappingError("Grounded encounter outcome is invalid.")
        if not isinstance(event_payload, Mapping):
            raise PersistenceMappingError("Dragon Event payload must be an object.")

        with self._write_session() as session:
            source = session.scalar(
                select(InteractionEvent)
                .where(
                    InteractionEvent.event_id == source_interaction_event_id
                )
                .with_for_update()
            )
            if source is None:
                raise PersistenceMappingError(
                    "Source Interaction Event does not exist."
                )
            if source.event_type != "free_world_action":
                raise PersistenceMappingError(
                    "Dragon encounter source must be a free_world_action event."
                )
            if source.player_id != player_id:
                raise PersistenceMappingError(
                    "Dragon encounter source belongs to another Player."
                )
            expected_location = source.location_id
            source_payload = source.event_payload
            if isinstance(source_payload, Mapping):
                world_effect = source_payload.get("world_effect")
                if isinstance(world_effect, Mapping) and isinstance(
                    world_effect.get("current_location"), str
                ):
                    expected_location = world_effect["current_location"]
            if dragon["current_location"] != expected_location:
                raise PersistenceMappingError(
                    "Grounded Dragon Location does not match the source action."
                )

            existing_events = session.scalars(
                select(DragonEvent)
                .where(
                    DragonEvent.source_interaction_event_id
                    == source_interaction_event_id,
                    DragonEvent.event_type == "dragon_first_encounter",
                )
                .order_by(DragonEvent.event_id)
                .limit(2)
            ).all()
            if len(existing_events) > 1:
                raise PersistenceMappingError(
                    "Source encounter maps to multiple first Dragon events."
                )
            if existing_events:
                existing_event = existing_events[0]
                if existing_event.player_id != player_id:
                    raise PersistenceMappingError(
                        "Existing source encounter belongs to another Player."
                    )
                existing_dragon = session.get(Dragon, existing_event.dragon_id)
                if existing_dragon is None:
                    raise PersistenceMappingError(
                        "Grounded Dragon Event references a missing Dragon."
                    )
                return {
                    "status": "already_applied",
                    "dragon": _dragon_record(existing_dragon),
                    "dragon_event": _dragon_event_record(existing_event),
                }

            if session.get(Dragon, dragon["dragon_id"]) is not None:
                raise PersistenceMappingError(
                    "Deterministic Dragon ID already exists without its source event."
                )

            dragon_record = Dragon(
                dragon_id=dragon["dragon_id"],
                archetype_id=dragon["archetype_id"],
                name=dragon["name"],
                sex=dragon["sex"],
                age_stage=dragon["age_stage"],
                appearance=dict(dragon["appearance"]),
                temperament_traits=list(dragon["temperament_traits"]),
                current_location=dragon["current_location"],
                health_state=dragon["health_state"],
                energy=dragon["energy"],
                hunger=dragon["hunger"],
                alertness=dragon["alertness"],
                behavior_state=dragon["behavior_state"],
                taming_state=dragon["taming_state"],
            )
            session.add(dragon_record)
            session.flush()

            dragon_event = DragonEvent(
                event_id=dragon_event_id,
                event_type="dragon_first_encounter",
                dragon_id=dragon_record.dragon_id,
                player_id=player_id,
                source_interaction_event_id=source_interaction_event_id,
                world_day=source.world_day,
                world_hour=source.world_hour,
                location_id=dragon_record.current_location,
                milestone_key="first_encounter",
                event_payload={
                    **dict(event_payload),
                    "encounter_outcome": encounter_outcome,
                },
            )
            session.add(dragon_event)
            session.flush()
            session.refresh(dragon_record)
            session.refresh(dragon_event)
            return {
                "status": "committed",
                "dragon": _dragon_record(dragon_record),
                "dragon_event": _dragon_event_record(dragon_event),
            }

    def commit_free_action(
        self,
        *,
        player_id: str,
        expected_current_location: str,
        expected_goals: Sequence[str],
        state_changes: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically commit one allowlisted D2 effect and Interaction Event."""

        if not set(state_changes).issubset({"current_location", "goals"}):
            raise PersistenceMappingError("D2 state change is outside the allowlist.")
        world_context = _required_mapping(event, "world_context")
        event_payload = _required_mapping(event, "event_payload")
        with self._write_session() as session:
            player_state = session.scalar(
                select(PlayerState)
                .where(PlayerState.player_id == player_id)
                .with_for_update()
            )
            if player_state is None:
                raise PersistenceMappingError(f"PlayerState does not exist: {player_id}")
            if (
                player_state.current_location != expected_current_location
                or list(player_state.goals) != list(expected_goals)
            ):
                raise PersistenceMappingError("PlayerState changed before D2 commit.")

            new_location = state_changes.get("current_location")
            if new_location is not None:
                if not isinstance(new_location, str) or not new_location:
                    raise PersistenceMappingError("current_location change is invalid.")
                player_state.current_location = new_location
            new_goals = state_changes.get("goals")
            if new_goals is not None:
                if not isinstance(new_goals, list) or not all(
                    isinstance(goal, str) and goal.strip() for goal in new_goals
                ):
                    raise PersistenceMappingError("goals change is invalid.")
                player_state.goals = list(new_goals)

            record = InteractionEvent(
                event_id=event["event_id"],
                event_type=event["event_type"],
                player_id=player_id,
                npc_id=None,
                world_day=world_context["world_day"],
                world_hour=world_context["world_hour"],
                location_id=world_context["location_id"],
                player_utterance=event["player_utterance"],
                npc_response=None,
                topic=None,
                player_claims=list(event.get("player_claims", [])),
                memory_candidate=None,
                relationship_signal=None,
                event_payload=dict(event_payload),
            )
            session.add(record)
            session.flush()
            session.refresh(record)
            return {
                "player_state": _player_state_record(player_state),
                "interaction_event": _interaction_event_record(record),
            }

    def upsert_player_state(
        self,
        *,
        player_id: str,
        current_location: str,
        inventory: Sequence[Any],
        goals: Sequence[str],
        identity_context: Mapping[str, Any] | None | object = (
            _IDENTITY_CONTEXT_UNSET
        ),
    ) -> dict[str, Any]:
        """Upsert state without clearing an omitted Open Identity Context."""

        with self._write_session() as session:
            record = session.get(PlayerState, player_id)
            if record is None:
                record = PlayerState(
                    player_id=player_id,
                    current_location=current_location,
                    inventory=list(inventory),
                    goals=list(goals),
                    identity_context=(
                        None
                        if identity_context is _IDENTITY_CONTEXT_UNSET
                        else _identity_context_value(identity_context)
                    ),
                )
                session.add(record)
            else:
                record.current_location = current_location
                record.inventory = list(inventory)
                record.goals = list(goals)
                if identity_context is not _IDENTITY_CONTEXT_UNSET:
                    record.identity_context = _identity_context_value(
                        identity_context
                    )
            session.flush()
            return _player_state_record(record)

    def commit_initial_identity(
        self,
        *,
        player_id: str,
        display_name: str | None,
        traits: Sequence[str],
        identity_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically initialize one already-existing Player's Origin Identity.

        The caller supplies validated B1/B2-derived data. Rows are locked so two
        concurrent initializations cannot both observe an uninitialized state.
        This method never creates a missing Player or PlayerState.
        """

        normalized_name = (
            display_name.strip()
            if isinstance(display_name, str) and display_name.strip()
            else None
        )
        normalized_traits = list(traits)
        normalized_context = dict(identity_context)

        with self._write_session() as session:
            player = session.scalar(
                select(Player)
                .where(Player.player_id == player_id)
                .with_for_update()
            )
            if player is None:
                raise PersistenceMappingError(
                    f"Player does not exist: {player_id}"
                )

            player_state = session.scalar(
                select(PlayerState)
                .where(PlayerState.player_id == player_id)
                .with_for_update()
            )
            if player_state is None:
                raise PersistenceMappingError(
                    f"PlayerState does not exist: {player_id}"
                )

            existing_context = player_state.identity_context
            if existing_context is not None:
                same_context = dict(existing_context) == normalized_context
                same_traits = list(player.traits) == normalized_traits
                same_name = (
                    normalized_name is None or player.name == normalized_name
                )
                if (
                    existing_context.get("identity_initialized") is True
                    and same_context
                    and same_traits
                    and same_name
                ):
                    return {
                        "status": "already_applied",
                        "player": _player_record(player),
                        "player_state": _player_state_record(player_state),
                    }
                raise IdentityAlreadyInitializedError(
                    "identity_already_initialized"
                )

            if normalized_name is not None:
                player.name = normalized_name
            player.traits = normalized_traits
            player_state.identity_context = normalized_context
            session.flush()

            return {
                "status": "committed",
                "player": _player_record(player),
                "player_state": _player_state_record(player_state),
            }

    def backfill_identity_facets(
        self,
        *,
        player_id: str,
        identity_facets: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically add v0.2 Facets to one initialized v0.1 Identity.

        This narrow compatibility operation never reinitializes identity and
        never changes any existing Identity Context key.
        """

        normalized_facets = _identity_facets_value(identity_facets)
        with self._write_session() as session:
            player_state = session.scalar(
                select(PlayerState)
                .where(PlayerState.player_id == player_id)
                .with_for_update()
            )
            if player_state is None:
                raise PersistenceMappingError(
                    f"PlayerState does not exist: {player_id}"
                )

            existing_context = player_state.identity_context
            if not isinstance(existing_context, Mapping) or (
                existing_context.get("identity_initialized") is not True
            ):
                raise PersistenceMappingError(
                    "Identity Facets can only backfill an initialized Identity."
                )

            existing_facets = existing_context.get(
                "identity_facets",
                _IDENTITY_CONTEXT_UNSET,
            )
            if existing_facets is not _IDENTITY_CONTEXT_UNSET:
                if _identity_facets_value(existing_facets) == normalized_facets:
                    return {
                        "status": "already_applied",
                        "player_state": _player_state_record(player_state),
                    }
                raise IdentityFacetBackfillConflictError(
                    "identity_facets_already_exist"
                )

            updated_context = dict(existing_context)
            updated_context["identity_facets"] = normalized_facets
            player_state.identity_context = updated_context
            session.flush()
            return {
                "status": "committed",
                "player_state": _player_state_record(player_state),
            }

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

    def get_interaction_event(
        self,
        event_id: str,
    ) -> dict[str, Any] | None:
        """Read one persisted Interaction Event without producing a mutation."""

        with self._read_session() as session:
            record = session.get(InteractionEvent, event_id)
            return (
                _interaction_event_record(record)
                if record is not None
                else None
            )


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


def _dragon_record(record: Dragon) -> dict[str, Any]:
    return {
        "dragon_id": record.dragon_id,
        "archetype_id": record.archetype_id,
        "name": record.name,
        "sex": record.sex,
        "age_stage": record.age_stage,
        "appearance": dict(record.appearance),
        "temperament_traits": list(record.temperament_traits),
        "current_location": record.current_location,
        "health_state": record.health_state,
        "energy": record.energy,
        "hunger": record.hunger,
        "alertness": record.alertness,
        "behavior_state": record.behavior_state,
        "taming_state": record.taming_state,
    }


def _dragon_event_record(record: DragonEvent) -> dict[str, Any]:
    return {
        "event_id": record.event_id,
        "event_type": record.event_type,
        "dragon_id": record.dragon_id,
        "player_id": record.player_id,
        "source_interaction_event_id": record.source_interaction_event_id,
        "world_day": record.world_day,
        "world_hour": record.world_hour,
        "location_id": record.location_id,
        "milestone_key": record.milestone_key,
        "event_payload": dict(record.event_payload),
        "recorded_at": record.recorded_at.isoformat(),
    }


def _player_state_record(record: PlayerState) -> dict[str, Any]:
    return {
        "player_id": record.player_id,
        "current_location": record.current_location,
        "inventory": list(record.inventory),
        "goals": list(record.goals),
        "identity_context": (
            dict(record.identity_context)
            if record.identity_context is not None
            else None
        ),
    }


def _identity_context_value(
    value: Mapping[str, Any] | None | object,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PersistenceMappingError("identity_context must be an object or null.")
    return dict(value)


def _identity_facets_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "narrative_species",
        "occupations",
    }:
        raise PersistenceMappingError(
            "identity_facets must contain only narrative_species and occupations."
        )

    species = value.get("narrative_species")
    if species is not None:
        if not isinstance(species, str) or not species.strip():
            raise PersistenceMappingError(
                "identity_facets.narrative_species must be a non-empty string "
                "or null."
            )
        species = species.strip()

    occupations = value.get("occupations")
    if not isinstance(occupations, list) or not all(
        isinstance(occupation, str) and occupation.strip()
        for occupation in occupations
    ):
        raise PersistenceMappingError(
            "identity_facets.occupations must be an array of non-empty strings."
        )
    normalized_occupations = [occupation.strip() for occupation in occupations]
    if len(normalized_occupations) > 3:
        raise PersistenceMappingError(
            "identity_facets.occupations must contain at most 3 items."
        )
    if len(set(normalized_occupations)) != len(normalized_occupations):
        raise PersistenceMappingError(
            "identity_facets.occupations must be unique."
        )
    if (species is not None and len(species) > 80) or any(
        len(occupation) > 80 for occupation in normalized_occupations
    ):
        raise PersistenceMappingError(
            "identity_facets must contain short labels."
        )
    return {
        "narrative_species": species,
        "occupations": normalized_occupations,
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
