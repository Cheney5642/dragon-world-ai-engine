"""SQLAlchemy 2.x mappings for the Frozen PostgreSQL Schema Design v0.1.

These mappings define metadata only. They never create tables or migrate the
existing JSON stores. ORM relationships are intentionally deferred; v0.1
prioritizes database columns, keys, constraints, and delete policies.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Player(Base):
    """Stable player identity; mutable state belongs to player_states."""

    __tablename__ = "players"
    __table_args__ = (
        CheckConstraint(
            "species IN ('human', 'dragon')",
            name="ck_players_species",
        ),
        CheckConstraint(
            "jsonb_typeof(traits) = 'array'",
            name="ck_players_traits_json_array",
        ),
        CheckConstraint(
            "jsonb_array_length(traits) <= 5",
            name="ck_players_traits_max_items",
        ),
    )

    player_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    species: Mapped[str | None] = mapped_column(Text, nullable=True)
    occupation: Mapped[str | None] = mapped_column(Text, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    traits: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class PlayerState(Base):
    """Current mutable state for exactly one player."""

    __tablename__ = "player_states"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(inventory) = 'array'",
            name="ck_player_states_inventory_json_array",
        ),
        CheckConstraint(
            "jsonb_typeof(goals) = 'array'",
            name="ck_player_states_goals_json_array",
        ),
        CheckConstraint(
            "jsonb_array_length(goals) <= 5",
            name="ck_player_states_goals_max_items",
        ),
    )

    player_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="CASCADE"),
        primary_key=True,
    )
    current_location: Mapped[str] = mapped_column(Text, nullable=False)
    inventory: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    goals: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class Npc(Base):
    """NPC registry and runtime state; profile data remains configuration."""

    __tablename__ = "npcs"

    npc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    current_location: Mapped[str] = mapped_column(Text, nullable=False)
    current_activity: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood: Mapped[str | None] = mapped_column(Text, nullable=True)


class NpcMemory(Base):
    """Persistent subjective NPC memory, not verified World Truth."""

    __tablename__ = "npc_memories"
    __table_args__ = (
        UniqueConstraint(
            "npc_id",
            "source_event_id",
            name="uq_npc_memories_npc_source_event",
        ),
        CheckConstraint(
            "memory_type IN ('player_intention', 'player_claim', 'interaction')",
            name="ck_npc_memories_memory_type",
        ),
        CheckConstraint(
            "btrim(content) <> ''",
            name="ck_npc_memories_content_nonempty",
        ),
        CheckConstraint(
            "epistemic_status IN ('reported_by_player', 'observed_interaction')",
            name="ck_npc_memories_epistemic_status",
        ),
        CheckConstraint("world_day >= 1", name="ck_npc_memories_world_day"),
        CheckConstraint(
            "world_hour BETWEEN 0 AND 23",
            name="ck_npc_memories_world_hour",
        ),
        CheckConstraint(
            "char_length(created_from_topic) BETWEEN 1 AND 80",
            name="ck_npc_memories_topic_length",
        ),
    )

    memory_id: Mapped[str] = mapped_column(Text, primary_key=True)
    npc_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("npcs.npc_id", ondelete="RESTRICT"),
        nullable=False,
    )
    player_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_event_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("interaction_events.event_id", ondelete="RESTRICT"),
        nullable=True,
    )
    memory_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(Text, nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    location_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_from_topic: Mapped[str] = mapped_column(Text, nullable=False)
    # "metadata" is reserved by SQLAlchemy Declarative, so only the Python
    # attribute is renamed; the PostgreSQL column remains exactly "metadata".
    memory_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )


class NpcRelationship(Base):
    """Current NPC-by-player relationship and lightweight idempotency audit."""

    __tablename__ = "npc_relationships"
    __table_args__ = (
        CheckConstraint(
            "familiarity BETWEEN 0 AND 3",
            name="ck_npc_relationships_familiarity",
        ),
        CheckConstraint(
            "trust BETWEEN -2 AND 2",
            name="ck_npc_relationships_trust",
        ),
        CheckConstraint(
            "attitude IN ('hostile', 'wary', 'neutral', 'warm')",
            name="ck_npc_relationships_attitude",
        ),
        CheckConstraint(
            "jsonb_typeof(applied_event_ids) = 'array' "
            "AND jsonb_array_length(applied_event_ids) > 0",
            name="ck_npc_relationships_applied_events",
        ),
    )

    player_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    npc_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("npcs.npc_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    familiarity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    trust: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    attitude: Mapped[str] = mapped_column(Text, nullable=False)
    applied_event_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    last_source_event_id: Mapped[str] = mapped_column(Text, nullable=False)


class Dragon(Base):
    """Individual dragon identity and its current runtime state."""

    __tablename__ = "dragons"
    __table_args__ = (
        CheckConstraint(
            "age_stage IN ('hatchling', 'juvenile', 'young_adult', 'adult')",
            name="ck_dragons_age_stage",
        ),
        CheckConstraint(
            "jsonb_typeof(temperament_traits) = 'array'",
            name="ck_dragons_temperament_traits_json_array",
        ),
        CheckConstraint(
            "behavior_state IN "
            "('resting', 'feeding', 'wandering', 'watching', 'avoiding', "
            "'threatening', 'attacking', 'following', 'flying')",
            name="ck_dragons_behavior_state",
        ),
        CheckConstraint(
            "taming_state IN ('wild', 'tolerant', 'bonding', 'tamed')",
            name="ck_dragons_taming_state",
        ),
    )

    dragon_id: Mapped[str] = mapped_column(Text, primary_key=True)
    archetype_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    sex: Mapped[str | None] = mapped_column(Text, nullable=True)
    age_stage: Mapped[str] = mapped_column(Text, nullable=False)
    appearance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    temperament_traits: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    current_location: Mapped[str] = mapped_column(Text, nullable=False)
    health_state: Mapped[str] = mapped_column(Text, nullable=False)
    energy: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    hunger: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    alertness: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    behavior_state: Mapped[str] = mapped_column(Text, nullable=False)
    taming_state: Mapped[str] = mapped_column(Text, nullable=False)


class PlayerDragonBond(Base):
    """Current relationship and riding authorization for one player/dragon."""

    __tablename__ = "player_dragon_bonds"
    __table_args__ = (
        CheckConstraint(
            "familiarity BETWEEN 0 AND 5",
            name="ck_player_dragon_bonds_familiarity",
        ),
        CheckConstraint(
            "trust BETWEEN -3 AND 5",
            name="ck_player_dragon_bonds_trust",
        ),
        CheckConstraint(
            "fear BETWEEN 0 AND 5",
            name="ck_player_dragon_bonds_fear",
        ),
        CheckConstraint(
            "bond BETWEEN 0 AND 5",
            name="ck_player_dragon_bonds_bond",
        ),
    )

    player_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    dragon_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("dragons.dragon_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    familiarity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    trust: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fear: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    bond: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    riding_unlocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    last_significant_event_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("dragon_events.event_id", ondelete="RESTRICT"),
        nullable=True,
    )


class DragonEgg(Base):
    """Acquired dragon egg, incubation state, and one-way hatching link."""

    __tablename__ = "dragon_eggs"
    __table_args__ = (
        CheckConstraint(
            "(hatched_dragon_id IS NULL AND hatched_at IS NULL) OR "
            "(hatched_dragon_id IS NOT NULL AND hatched_at IS NOT NULL)",
            name="ck_dragon_eggs_hatching_fields_together",
        ),
        CheckConstraint(
            "hatched_dragon_id IS NULL OR incubation_state = 'hatched'",
            name="ck_dragon_eggs_hatched_state",
        ),
    )

    egg_id: Mapped[str] = mapped_column(Text, primary_key=True)
    archetype_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquired_by_player_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="RESTRICT"),
        nullable=False,
    )
    incubation_state: Mapped[str] = mapped_column(Text, nullable=False)
    incubation_progress: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    acquired_event_type: Mapped[str] = mapped_column(Text, nullable=False)
    acquired_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    hatched_dragon_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("dragons.dragon_id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    hatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DragonEvent(Base):
    """Append-only grounded dragon event."""

    __tablename__ = "dragon_events"
    __table_args__ = (
        UniqueConstraint(
            "dragon_id",
            "source_interaction_event_id",
            "event_type",
            name="uq_dragon_events_grounded_source",
        ),
        CheckConstraint(
            "event_type IN ("
            "'dragon_first_encounter', 'dragon_accepts_food', "
            "'dragon_allows_close_presence', 'dragon_allows_touch', "
            "'player_heals_dragon', 'player_rescues_dragon', "
            "'dragon_rescues_player', 'shared_danger_survived', "
            "'dragon_tamed', 'dragon_accepts_mount', 'first_shared_flight')",
            name="ck_dragon_events_event_type",
        ),
        CheckConstraint("world_day >= 1", name="ck_dragon_events_world_day"),
        CheckConstraint(
            "world_hour BETWEEN 0 AND 23",
            name="ck_dragon_events_world_hour",
        ),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    dragon_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("dragons.dragon_id", ondelete="RESTRICT"),
        nullable=False,
    )
    player_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_interaction_event_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("interaction_events.event_id", ondelete="RESTRICT"),
        nullable=True,
    )
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    location_id: Mapped[str] = mapped_column(Text, nullable=False)
    milestone_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class InteractionEvent(Base):
    """Append-only player interaction event, including NPC dialogue."""

    __tablename__ = "interaction_events"
    __table_args__ = (
        CheckConstraint(
            "world_day >= 1",
            name="ck_interaction_events_world_day",
        ),
        CheckConstraint(
            "world_hour BETWEEN 0 AND 23",
            name="ck_interaction_events_world_hour",
        ),
        CheckConstraint(
            "btrim(player_utterance) <> ''",
            name="ck_interaction_events_utterance_nonempty",
        ),
        CheckConstraint(
            "topic IS NULL OR char_length(topic) BETWEEN 1 AND 80",
            name="ck_interaction_events_topic_length",
        ),
        CheckConstraint(
            "jsonb_typeof(player_claims) = 'array'",
            name="ck_interaction_events_player_claims_json_array",
        ),
        CheckConstraint(
            "relationship_signal IS NULL OR relationship_signal IN "
            "('none', 'potential_positive', 'potential_negative')",
            name="ck_interaction_events_relationship_signal",
        ),
        CheckConstraint(
            "event_type <> 'npc_dialogue' OR ("
            "npc_id IS NOT NULL AND npc_response IS NOT NULL AND "
            "topic IS NOT NULL AND memory_candidate IS NOT NULL AND "
            "relationship_signal IS NOT NULL)",
            name="ck_interaction_events_npc_dialogue_fields",
        ),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("players.player_id", ondelete="RESTRICT"),
        nullable=False,
    )
    npc_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("npcs.npc_id", ondelete="RESTRICT"),
        nullable=True,
    )
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    location_id: Mapped[str] = mapped_column(Text, nullable=False)
    player_utterance: Mapped[str] = mapped_column(Text, nullable=False)
    npc_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    player_claims: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    memory_candidate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    relationship_signal: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class WorldStateEntry(Base):
    """Current world/global runtime truth keyed by stable state ID."""

    __tablename__ = "world_state_entries"
    __table_args__ = (
        CheckConstraint(
            "(source_event_type IS NULL AND source_event_id IS NULL) OR "
            "(source_event_type IS NOT NULL AND source_event_id IS NOT NULL)",
            name="ck_world_state_entries_source_fields_together",
        ),
    )

    state_id: Mapped[str] = mapped_column(Text, primary_key=True)
    state_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    source_event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
