"""D4-C atomic Dragon bond/taming persistence tests."""

from __future__ import annotations

import copy
import unittest
import uuid
from typing import Any

from sqlalchemy import delete, func, select

from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    DragonEvent,
    InteractionEvent,
    Player,
    PlayerDragonBond,
    PlayerState,
)
from database.persistence import (
    PersistenceMappingError,
    PostgresPersistenceAdapter,
    _stable_dragon_interaction_event_id,
)


def action(
    family: str,
    text: str,
    *,
    target: str = "D4C Dragon",
    intent: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    return {
        "action_family": family,
        "action": text,
        "target": target,
        "destination": None,
        "direction": None,
        "intent": intent,
        "method": method,
        "explicit_goal": None,
        "needs_clarification": False,
    }


class DragonBondPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine()
        cls.session_factory = create_session_factory(cls.engine)
        cls.persistence = PostgresPersistenceAdapter(cls.session_factory)
        cls.token = uuid.uuid4().hex
        cls.player_id = f"test_d4c_player_{cls.token}"
        cls.other_player_id = f"test_d4c_player_other_{cls.token}"
        cls.dragon_id = f"test_d4c_dragon_{cls.token}"
        cls.other_dragon_id = f"test_d4c_dragon_other_{cls.token}"
        cls.source_prefix = f"test_d4c_source_{cls.token}_"
        cls.formal_before = cls._formal_snapshot()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup_all()
        assert cls._formal_snapshot() == cls.formal_before
        with cls.session_factory() as session:
            assert session.scalar(
                select(func.count()).select_from(Player).where(
                    Player.player_id.like("test_d4c_%")
                )
            ) == 0
            assert session.scalar(
                select(func.count()).select_from(Dragon).where(
                    Dragon.dragon_id.like("test_d4c_%")
                )
            ) == 0
            assert session.scalar(
                select(func.count()).select_from(InteractionEvent).where(
                    InteractionEvent.event_id.like("test_d4c_%")
                )
            ) == 0
        cls.engine.dispose()

    @classmethod
    def _formal_snapshot(cls) -> dict[str, Any]:
        with cls.session_factory() as session:
            player = session.get(Player, "player_001")
            player_state = session.get(PlayerState, "player_001")
            kael = session.scalar(select(Dragon).where(Dragon.name == "Kael"))
            return {
                "player": None if player is None else {
                    "name": player.name,
                    "species": player.species,
                    "occupation": player.occupation,
                    "traits": copy.deepcopy(player.traits),
                },
                "player_state": None if player_state is None else {
                    "location": player_state.current_location,
                    "inventory": copy.deepcopy(player_state.inventory),
                    "goals": copy.deepcopy(player_state.goals),
                    "identity_context": copy.deepcopy(player_state.identity_context),
                },
                "kael": None if kael is None else {
                    "dragon_id": kael.dragon_id,
                    "location": kael.current_location,
                    "taming_state": kael.taming_state,
                    "behavior_state": kael.behavior_state,
                },
                "dragon_count": session.scalar(
                    select(func.count()).select_from(Dragon)
                ),
                "dragon_event_count": session.scalar(
                    select(func.count()).select_from(DragonEvent)
                ),
                "bond_count": session.scalar(
                    select(func.count()).select_from(PlayerDragonBond)
                ),
            }

    @classmethod
    def _cleanup_all(cls) -> None:
        player_ids = [cls.player_id, cls.other_player_id]
        dragon_ids = [cls.dragon_id, cls.other_dragon_id]
        with cls.session_factory.begin() as session:
            session.execute(
                delete(PlayerDragonBond).where(
                    (PlayerDragonBond.player_id.in_(player_ids))
                    | (PlayerDragonBond.dragon_id.in_(dragon_ids))
                )
            )
            session.execute(
                delete(DragonEvent).where(
                    (DragonEvent.dragon_id.in_(dragon_ids))
                    | (DragonEvent.source_interaction_event_id.like(
                        f"{cls.source_prefix}%"
                    ))
                )
            )
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.event_id.like(f"{cls.source_prefix}%")
                )
            )
            session.execute(delete(PlayerState).where(PlayerState.player_id.in_(player_ids)))
            session.execute(delete(Dragon).where(Dragon.dragon_id.in_(dragon_ids)))
            session.execute(delete(Player).where(Player.player_id.in_(player_ids)))

    def setUp(self) -> None:
        self._cleanup_all()
        self.source_counter = 0
        self._ensure_player(self.player_id)
        self._ensure_dragon(self.dragon_id)

    def tearDown(self) -> None:
        self._cleanup_all()

    def _ensure_player(
        self,
        player_id: str,
        *,
        location: str = "stormcliff",
        inventory: list[Any] | None = None,
    ) -> None:
        self.persistence.ensure_player(
            player_id=player_id,
            name="D4C Test Player",
            species="human",
            occupation=None,
            background=None,
            traits=[],
        )
        self.persistence.upsert_player_state(
            player_id=player_id,
            current_location=location,
            inventory=inventory or [],
            goals=[],
            identity_context={},
        )

    def _ensure_dragon(
        self,
        dragon_id: str,
        *,
        location: str = "stormcliff",
        taming_state: str = "wild",
        behavior_state: str = "watching",
    ) -> None:
        with self.session_factory.begin() as session:
            session.add(
                Dragon(
                    dragon_id=dragon_id,
                    archetype_id="balanced_wild",
                    name="D4C Dragon" if dragon_id == self.dragon_id else "Other D4C Dragon",
                    sex=None,
                    age_stage="adult",
                    appearance={"description": "测试龙", "distinctive_features": []},
                    temperament_traits=["谨慎"],
                    current_location=location,
                    health_state="healthy",
                    energy=80,
                    hunger=20,
                    alertness=60,
                    behavior_state=behavior_state,
                    taming_state=taming_state,
                )
            )

    def _set_dragon_state(self, taming_state: str) -> None:
        with self.session_factory.begin() as session:
            dragon = session.get(Dragon, self.dragon_id)
            assert dragon is not None
            dragon.taming_state = taming_state

    def _seed_bond(
        self,
        familiarity: int,
        trust: int,
        fear: int,
        bond_value: int,
        *,
        player_id: str | None = None,
        dragon_id: str | None = None,
        riding_unlocked: bool = False,
    ) -> None:
        with self.session_factory.begin() as session:
            session.add(
                PlayerDragonBond(
                    player_id=player_id or self.player_id,
                    dragon_id=dragon_id or self.dragon_id,
                    familiarity=familiarity,
                    trust=trust,
                    fear=fear,
                    bond=bond_value,
                    riding_unlocked=riding_unlocked,
                    last_significant_event_id=None,
                )
            )

    def _source(
        self,
        structured_action: dict[str, Any],
        *,
        player_id: str | None = None,
        suffix: str = "action",
        d2_status: str = "success",
        domain_route: str | None = None,
    ) -> str:
        self.source_counter += 1
        source_id = f"{self.source_prefix}{suffix}_{self.source_counter:03d}"
        route = domain_route
        self.persistence.insert_interaction_event(
            {
                "event_id": source_id,
                "event_type": "free_world_action",
                "player_id": player_id or self.player_id,
                "world_context": {
                    "world_day": 1,
                    "world_hour": 8,
                    "location_id": "stormcliff",
                },
                "player_utterance": structured_action["action"],
                "player_claims": [],
                "event_payload": {
                    "structured_action": structured_action,
                    "resolution": {
                        "status": d2_status,
                        "effect_scope": (
                            "domain_route" if route is not None else "narrative_only"
                        ),
                        "reason_code": "dragon_runtime_required",
                        "state_changes": {},
                        "domain_route": route,
                    },
                    "world_effect": {},
                },
            }
        )
        return source_id

    def _commit(
        self,
        structured_action: dict[str, Any],
        *,
        player_id: str | None = None,
        dragon_id: str | None = None,
        suffix: str = "action",
        d2_status: str = "success",
        domain_route: str | None = None,
    ) -> dict[str, Any]:
        source_id = self._source(
            structured_action,
            player_id=player_id,
            suffix=suffix,
            d2_status=d2_status,
            domain_route=domain_route,
        )
        return self.persistence.commit_dragon_interaction(
            player_id=player_id or self.player_id,
            dragon_id=dragon_id or self.dragon_id,
            source_interaction_event_id=source_id,
        )

    def _seed_history(
        self,
        *,
        interaction_type: str,
        category: str | None,
        player_id: str | None = None,
        dragon_id: str | None = None,
        anti_farming: str = "full",
    ) -> str:
        source_id = self._source(
            action("interact", f"seed {interaction_type}"),
            player_id=player_id,
            suffix=f"history_{interaction_type}",
        )
        event = self.persistence.get_interaction_event(source_id)
        assert event is not None
        payload = dict(event["event_payload"])
        payload["dragon_interaction"] = {
            "dragon_id": dragon_id or self.dragon_id,
            "player_id": player_id or self.player_id,
            "source_interaction_event_id": source_id,
            "status": "success",
            "interaction_type": interaction_type,
            "dragon_reaction": "calm",
            "relationship_effect": "positive",
            "reason_code": "seeded_test_history",
            "positive_category": category,
            "anti_farming": anti_farming,
            "applied_deltas": {"familiarity": 1, "trust": 0, "fear": 0, "bond": 0},
            "before": {"familiarity": 0, "trust": 0, "fear": 0, "bond": 0, "taming_state": "wild"},
            "after": {"familiarity": 1, "trust": 0, "fear": 0, "bond": 0, "taming_state": "wild"},
            "taming_transition": None,
            "significant_event_id": None,
            "positive_categories": [category] if category is not None else [],
            "riding_unlocked": False,
            "is_final": True,
        }
        with self.session_factory.begin() as session:
            record = session.get(InteractionEvent, source_id)
            assert record is not None
            record.event_payload = payload
        return source_id

    def _bond(self, *, player_id: str | None = None, dragon_id: str | None = None) -> PlayerDragonBond | None:
        with self.session_factory() as session:
            record = session.get(
                PlayerDragonBond,
                (player_id or self.player_id, dragon_id or self.dragon_id),
            )
            if record is None:
                return None
            session.expunge(record)
            return record

    def _dragon(self) -> Dragon:
        with self.session_factory() as session:
            record = session.get(Dragon, self.dragon_id)
            assert record is not None
            session.expunge(record)
            return record

    def _event_count(self) -> int:
        with self.session_factory() as session:
            return session.scalar(
                select(func.count()).select_from(DragonEvent).where(
                    DragonEvent.dragon_id == self.dragon_id
                )
            )

    def test_case_01_observe_does_not_create_bond_or_mutate_dragon(self) -> None:
        before = self._dragon().taming_state
        result = self._commit(action("observe_search", "远远观察 D4C Dragon"), suffix="observe")
        self.assertEqual(result["status"], "applied")
        self.assertIsNone(self._bond())
        self.assertEqual(self._dragon().taming_state, before)

    def test_case_02_first_cautious_approach_creates_exact_bond(self) -> None:
        result = self._commit(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"),
            suffix="approach",
        )
        self.assertEqual(result["bond_state"], {
            "familiarity": 1, "trust": 0, "fear": 0, "bond": 0,
            "riding_unlocked": False,
        })

    def test_case_03_calm_communication_persists_category(self) -> None:
        result = self._commit(
            action("interact", "平静地和 D4C Dragon 说话", method="轻声说话"),
            suffix="communicate",
        )
        self.assertEqual(result["positive_categories"], ["communication"])
        history = self.persistence.list_committed_dragon_interactions(
            player_id=self.player_id, dragon_id=self.dragon_id
        )
        self.assertEqual(history[0]["positive_category"], "communication")

    def test_case_04_first_consecutive_positive_is_full(self) -> None:
        result = self._commit(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"),
            suffix="repeat1",
        )
        event = self.persistence.get_interaction_event(result["source_interaction_event_id"])
        self.assertEqual(event["event_payload"]["dragon_interaction"]["anti_farming"], "full")

    def test_case_05_second_consecutive_positive_is_familiarity_only(self) -> None:
        careful = action("interact", "慢慢靠近 D4C Dragon", method="小心靠近")
        self._commit(careful, suffix="repeat1")
        result = self._commit(careful, suffix="repeat2")
        event = self.persistence.get_interaction_event(result["source_interaction_event_id"])
        interaction = event["event_payload"]["dragon_interaction"]
        self.assertEqual(interaction["anti_farming"], "familiarity_only")
        self.assertEqual(interaction["applied_deltas"]["trust"], 0)

    def test_case_06_third_consecutive_positive_has_zero_gain(self) -> None:
        careful = action("interact", "慢慢靠近 D4C Dragon", method="小心靠近")
        self._commit(careful, suffix="repeat1")
        self._commit(careful, suffix="repeat2")
        result = self._commit(careful, suffix="repeat3")
        self.assertEqual(set(result["applied_deltas"].values()), {0})

    def test_case_07_different_type_resets_chain_and_food_is_atomic(self) -> None:
        with self.session_factory.begin() as session:
            state = session.get(PlayerState, self.player_id)
            assert state is not None
            state.inventory = [{"item_id": "fish_001", "category": "food", "quantity": 1}]
        careful = action("interact", "慢慢靠近 D4C Dragon", method="小心靠近")
        self._commit(careful, suffix="repeat1")
        self._commit(careful, suffix="repeat2")
        food = self._commit(
            action("interact", "把食物放下给 D4C Dragon", method="放下食物"),
            suffix="food",
        )
        event = self.persistence.get_interaction_event(food["source_interaction_event_id"])
        self.assertEqual(event["event_payload"]["dragon_interaction"]["anti_farming"], "full")
        self.assertEqual(self.persistence.get_player_state(self.player_id)["inventory"], [])

    def test_case_08_threat_creates_negative_bond_and_clamps(self) -> None:
        result = self._commit(action("conflict", "挥剑威胁 D4C Dragon"), suffix="threat")
        self.assertEqual(result["bond_state"]["trust"], -1)
        self.assertEqual(result["bond_state"]["fear"], 1)
        self.assertEqual(result["bond_state"]["bond"], 0)

    def test_case_09_other_player_history_is_isolated(self) -> None:
        self._ensure_player(self.other_player_id)
        careful = action("interact", "慢慢靠近 D4C Dragon", method="小心靠近")
        self._commit(careful, suffix="p1a")
        self._commit(careful, suffix="p1b")
        result = self._commit(careful, player_id=self.other_player_id, suffix="p2")
        event = self.persistence.get_interaction_event(result["source_interaction_event_id"])
        self.assertEqual(event["event_payload"]["dragon_interaction"]["anti_farming"], "full")

    def test_case_10_other_dragon_history_is_isolated(self) -> None:
        self._ensure_dragon(self.other_dragon_id)
        careful = action("interact", "慢慢靠近 D4C Dragon", method="小心靠近")
        self._commit(careful, suffix="d1a")
        self._commit(careful, suffix="d1b")
        other_action = action(
            "interact", "慢慢靠近 Other D4C Dragon", target="Other D4C Dragon", method="小心靠近"
        )
        result = self._commit(other_action, dragon_id=self.other_dragon_id, suffix="d2")
        event = self.persistence.get_interaction_event(result["source_interaction_event_id"])
        self.assertEqual(event["event_payload"]["dragon_interaction"]["anti_farming"], "full")

    def test_case_11_reaching_tolerant_commits_one_step(self) -> None:
        self._seed_bond(1, 0, 0, 0)
        result = self._commit(
            action("interact", "平静地和 D4C Dragon 说话", method="轻声说话"),
            suffix="tolerant",
        )
        self.assertEqual(result["taming_transition"], {"from": "wild", "to": "tolerant"})
        self.assertEqual(self._dragon().taming_state, "tolerant")

    def test_case_12_reaching_bonding_commits_one_step(self) -> None:
        self._set_dragon_state("tolerant")
        self._seed_bond(2, 2, 0, 0)
        self._seed_history(interaction_type="approach", category="close_presence")
        result = self._commit(
            action("interact", "轻轻触碰 D4C Dragon", method="小心触碰"),
            suffix="bonding",
        )
        self.assertEqual(result["taming_transition"], {"from": "tolerant", "to": "bonding"})

    def test_case_13_reaching_tamed_writes_event_atomically(self) -> None:
        self._set_dragon_state("bonding")
        self._seed_bond(3, 2, 0, 1)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="communicate", category="communication")
        before = self._event_count()
        result = self._commit(
            action("interact", "轻轻触碰 D4C Dragon", method="小心触碰"),
            suffix="tamed",
        )
        self.assertEqual(result["taming_transition"], {"from": "bonding", "to": "tamed"})
        self.assertEqual(self._dragon().taming_state, "tamed")
        self.assertEqual(self._event_count(), before + 1)

    def test_case_14_tamed_retry_is_idempotent(self) -> None:
        self._set_dragon_state("bonding")
        self._seed_bond(3, 2, 0, 1)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="communicate", category="communication")
        source = self._source(
            action("interact", "轻轻触碰 D4C Dragon", method="小心触碰"), suffix="tamed_retry"
        )
        first = self.persistence.commit_dragon_interaction(
            player_id=self.player_id, dragon_id=self.dragon_id, source_interaction_event_id=source
        )
        before_bond = first["bond_state"]
        before_events = self._event_count()
        second = self.persistence.commit_dragon_interaction(
            player_id=self.player_id, dragon_id=self.dragon_id, source_interaction_event_id=source
        )
        self.assertEqual(second["status"], "already_applied")
        self.assertEqual(second["bond_state"], before_bond)
        self.assertEqual(self._event_count(), before_events)

    def test_case_15_tamed_event_failure_rolls_back_everything(self) -> None:
        self._set_dragon_state("bonding")
        self._seed_bond(3, 2, 0, 1)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="communicate", category="communication")
        source = self._source(
            action("interact", "轻轻触碰 D4C Dragon", method="小心触碰"), suffix="rollback"
        )
        conflicting_source = self._source(action("other", "conflict seed"), suffix="conflict")
        event_id = _stable_dragon_interaction_event_id(source, "dragon_tamed")
        with self.session_factory.begin() as session:
            session.add(DragonEvent(
                event_id=event_id,
                event_type="dragon_tamed",
                dragon_id=self.dragon_id,
                player_id=self.player_id,
                source_interaction_event_id=conflicting_source,
                world_day=1,
                world_hour=8,
                location_id="stormcliff",
                milestone_key="test_conflict",
                event_payload={},
            ))
        before_bond = self._bond()
        with self.assertRaises(PersistenceMappingError):
            self.persistence.commit_dragon_interaction(
                player_id=self.player_id, dragon_id=self.dragon_id, source_interaction_event_id=source
            )
        after_bond = self._bond()
        self.assertEqual((after_bond.familiarity, after_bond.trust, after_bond.bond),
                         (before_bond.familiarity, before_bond.trust, before_bond.bond))
        self.assertEqual(self._dragon().taming_state, "bonding")
        self.assertNotIn("dragon_interaction", self.persistence.get_interaction_event(source)["event_payload"])

    def test_case_16_cross_location_is_blocked_without_bond(self) -> None:
        with self.session_factory.begin() as session:
            state = session.get(PlayerState, self.player_id)
            assert state is not None
            state.current_location = "skeld"
        result = self._commit(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"), suffix="range"
        )
        self.assertEqual(set(result["applied_deltas"].values()), {0})
        self.assertIsNone(self._bond())

    def test_case_17_player_taming_claim_cannot_transition(self) -> None:
        result = self._commit(action("other", "D4C Dragon 已被我驯服"), suffix="claim")
        self.assertEqual(result["taming_state"], "wild")
        self.assertIsNone(result["taming_transition"])

    def test_case_18_ride_attempt_never_unlocks_riding(self) -> None:
        result = self._commit(
            action("travel", "骑 D4C Dragon 去 Skeld", intent="骑乘"),
            suffix="ride",
            d2_status="blocked",
            domain_route="dragon",
        )
        self.assertFalse(result["bond_state"]["riding_unlocked"])
        self.assertIsNone(self._bond())

    def test_case_19_blocked_touch_does_not_apply_negative_preview(self) -> None:
        result = self._commit(action("interact", "突然抱住 D4C Dragon"), suffix="blocked")
        event = self.persistence.get_interaction_event(result["source_interaction_event_id"])
        self.assertEqual(event["event_payload"]["dragon_interaction"]["status"], "blocked")
        self.assertEqual(set(result["applied_deltas"].values()), {0})
        self.assertIsNone(self._bond())

    def test_case_20_source_retry_is_idempotent(self) -> None:
        source = self._source(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"), suffix="retry"
        )
        first = self.persistence.commit_dragon_interaction(
            player_id=self.player_id, dragon_id=self.dragon_id, source_interaction_event_id=source
        )
        second = self.persistence.commit_dragon_interaction(
            player_id=self.player_id, dragon_id=self.dragon_id, source_interaction_event_id=source
        )
        self.assertEqual(first["bond_state"], second["bond_state"])
        self.assertEqual(second["status"], "already_applied")

    def test_case_21_ordinary_interaction_updates_source_only(self) -> None:
        before = self._event_count()
        result = self._commit(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"), suffix="audit"
        )
        event = self.persistence.get_interaction_event(result["source_interaction_event_id"])
        interaction = event["event_payload"]["dragon_interaction"]
        self.assertTrue(interaction["is_final"])
        self.assertEqual(interaction["dragon_id"], self.dragon_id)
        self.assertEqual(self._event_count(), before)

    def test_case_22_three_positive_categories_read_back(self) -> None:
        self._commit(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"), suffix="cat_close"
        )
        self._commit(
            action("interact", "平静地和 D4C Dragon 说话", method="轻声说话"), suffix="cat_talk"
        )
        self._seed_bond_after_existing(3, 2, 0, 0)
        self._set_dragon_state("tolerant")
        result = self._commit(
            action("interact", "轻轻触碰 D4C Dragon", method="小心触碰"), suffix="cat_touch"
        )
        self.assertEqual(
            set(result["positive_categories"]),
            {"close_presence", "communication", "touch"},
        )

    def _seed_bond_after_existing(self, familiarity: int, trust: int, fear: int, bond_value: int) -> None:
        with self.session_factory.begin() as session:
            record = session.get(PlayerDragonBond, (self.player_id, self.dragon_id))
            assert record is not None
            record.familiarity = familiarity
            record.trust = trust
            record.fear = fear
            record.bond = bond_value

    def test_case_23_single_effect_transitions_only_one_adjacent_state(self) -> None:
        self._seed_bond(4, 3, 0, 2)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="offer_food", category="food")
        self._seed_history(interaction_type="touch", category="touch")
        result = self._commit(
            action("interact", "平静地和 D4C Dragon 说话", method="轻声说话"), suffix="one_step"
        )
        self.assertEqual(result["taming_transition"], {"from": "wild", "to": "tolerant"})
        self.assertEqual(self._dragon().taming_state, "tolerant")

    def test_case_24_all_relationship_values_are_clamped(self) -> None:
        self._seed_bond(5, 5, 5, 5)
        result = self._commit(action("conflict", "挥剑威胁 D4C Dragon"), suffix="clamp")
        state = result["bond_state"]
        self.assertTrue(0 <= state["familiarity"] <= 5)
        self.assertTrue(-3 <= state["trust"] <= 5)
        self.assertTrue(0 <= state["fear"] <= 5)
        self.assertTrue(0 <= state["bond"] <= 5)

    def test_case_25_observe_cannot_trigger_tolerant_from_ready_snapshot(self) -> None:
        self._seed_bond(2, 1, 0, 0)
        self._seed_history(interaction_type="approach", category="close_presence")
        result = self._commit(
            action("observe_search", "远远观察 D4C Dragon"),
            suffix="observe_ready",
        )
        self.assertIsNone(result["taming_transition"])
        self.assertEqual(self._dragon().taming_state, "wild")

    def test_case_26_threat_cannot_trigger_bonding_from_ready_snapshot(self) -> None:
        self._set_dragon_state("tolerant")
        self._seed_bond(4, 3, 0, 2)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="communicate", category="communication")
        result = self._commit(
            action("conflict", "挥剑威胁 D4C Dragon"),
            suffix="threat_ready",
        )
        self.assertIsNone(result["taming_transition"])
        self.assertEqual(self._dragon().taming_state, "tolerant")

    def test_case_27_positive_communication_triggers_bonding(self) -> None:
        self._set_dragon_state("tolerant")
        self._seed_bond(3, 2, 0, 1)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="touch", category="touch")
        result = self._commit(
            action(
                "interact",
                "平静地和 D4C Dragon 说话",
                method="轻声说话",
            ),
            suffix="positive_bonding",
        )
        self.assertEqual(
            result["taming_transition"],
            {"from": "tolerant", "to": "bonding"},
        )
        self.assertEqual(self._dragon().taming_state, "bonding")

    def test_case_28_blocked_interaction_cannot_trigger_tamed(self) -> None:
        self._set_dragon_state("bonding")
        self._seed_bond(5, 5, 0, 5)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="communicate", category="communication")
        self._seed_history(interaction_type="offer_food", category="food")
        before_events = self._event_count()
        result = self._commit(
            action("travel", "骑 D4C Dragon 去 Skeld", intent="骑乘"),
            suffix="blocked_tamed",
            d2_status="blocked",
            domain_route="dragon",
        )
        self.assertIsNone(result["taming_transition"])
        self.assertEqual(self._dragon().taming_state, "bonding")
        self.assertEqual(self._event_count(), before_events)

    def test_case_29_next_positive_touch_triggers_one_tamed_event(self) -> None:
        self._set_dragon_state("bonding")
        self._seed_bond(5, 5, 0, 4)
        self._seed_history(interaction_type="approach", category="close_presence")
        self._seed_history(interaction_type="communicate", category="communication")
        self._seed_history(interaction_type="offer_food", category="food")
        blocked = self._commit(
            action("travel", "骑 D4C Dragon 去 Skeld", intent="骑乘"),
            suffix="blocked_before_touch",
            d2_status="blocked",
            domain_route="dragon",
        )
        self.assertIsNone(blocked["taming_transition"])
        before_events = self._event_count()
        result = self._commit(
            action("interact", "轻轻触碰 D4C Dragon", method="小心触碰"),
            suffix="positive_touch_tamed",
        )
        self.assertEqual(
            result["taming_transition"],
            {"from": "bonding", "to": "tamed"},
        )
        self.assertEqual(self._event_count(), before_events + 1)
        with self.session_factory() as session:
            count = session.scalar(
                select(func.count()).select_from(DragonEvent).where(
                    DragonEvent.dragon_id == self.dragon_id,
                    DragonEvent.event_type == "dragon_tamed",
                )
            )
        self.assertEqual(count, 1)

    def test_case_30_source_payload_merges_without_losing_d2_or_d3(self) -> None:
        source = self._source(
            action("interact", "慢慢靠近 D4C Dragon", method="小心靠近"),
            suffix="payload_merge",
        )
        decision = {
            "outcome": "sighting",
            "is_final": True,
            "requires_new_dragon": False,
            "dragon_id": self.dragon_id,
            "reason_code": "existing_dragon_sighting",
            "context_score": 10,
            "roll": 0.75,
        }
        self.persistence.record_dragon_encounter_decision(
            player_id=self.player_id,
            source_interaction_event_id=source,
            encounter_location_id="stormcliff",
            decision=decision,
        )
        before = copy.deepcopy(
            self.persistence.get_interaction_event(source)["event_payload"]
        )
        self.persistence.commit_dragon_interaction(
            player_id=self.player_id,
            dragon_id=self.dragon_id,
            source_interaction_event_id=source,
        )
        after = self.persistence.get_interaction_event(source)["event_payload"]
        for key in (
            "structured_action",
            "resolution",
            "world_effect",
            "dragon_encounter_decision",
            "dragon_encounter_location_id",
        ):
            self.assertEqual(after[key], before[key])
        self.assertNotIn("dragon_interaction", before)
        self.assertTrue(after["dragon_interaction"]["is_final"])


if __name__ == "__main__":
    unittest.main()
