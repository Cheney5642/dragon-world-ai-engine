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

import uuid
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

_GROUNDED_DRAGON_INTERACTION_EVENTS = {
    "dragon_accepts_food",
    "dragon_allows_close_presence",
    "dragon_allows_touch",
    "player_heals_dragon",
    "player_rescues_dragon",
    "dragon_rescues_player",
    "shared_danger_survived",
    "dragon_tamed",
}


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

    def get_player_dragon_bond(
        self,
        *,
        player_id: str,
        dragon_id: str,
    ) -> dict[str, Any] | None:
        """Read one committed Player/Dragon relationship without mutation."""

        with self._read_session() as session:
            record = session.get(PlayerDragonBond, (player_id, dragon_id))
            return (
                _player_dragon_bond_state(record)
                if record is not None
                else None
            )

    def list_committed_dragon_interactions(
        self,
        *,
        player_id: str,
        dragon_id: str,
    ) -> list[dict[str, Any]]:
        """Read effective, final D4 interaction history for one Player/Dragon."""

        with self._read_session() as session:
            return _committed_dragon_interactions(
                session,
                player_id=player_id,
                dragon_id=dragon_id,
            )

    def commit_dragon_interaction(
        self,
        *,
        player_id: str,
        dragon_id: str,
        source_interaction_event_id: str,
    ) -> dict[str, Any]:
        """Re-resolve and atomically apply one grounded D4 interaction.

        The source event supplies the frozen D2 Structured Action. Relationship
        deltas, anti-farming, categories, and taming preview are always rebuilt
        from rows locked in this transaction; callers cannot submit them.
        """

        from core.dragon_interaction_resolution import (
            BOND_BOUNDS,
            POSITIVE_CATEGORIES,
            resolve_dragon_interaction,
        )

        with self._write_session() as session:
            source = session.scalar(
                select(InteractionEvent)
                .where(InteractionEvent.event_id == source_interaction_event_id)
                .with_for_update()
            )
            if source is None:
                raise PersistenceMappingError(
                    "Source Interaction Event does not exist."
                )
            if source.event_type != "free_world_action":
                raise PersistenceMappingError(
                    "Dragon interaction source must be a free_world_action event."
                )
            if source.player_id != player_id:
                raise PersistenceMappingError(
                    "Dragon interaction source belongs to another Player."
                )

            source_payload = source.event_payload
            if not isinstance(source_payload, Mapping):
                raise PersistenceMappingError(
                    "Dragon interaction source payload is invalid."
                )
            existing = source_payload.get("dragon_interaction")
            if existing is not None:
                return _already_applied_dragon_interaction(
                    existing,
                    player_id=player_id,
                    dragon_id=dragon_id,
                    source_interaction_event_id=source_interaction_event_id,
                )

            structured_action = source_payload.get("structured_action")
            d2_resolution = source_payload.get("resolution")
            if not isinstance(structured_action, Mapping) or not isinstance(
                d2_resolution, Mapping
            ):
                raise PersistenceMappingError(
                    "Dragon interaction source lacks the formal D2 result."
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
            dragon = session.scalar(
                select(Dragon)
                .where(Dragon.dragon_id == dragon_id)
                .with_for_update()
            )
            if dragon is None:
                raise PersistenceMappingError(f"Dragon does not exist: {dragon_id}")
            _validate_dragon_interaction_target(
                structured_action,
                d2_resolution,
                dragon,
            )

            bond = session.scalar(
                select(PlayerDragonBond)
                .where(
                    PlayerDragonBond.player_id == player_id,
                    PlayerDragonBond.dragon_id == dragon_id,
                )
                .with_for_update()
            )
            bond_snapshot = (
                _player_dragon_bond_record(bond)
                if bond is not None
                else _empty_player_dragon_bond(player_id, dragon_id)
            )
            history = _committed_dragon_interactions(
                session,
                player_id=player_id,
                dragon_id=dragon_id,
                exclude_event_id=source_interaction_event_id,
            )
            positive_categories = _grounded_positive_categories(
                history,
                allowed=POSITIVE_CATEGORIES,
            )

            resolution = resolve_dragon_interaction(
                structured_action,
                source_interaction_event_id=source_interaction_event_id,
                player_id=player_id,
                dragon_id=dragon_id,
                dragon=_dragon_record(dragon),
                player_location=player_state.current_location,
                bond=bond_snapshot,
                recent_history=history,
                positive_categories=positive_categories,
                player_inventory=list(player_state.inventory),
            )

            before = {
                field: bond_snapshot[field]
                for field in BOND_BOUNDS
            }
            before["taming_state"] = dragon.taming_state
            proposed = resolution["state_changes"]
            may_apply = resolution["status"] in {"success", "partial"}
            applied_deltas: dict[str, int] = {}
            after_values: dict[str, int] = {}
            for field, (minimum, maximum) in BOND_BOUNDS.items():
                proposed_delta = proposed[f"{field}_delta"] if may_apply else 0
                after_value = min(
                    maximum,
                    max(minimum, bond_snapshot[field] + proposed_delta),
                )
                after_values[field] = after_value
                applied_deltas[field] = after_value - bond_snapshot[field]

            if resolution["interaction_type"] == "offer_food" and may_apply:
                player_state.inventory = _consume_grounded_food_item(
                    player_state.inventory
                )

            has_relationship_change = any(applied_deltas.values())
            if bond is None and has_relationship_change:
                bond = PlayerDragonBond(
                    player_id=player_id,
                    dragon_id=dragon_id,
                    familiarity=0,
                    trust=0,
                    fear=0,
                    bond=0,
                    riding_unlocked=False,
                    last_significant_event_id=None,
                )
                session.add(bond)
            if bond is not None and has_relationship_change:
                bond.familiarity = after_values["familiarity"]
                bond.trust = after_values["trust"]
                bond.fear = after_values["fear"]
                bond.bond = after_values["bond"]

            current_category = resolution["positive_category"]
            if (
                may_apply
                and current_category in POSITIVE_CATEGORIES
                and resolution["anti_farming"] in {"full", "familiarity_only"}
            ):
                positive_categories = sorted(
                    {*positive_categories, current_category}
                )

            may_advance_taming = (
                may_apply
                and resolution["relationship_effect"] == "positive"
                and resolution["positive_category"] in POSITIVE_CATEGORIES
            )
            next_state = (
                resolution["next_taming_state_preview"]
                if may_advance_taming
                else None
            )
            transition = _validated_taming_transition(
                dragon.taming_state,
                next_state,
            )
            if transition is not None:
                dragon.taming_state = transition["to"]

            after = dict(after_values)
            after["taming_state"] = dragon.taming_state
            dragon_event: DragonEvent | None = None
            grounded_event_type = (
                "dragon_tamed"
                if transition is not None and transition["to"] == "tamed"
                else resolution["significant_event"]
            )
            if grounded_event_type is not None:
                if grounded_event_type not in _GROUNDED_DRAGON_INTERACTION_EVENTS:
                    raise PersistenceMappingError(
                        "Dragon interaction significant event is not grounded."
                    )
                event_id = _stable_dragon_interaction_event_id(
                    source_interaction_event_id,
                    grounded_event_type,
                )
                if session.get(DragonEvent, event_id) is not None:
                    raise PersistenceMappingError(
                        "Dragon interaction event exists without an applied source."
                    )
                dragon_event = DragonEvent(
                    event_id=event_id,
                    event_type=grounded_event_type,
                    dragon_id=dragon_id,
                    player_id=player_id,
                    source_interaction_event_id=source_interaction_event_id,
                    world_day=source.world_day,
                    world_hour=source.world_hour,
                    location_id=dragon.current_location,
                    milestone_key=(
                        "tamed" if grounded_event_type == "dragon_tamed" else None
                    ),
                    event_payload={
                        "interaction_type": resolution["interaction_type"],
                        "before": before,
                        "after": after,
                    },
                )
                session.add(dragon_event)
                session.flush()
                if bond is not None:
                    bond.last_significant_event_id = event_id

            formal_result = {
                "dragon_id": dragon_id,
                "player_id": player_id,
                "source_interaction_event_id": source_interaction_event_id,
                "status": resolution["status"],
                "interaction_type": resolution["interaction_type"],
                "dragon_reaction": resolution["dragon_reaction"],
                "relationship_effect": resolution["relationship_effect"],
                "reason_code": resolution["reason_code"],
                "positive_category": resolution["positive_category"],
                "anti_farming": resolution["anti_farming"],
                "applied_deltas": applied_deltas,
                "before": before,
                "after": after,
                "taming_transition": transition,
                "significant_event_id": (
                    dragon_event.event_id if dragon_event is not None else None
                ),
                "positive_categories": positive_categories,
                "riding_unlocked": (
                    bond.riding_unlocked if bond is not None else False
                ),
                "is_final": True,
            }
            updated_payload = dict(source_payload)
            updated_payload["dragon_interaction"] = formal_result
            source.event_payload = updated_payload
            session.flush()
            session.refresh(source)
            session.refresh(dragon)
            if bond is not None:
                session.refresh(bond)

            return {
                "status": "applied",
                "dragon_id": dragon_id,
                "bond_state": (
                    _player_dragon_bond_state(bond)
                    if bond is not None
                    else _empty_player_dragon_bond_state()
                ),
                "taming_state": dragon.taming_state,
                "taming_transition": transition,
                "applied_deltas": applied_deltas,
                "positive_categories": positive_categories,
                "dragon_event_id": (
                    dragon_event.event_id if dragon_event is not None else None
                ),
                "source_interaction_event_id": source_interaction_event_id,
            }

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
            InteractionEvent.event_type == "free_world_action",
            InteractionEvent.event_payload.op("?")("dragon_encounter_decision"),
        )
        if location_id is not None:
            statement = statement.where(
                InteractionEvent.event_payload[
                    "dragon_encounter_location_id"
                ].astext
                == location_id
            )
        statement = statement.order_by(
            InteractionEvent.recorded_at.desc(),
            InteractionEvent.event_id.desc(),
        ).limit(limit)
        with self._read_session() as session:
            history: list[dict[str, Any]] = []
            for record in session.scalars(statement).all():
                persisted = _interaction_event_record(record)
                payload = persisted.get("event_payload")
                if not isinstance(payload, Mapping):
                    continue
                decision = payload.get("dragon_encounter_decision")
                if not isinstance(decision, Mapping):
                    continue
                # D3-B consumes only the bounded decision projection. The full
                # source event remains available through get_interaction_event().
                persisted["event_payload"] = {
                    "encounter_decision": dict(decision)
                }
                history.append(persisted)
            return history

    def record_dragon_encounter_decision(
        self,
        *,
        player_id: str,
        source_interaction_event_id: str,
        encounter_location_id: str,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Idempotently attach one D3 decision to its D2 source event."""

        if not encounter_location_id:
            raise PersistenceMappingError("Encounter Location is invalid.")
        decision_value = _dragon_encounter_decision_value(decision)
        with self._write_session() as session:
            source = session.scalar(
                select(InteractionEvent)
                .where(InteractionEvent.event_id == source_interaction_event_id)
                .with_for_update()
            )
            _validate_dragon_encounter_source(source, player_id)
            payload = dict(source.event_payload or {})
            existing = payload.get("dragon_encounter_decision")
            existing_location = payload.get("dragon_encounter_location_id")
            if existing is not None:
                if not isinstance(existing, Mapping) or dict(existing) != decision_value:
                    raise PersistenceMappingError(
                        "Source Interaction Event already has another Dragon decision."
                    )
                if existing_location != encounter_location_id:
                    raise PersistenceMappingError(
                        "Source Interaction Event has another encounter Location."
                    )
                return _interaction_event_record(source)

            payload["dragon_encounter_decision"] = decision_value
            payload["dragon_encounter_location_id"] = encounter_location_id
            source.event_payload = payload
            session.flush()
            session.refresh(source)
            return _interaction_event_record(source)

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
            _validate_dragon_encounter_source(source, player_id)
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
            source_payload_value = dict(source.event_payload or {})
            existing_source_decision = source_payload_value.get(
                "dragon_encounter_decision"
            )
            provisional_decision = event_payload.get("provisional_decision")
            if provisional_decision is None and isinstance(
                existing_source_decision, Mapping
            ):
                provisional_decision = existing_source_decision
            provisional_value = (
                _dragon_encounter_decision_value(provisional_decision)
                if provisional_decision is not None
                else None
            )
            if provisional_value is not None:
                if (
                    provisional_value["is_final"] is not False
                    or provisional_value["requires_new_dragon"] is not True
                ):
                    raise PersistenceMappingError(
                        "Dragon creation requires a provisional encounter decision."
                    )
                if existing_source_decision is not None and (
                    not isinstance(existing_source_decision, Mapping)
                    or dict(existing_source_decision) != provisional_value
                ):
                    existing_value = _dragon_encounter_decision_value(
                        existing_source_decision
                    )
                    if not (
                        existing_value["is_final"] is True
                        and existing_value["dragon_id"] == dragon["dragon_id"]
                        and existing_value["outcome"]
                        == provisional_value["outcome"]
                        and existing_value["context_score"]
                        == provisional_value["context_score"]
                        and float(existing_value["roll"])
                        == float(provisional_value["roll"])
                    ):
                        raise PersistenceMappingError(
                            "Source Interaction Event Dragon decision conflicts."
                        )
            existing_encounter_location = source_payload_value.get(
                "dragon_encounter_location_id"
            )
            if existing_encounter_location not in {
                None,
                dragon["current_location"],
            }:
                raise PersistenceMappingError(
                    "Source Interaction Event encounter Location conflicts."
                )

            final_decision = None
            if provisional_value is not None:
                final_decision = dict(provisional_value)
                final_decision.update(
                    {
                        "is_final": True,
                        "requires_new_dragon": False,
                        "dragon_id": dragon["dragon_id"],
                        "reason_code": (
                            "new_dragon_committed_for_"
                            f"{provisional_value['outcome']}"
                        ),
                    }
                )
                final_decision = _dragon_encounter_decision_value(final_decision)

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
                if final_decision is not None:
                    source_payload_value[
                        "dragon_encounter_decision"
                    ] = final_decision
                    source_payload_value[
                        "dragon_encounter_location_id"
                    ] = dragon["current_location"]
                    source.event_payload = source_payload_value
                session.flush()
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
            if final_decision is not None:
                source_payload_value["dragon_encounter_decision"] = final_decision
                source_payload_value[
                    "dragon_encounter_location_id"
                ] = dragon_record.current_location
                source.event_payload = source_payload_value
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


def _validate_dragon_encounter_source(
    source: InteractionEvent | None,
    player_id: str,
) -> None:
    if source is None:
        raise PersistenceMappingError("Source Interaction Event does not exist.")
    if source.event_type != "free_world_action":
        raise PersistenceMappingError(
            "Dragon encounter source must be a free_world_action event."
        )
    if source.player_id != player_id:
        raise PersistenceMappingError(
            "Dragon encounter source belongs to another Player."
        )


def _validate_dragon_interaction_target(
    structured_action: Mapping[str, Any],
    d2_resolution: Mapping[str, Any],
    dragon: Dragon,
) -> None:
    """Bind a formal D2 source to one committed Dragon without guessing."""

    status = d2_resolution.get("status")
    domain_route = d2_resolution.get("domain_route")
    if status not in {"success", "partial", "blocked", "needs_clarification"}:
        raise PersistenceMappingError("D2 source resolution status is invalid.")
    target = structured_action.get("target")
    target_matches = isinstance(target, str) and target.strip().casefold() in {
        dragon.dragon_id.casefold(),
        (dragon.name or "").casefold(),
    }
    if domain_route != "dragon" and not target_matches:
        raise PersistenceMappingError(
            "Source Action is not grounded to the requested Dragon."
        )


def _committed_dragon_interactions(
    session: Session,
    *,
    player_id: str,
    dragon_id: str,
    exclude_event_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(InteractionEvent).where(
        InteractionEvent.player_id == player_id,
        InteractionEvent.event_type == "free_world_action",
        InteractionEvent.event_payload.op("?")("dragon_interaction"),
    )
    if exclude_event_id is not None:
        statement = statement.where(InteractionEvent.event_id != exclude_event_id)
    statement = statement.order_by(
        InteractionEvent.recorded_at.desc(),
        InteractionEvent.event_id.desc(),
    )
    history: list[dict[str, Any]] = []
    for record in session.scalars(statement).all():
        payload = record.event_payload
        if not isinstance(payload, Mapping):
            continue
        interaction = payload.get("dragon_interaction")
        if not isinstance(interaction, Mapping):
            continue
        if (
            interaction.get("is_final") is not True
            or interaction.get("player_id") != player_id
            or interaction.get("dragon_id") != dragon_id
            or interaction.get("status") not in {"success", "partial"}
        ):
            continue
        history.append(
            {
                **dict(interaction),
                "event_id": record.event_id,
                "event_payload": {"dragon_interaction": dict(interaction)},
            }
        )
    return history


def _grounded_positive_categories(
    history: Sequence[Mapping[str, Any]],
    *,
    allowed: set[str],
) -> list[str]:
    categories = {
        record["positive_category"]
        for record in history
        if record.get("relationship_effect") == "positive"
        and record.get("positive_category") in allowed
        and record.get("anti_farming") in {"full", "familiarity_only"}
    }
    return sorted(categories)


def _empty_player_dragon_bond(
    player_id: str,
    dragon_id: str,
) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "dragon_id": dragon_id,
        **_empty_player_dragon_bond_state(),
        "last_significant_event_id": None,
    }


def _empty_player_dragon_bond_state() -> dict[str, Any]:
    return {
        "familiarity": 0,
        "trust": 0,
        "fear": 0,
        "bond": 0,
        "riding_unlocked": False,
    }


def _consume_grounded_food_item(inventory: Sequence[Any]) -> list[Any]:
    """Decrement one explicit food item; ambiguous inventory fails closed."""

    updated = [dict(item) if isinstance(item, Mapping) else item for item in inventory]
    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(updated):
        if not isinstance(item, dict):
            continue
        category = item.get("category", item.get("type"))
        quantity = item.get("quantity")
        if (
            category == "food"
            and isinstance(item.get("item_id"), str)
            and item["item_id"].strip()
            and isinstance(quantity, int)
            and not isinstance(quantity, bool)
            and quantity > 0
        ):
            candidates.append((index, item))
    if len(candidates) != 1:
        raise PersistenceMappingError(
            "Food consumption requires exactly one explicit consumable item."
        )
    index, item = candidates[0]
    if item["quantity"] == 1:
        del updated[index]
    else:
        item["quantity"] -= 1
    return updated


def _validated_taming_transition(
    current_state: str,
    next_state: Any,
) -> dict[str, str] | None:
    if next_state is None:
        return None
    adjacent = {
        "wild": "tolerant",
        "tolerant": "bonding",
        "bonding": "tamed",
        "tamed": None,
    }
    if current_state not in adjacent or adjacent[current_state] != next_state:
        raise PersistenceMappingError(
            "Dragon taming transition is not an adjacent grounded step."
        )
    return {"from": current_state, "to": next_state}


def _stable_dragon_interaction_event_id(
    source_interaction_event_id: str,
    event_type: str,
) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"dragon-world:{event_type}:{source_interaction_event_id}",
    )
    return f"dragon_event_{value.hex}"


def _already_applied_dragon_interaction(
    value: Any,
    *,
    player_id: str,
    dragon_id: str,
    source_interaction_event_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("is_final") is not True:
        raise PersistenceMappingError(
            "Source Interaction Event has an incomplete Dragon interaction."
        )
    if (
        value.get("player_id") != player_id
        or value.get("dragon_id") != dragon_id
        or value.get("source_interaction_event_id")
        != source_interaction_event_id
    ):
        raise PersistenceMappingError(
            "Source Interaction Event has another Dragon interaction."
        )
    after = value.get("after")
    deltas = value.get("applied_deltas")
    categories = value.get("positive_categories", [])
    if not isinstance(after, Mapping) or not isinstance(deltas, Mapping):
        raise PersistenceMappingError(
            "Applied Dragon interaction read-back is invalid."
        )
    if not isinstance(categories, list):
        raise PersistenceMappingError(
            "Applied Dragon interaction categories are invalid."
        )
    return {
        "status": "already_applied",
        "dragon_id": dragon_id,
        "bond_state": {
            "familiarity": after["familiarity"],
            "trust": after["trust"],
            "fear": after["fear"],
            "bond": after["bond"],
            "riding_unlocked": bool(value.get("riding_unlocked", False)),
        },
        "taming_state": after["taming_state"],
        "taming_transition": value.get("taming_transition"),
        "applied_deltas": dict(deltas),
        "positive_categories": list(categories),
        "dragon_event_id": value.get("significant_event_id"),
        "source_interaction_event_id": source_interaction_event_id,
    }


def _dragon_encounter_decision_value(value: Any) -> dict[str, Any]:
    required = {
        "outcome",
        "is_final",
        "requires_new_dragon",
        "dragon_id",
        "reason_code",
        "context_score",
        "roll",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise PersistenceMappingError("Dragon encounter decision fields are invalid.")
    outcome = value["outcome"]
    if outcome not in {"none", "trace", "sighting", "direct_encounter"}:
        raise PersistenceMappingError("Dragon encounter outcome is invalid.")
    if not isinstance(value["is_final"], bool) or not isinstance(
        value["requires_new_dragon"], bool
    ):
        raise PersistenceMappingError("Dragon encounter finality is invalid.")
    dragon_id = value["dragon_id"]
    if dragon_id is not None and (
        not isinstance(dragon_id, str) or not dragon_id
    ):
        raise PersistenceMappingError("Dragon encounter dragon_id is invalid.")
    if not isinstance(value["reason_code"], str) or not value["reason_code"]:
        raise PersistenceMappingError("Dragon encounter reason_code is invalid.")
    context_score = value["context_score"]
    if isinstance(context_score, bool) or not isinstance(context_score, int):
        raise PersistenceMappingError("Dragon encounter context_score is invalid.")
    roll = value["roll"]
    if isinstance(roll, bool) or not isinstance(roll, (int, float)):
        raise PersistenceMappingError("Dragon encounter roll is invalid.")
    if not 0.0 <= float(roll) <= 1.0:
        raise PersistenceMappingError("Dragon encounter roll is outside 0..1.")
    if outcome in {"none", "trace"}:
        if (
            value["is_final"] is not True
            or value["requires_new_dragon"] is not False
            or dragon_id is not None
        ):
            raise PersistenceMappingError(
                "none/trace encounter decision finality is invalid."
            )
    elif value["is_final"] is True:
        if value["requires_new_dragon"] is not False or dragon_id is None:
            raise PersistenceMappingError(
                "Final Dragon encounter must reference a committed Dragon."
            )
    elif value["requires_new_dragon"] is not True or dragon_id is not None:
        raise PersistenceMappingError(
            "Provisional Dragon encounter must request a new Dragon."
        )
    return dict(value)


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


def _player_dragon_bond_record(record: PlayerDragonBond) -> dict[str, Any]:
    return {
        "player_id": record.player_id,
        "dragon_id": record.dragon_id,
        "familiarity": record.familiarity,
        "trust": record.trust,
        "fear": record.fear,
        "bond": record.bond,
        "riding_unlocked": record.riding_unlocked,
        "last_significant_event_id": record.last_significant_event_id,
    }


def _player_dragon_bond_state(record: PlayerDragonBond) -> dict[str, Any]:
    value = _player_dragon_bond_record(record)
    return {
        key: value[key]
        for key in ("familiarity", "trust", "fear", "bond", "riding_unlocked")
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
