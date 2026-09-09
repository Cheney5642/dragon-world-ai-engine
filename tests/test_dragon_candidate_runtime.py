"""D3-C Candidate, Grounding, idempotency, and atomic commit tests."""

from __future__ import annotations

import copy
import json
import unittest
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import StatementError

from core.free_action_resolution import load_world_skeleton
from database import create_database_engine, create_session_factory
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
from database.persistence import PostgresPersistenceAdapter
from dragon.candidate_runtime import (
    DragonCandidateError,
    PROMPT_PATH,
    commit_new_dragon_encounter,
    generate_dragon_candidate,
    ground_dragon_candidate,
    load_dragon_archetypes,
    stable_dragon_id_for_source,
    stable_first_encounter_event_id,
    validate_provisional_new_dragon_decision,
)


def decision(outcome: str = "sighting") -> dict[str, Any]:
    return {
        "outcome": outcome,
        "is_final": False,
        "requires_new_dragon": True,
        "dragon_id": None,
        "reason_code": f"new_dragon_required_for_{outcome}",
        "context_score": 9,
        "roll": 0.75,
    }


def candidate(
    *,
    name: str = "Mossveil",
    physical_tendency: str = "medium_balanced",
    behavioral_tendency: str = "cautious",
    ecological_flavor: str = "It moves quietly beneath old forest canopies.",
) -> dict[str, Any]:
    return {
        "name": name,
        "appearance": {
            "description": "A lean dragon with muted green scales and pale eyes.",
            "distinctive_features": [
                "fern-like ridges along its neck",
                "silver markings around its eyes",
            ],
        },
        "personality_traits": ["observant", "reserved"],
        "physical_tendency": physical_tendency,
        "behavioral_tendency": behavioral_tendency,
        "ecological_flavor": ecological_flavor,
    }


class FakeProvider:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.call_count = 0
        self.request: dict[str, Any] | None = None

    def create_structured_output(self, **request: Any) -> Any:
        self.call_count += 1
        self.request = request
        return self.output


class DragonCandidateOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skeleton = load_world_skeleton()
        cls.locations = cls.skeleton["locations"]

    def test_candidate_prompt_requires_simplified_chinese_narrative(self) -> None:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn("Simplified Chinese", prompt)
        for field_name in (
            "appearance.description",
            "appearance.distinctive_features",
            "personality_traits",
            "ecological_flavor",
        ):
            self.assertIn(field_name, prompt)

    def test_case_1_none_decision_is_rejected_before_candidate(self) -> None:
        invalid = {
            "outcome": "none",
            "is_final": True,
            "requires_new_dragon": False,
            "dragon_id": None,
            "reason_code": "context_no_encounter",
            "context_score": 2,
            "roll": 0.1,
        }
        with self.assertRaises(DragonCandidateError):
            validate_provisional_new_dragon_decision(invalid)

    def test_case_2_trace_decision_is_rejected(self) -> None:
        invalid = {
            "outcome": "trace",
            "is_final": True,
            "requires_new_dragon": False,
            "dragon_id": None,
            "reason_code": "dragon_trace",
            "context_score": 6,
            "roll": 0.2,
        }
        with self.assertRaises(DragonCandidateError):
            validate_provisional_new_dragon_decision(invalid)

    def test_case_3_already_final_existing_dragon_is_rejected(self) -> None:
        invalid = {
            "outcome": "sighting",
            "is_final": True,
            "requires_new_dragon": False,
            "dragon_id": "dragon_existing",
            "reason_code": "existing_dragon_sighting",
            "context_score": 10,
            "roll": 0.5,
        }
        with self.assertRaises(DragonCandidateError):
            validate_provisional_new_dragon_decision(invalid)

    def test_candidate_generator_uses_dedicated_strict_schema(self) -> None:
        expected = candidate()
        provider = FakeProvider(json.dumps(expected))
        result = generate_dragon_candidate(
            provisional_decision=decision(),
            encounter_location_id="whispering_woods",
            locations=self.locations,
            world_context={"weather": "cloudy"},
            provider_client=provider,  # type: ignore[arg-type]
        )
        self.assertEqual(result, expected)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.request["schema_name"], "dragon_candidate")
        self.assertNotIn("dragon_id", result)
        self.assertNotIn("archetype_id", result)
        self.assertNotIn("current_location", result)

    def test_case_6_owned_tamed_bonded_claim_fails_grounding(self) -> None:
        unsafe = candidate(
            ecological_flavor=(
                "Already tamed and owned by the player through an ancient bond."
            )
        )
        with self.assertRaises(DragonCandidateError):
            ground_dragon_candidate(
                candidate=unsafe,
                provisional_decision=decision(),
                encounter_location_id="whispering_woods",
                locations=self.locations,
            )

    def test_case_7_unregistered_encounter_location_fails_closed(self) -> None:
        with self.assertRaises(DragonCandidateError):
            ground_dragon_candidate(
                candidate=candidate(),
                provisional_decision=decision(),
                encounter_location_id="invented_dragon_vale",
                locations=self.locations,
            )

    def test_case_8_unresolvable_archetype_fails_closed(self) -> None:
        registry = copy.deepcopy(load_dragon_archetypes())
        for archetype in registry["archetypes"].values():
            archetype["physical_tendencies"] = ["unsupported_shape"]
        with self.assertRaises(DragonCandidateError):
            ground_dragon_candidate(
                candidate=candidate(),
                provisional_decision=decision(),
                encounter_location_id="whispering_woods",
                locations=self.locations,
                registry=registry,
            )

    def test_case_9_invalid_provider_output_fails_closed(self) -> None:
        provider = FakeProvider(json.dumps({"name": "Incomplete"}))
        with self.assertRaises(DragonCandidateError):
            generate_dragon_candidate(
                provisional_decision=decision(),
                encounter_location_id="whispering_woods",
                locations=self.locations,
                provider_client=provider,  # type: ignore[arg-type]
            )
        self.assertEqual(provider.call_count, 1)

    def test_registry_contains_only_three_broad_runtime_archetypes(self) -> None:
        registry = load_dragon_archetypes()
        self.assertEqual(
            set(registry["archetypes"]),
            {"agile_wild", "balanced_wild", "powerful_wild"},
        )

    def test_grounding_resolves_runtime_defaults_not_candidate_authority(self) -> None:
        grounded = ground_dragon_candidate(
            candidate=candidate(
                physical_tendency="large_powerful",
                behavioral_tendency="territorial",
            ),
            provisional_decision=decision("direct_encounter"),
            encounter_location_id="stormcliff",
            locations=self.locations,
        )
        self.assertEqual(grounded["archetype_id"], "powerful_wild")
        self.assertEqual(grounded["current_location"], "stormcliff")
        self.assertEqual(grounded["taming_state"], "wild")
        self.assertEqual(grounded["behavior_state"], "threatening")
        self.assertNotIn("owner", grounded)
        self.assertNotIn("riding_unlocked", grounded)


class DragonCandidateDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine()
        cls.session_factory = create_session_factory(cls.engine)
        cls.persistence = PostgresPersistenceAdapter(cls.session_factory)
        cls.skeleton = load_world_skeleton()
        cls.locations = cls.skeleton["locations"]
        cls.test_token = uuid.uuid4().hex
        cls.player_id = f"test_d3c_player_{cls.test_token}"
        cls.source_prefix = f"test_d3c_source_{cls.test_token}_"
        cls.persistence.ensure_player(
            player_id=cls.player_id,
            name="D3-C Test Player",
            species="human",
            occupation=None,
            background=None,
            traits=[],
        )
        cls.persistence.upsert_player_state(
            player_id=cls.player_id,
            current_location="whispering_woods",
            inventory=[],
            goals=[],
            identity_context={},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup_all()
        with cls.session_factory.begin() as session:
            session.execute(
                delete(PlayerState).where(PlayerState.player_id == cls.player_id)
            )
            session.execute(delete(Player).where(Player.player_id == cls.player_id))
        cls.engine.dispose()

    @classmethod
    def _cleanup_all(cls) -> None:
        with cls.session_factory.begin() as session:
            source_ids = session.scalars(
                select(InteractionEvent.event_id).where(
                    InteractionEvent.event_id.like(f"{cls.source_prefix}%")
                )
            ).all()
            dragon_ids = [stable_dragon_id_for_source(source_id) for source_id in source_ids]
            if dragon_ids:
                session.execute(
                    delete(PlayerDragonBond).where(
                        PlayerDragonBond.dragon_id.in_(dragon_ids)
                    )
                )
                session.execute(
                    delete(DragonEvent).where(DragonEvent.dragon_id.in_(dragon_ids))
                )
                session.execute(delete(Dragon).where(Dragon.dragon_id.in_(dragon_ids)))
            if source_ids:
                session.execute(
                    delete(InteractionEvent).where(
                        InteractionEvent.event_id.in_(source_ids)
                    )
                )

    def setUp(self) -> None:
        self._cleanup_all()
        self._source_counter = 0
        self.protected_counts = self._protected_counts()

    def tearDown(self) -> None:
        self._cleanup_all()
        self.assertEqual(self._protected_counts(), self.protected_counts)

    def _protected_counts(self) -> dict[str, int]:
        protected = (Npc, NpcMemory, NpcRelationship, PlayerDragonBond)
        with self.session_factory() as session:
            return {
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model)
                )
                for model in protected
            }

    def _source(self, suffix: str, *, location: str = "whispering_woods") -> str:
        self._source_counter += 1
        source_id = f"{self.source_prefix}{suffix}_{self._source_counter}"
        self.persistence.insert_interaction_event(
            {
                "event_id": source_id,
                "event_type": "free_world_action",
                "player_id": self.player_id,
                "world_context": {
                    "world_day": 1,
                    "world_hour": 8,
                    "location_id": location,
                },
                "player_utterance": "test Dragon encounter search",
                "player_claims": [],
                "event_payload": {
                    "structured_action": {},
                    "resolution": {},
                    "world_effect": {},
                },
            }
        )
        return source_id

    def _commit(
        self,
        source_id: str,
        *,
        outcome: str = "sighting",
        candidate_value: dict[str, Any] | None = None,
        location: str = "whispering_woods",
    ) -> dict[str, Any]:
        return commit_new_dragon_encounter(
            player_id=self.player_id,
            source_interaction_event_id=source_id,
            provisional_decision=decision(outcome),
            encounter_location_id=location,
            persistence=self.persistence,
            candidate=(candidate_value if candidate_value is not None else candidate()),
            locations=self.locations,
        )

    def _counts(self) -> tuple[int, int, int]:
        with self.session_factory() as session:
            return (
                session.scalar(select(func.count()).select_from(Dragon)),
                session.scalar(select(func.count()).select_from(DragonEvent)),
                session.scalar(select(func.count()).select_from(PlayerDragonBond)),
            )

    def test_case_4_valid_provisional_sighting_commits_and_finalizes(self) -> None:
        source_id = self._source("case_4")
        result = self._commit(source_id)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["encounter"]["outcome"], "sighting")
        self.assertTrue(result["encounter"]["is_final"])
        self.assertFalse(result["encounter"]["requires_new_dragon"])
        self.assertEqual(result["encounter"]["dragon_id"], result["dragon"]["dragon_id"])
        self.assertIsNotNone(self.persistence.get_dragon(result["dragon"]["dragon_id"]))

    def test_case_5_direct_encounter_commits_first_encounter_event(self) -> None:
        source_id = self._source("case_5", location="stormcliff")
        result = self._commit(
            source_id,
            outcome="direct_encounter",
            candidate_value=candidate(
                physical_tendency="large_powerful",
                behavioral_tendency="territorial",
            ),
            location="stormcliff",
        )
        self.assertEqual(result["encounter"]["outcome"], "direct_encounter")
        self.assertEqual(result["dragon_event"]["event_type"], "dragon_first_encounter")
        self.assertEqual(
            result["dragon_event"]["source_interaction_event_id"],
            source_id,
        )

    def test_case_10_retry_is_idempotent_and_returns_same_dragon(self) -> None:
        source_id = self._source("case_10")
        before = self._counts()
        first = self._commit(source_id)
        second = self._commit(
            source_id,
            candidate_value=candidate(name="A Different Retry Candidate"),
        )
        after = self._counts()
        self.assertEqual(first["status"], "committed")
        self.assertEqual(second["status"], "already_applied")
        self.assertEqual(first["dragon"]["dragon_id"], second["dragon"]["dragon_id"])
        self.assertEqual(after[0] - before[0], 1)
        self.assertEqual(after[1] - before[1], 1)

    def test_case_11_event_failure_rolls_back_dragon_insert(self) -> None:
        source_id = self._source("case_11")
        grounded = ground_dragon_candidate(
            candidate=candidate(),
            provisional_decision=decision(),
            encounter_location_id="whispering_woods",
            locations=self.locations,
        )
        grounded["dragon_id"] = stable_dragon_id_for_source(source_id)
        before = self._counts()
        with self.assertRaises((StatementError, TypeError)):
            self.persistence.commit_grounded_dragon_encounter(
                player_id=self.player_id,
                source_interaction_event_id=source_id,
                dragon=grounded,
                dragon_event_id=stable_first_encounter_event_id(source_id),
                encounter_outcome="sighting",
                event_payload={"not_json_serializable": object()},
            )
        self.assertEqual(self._counts(), before)
        self.assertIsNone(
            self.persistence.get_dragon(stable_dragon_id_for_source(source_id))
        )

    def test_case_12_success_adds_one_dragon_event_and_no_bond(self) -> None:
        source_id = self._source("case_12")
        before = self._counts()
        result = self._commit(source_id)
        after = self._counts()
        self.assertEqual(after[0] - before[0], 1)
        self.assertEqual(after[1] - before[1], 1)
        self.assertEqual(after[2], before[2])
        self.assertEqual(result["dragon"]["taming_state"], "wild")


if __name__ == "__main__":
    unittest.main()
