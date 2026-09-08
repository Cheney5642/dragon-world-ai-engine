"""D2-C deterministic resolution and PostgreSQL boundary tests."""

from __future__ import annotations

import copy
import unittest
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from core.free_action_resolution import (
    commit_action_resolution,
    load_world_skeleton,
    resolve_current_action,
)
from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    DragonEgg,
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
from database.persistence import PostgresPersistenceAdapter


PROTECTED_MODELS = (
    Npc,
    NpcMemory,
    NpcRelationship,
    Dragon,
    PlayerDragonBond,
    DragonEgg,
    DragonEvent,
    WorldStateEntry,
)


def action(
    family: str,
    text: str,
    *,
    target: str | None = None,
    destination: str | None = None,
    direction: str | None = None,
    intent: str | None = None,
    method: str | None = None,
    explicit_goal: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "action_family": family,
        "action": text,
        "target": target,
        "destination": destination,
        "direction": direction,
        "intent": intent,
        "method": method,
        "explicit_goal": explicit_goal,
        "needs_clarification": False,
    }


class FreeActionResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine()
        cls.session_factory = create_session_factory(cls.engine)
        cls.persistence = PostgresPersistenceAdapter(cls.session_factory)
        cls.player_id = f"test_d2c_{uuid.uuid4().hex}"
        cls.event_prefix = f"test_d2c_event_{uuid.uuid4().hex}_"
        cls.skeleton = load_world_skeleton()
        cls.persistence.ensure_player(
            player_id=cls.player_id,
            name="D2-C Test Player",
            species="human",
            occupation=None,
            background=None,
            traits=[],
        )
        cls.persistence.upsert_player_state(
            player_id=cls.player_id,
            current_location="skeld_village",
            inventory=[],
            goals=[],
            identity_context={},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        with cls.session_factory.begin() as session:
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.event_id.like(f"{cls.event_prefix}%")
                )
            )
            session.execute(delete(PlayerState).where(PlayerState.player_id == cls.player_id))
            session.execute(delete(Player).where(Player.player_id == cls.player_id))
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.session_factory.begin() as session:
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.event_id.like(f"{self.event_prefix}%")
                )
            )
        self.persistence.upsert_player_state(
            player_id=self.player_id,
            current_location="skeld_village",
            inventory=[],
            goals=[],
        )
        self.protected_counts = self._protected_counts()

    def tearDown(self) -> None:
        self.assertEqual(self._protected_counts(), self.protected_counts)

    def _protected_counts(self) -> dict[str, int]:
        with self.session_factory() as session:
            return {
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model)
                )
                for model in PROTECTED_MODELS
            }

    def _commit(self, player_input: str, structured_action: dict[str, Any], suffix: str):
        return commit_action_resolution(
            player_id=self.player_id,
            player_input=player_input,
            structured_action=structured_action,
            persistence=self.persistence,
            world_skeleton=self.skeleton,
            event_id=f"{self.event_prefix}{suffix}",
        )

    def _assert_event(self, result: dict[str, Any], event_id: str) -> None:
        self.assertEqual(result["interaction_event"]["event_id"], event_id)
        persisted = self.persistence.get_interaction_event(event_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["event_type"], "free_world_action")
        self.assertEqual(
            persisted["event_payload"]["resolution"], result["resolution"]
        )

    def test_case_1_known_travel_commits_location_and_event(self) -> None:
        result = self._commit(
            "我要去 Whispering Woods。",
            action("travel", "前往 Whispering Woods", destination="Whispering Woods"),
            "case_1",
        )
        self.assertEqual(result["resolution"]["status"], "success")
        self.assertEqual(result["resolution"]["effect_scope"], "player_state")
        self.assertEqual(result["player_state"]["current_location"], "whispering_woods")
        self.assertEqual(result["player_state"]["inventory"], [])
        self._assert_event(result, f"{self.event_prefix}case_1")

    def test_case_2_open_exploration_is_narrative_only(self) -> None:
        result = self._commit(
            "我往北一直走。",
            action("explore", "往北一直走", direction="北"),
            "case_2",
        )
        self.assertEqual(result["resolution"]["status"], "success")
        self.assertEqual(result["resolution"]["effect_scope"], "narrative_only")
        self.assertEqual(result["resolution"]["state_changes"], {})
        self.assertEqual(result["player_state"]["current_location"], "skeld_village")
        self.assertNotEqual(result["player_state"]["current_location"], "北")
        self._assert_event(result, f"{self.event_prefix}case_2")

    def test_case_3_drink_is_narrative_only(self) -> None:
        result = self._commit(
            "我在酒馆喝一杯。",
            action("rest_wait", "在酒馆喝一杯", target="一杯酒"),
            "case_3",
        )
        self.assertEqual(result["resolution"]["status"], "success")
        self.assertEqual(result["resolution"]["reason_code"], "narrative_only")
        self.assertEqual(result["player_state"]["current_location"], "skeld_village")
        self.assertEqual(result["player_state"]["goals"], [])
        self._assert_event(result, f"{self.event_prefix}case_3")

    def test_case_4_riding_without_grounded_dragon_is_blocked(self) -> None:
        self.assertFalse(self.persistence.has_rideable_dragon(self.player_id))
        result = self._commit(
            "我要骑我的龙去 Stormcliff。",
            action(
                "travel", "骑我的龙前往 Stormcliff", destination="Stormcliff",
                method="骑我的龙",
            ),
            "case_4",
        )
        self.assertEqual(result["resolution"]["status"], "blocked")
        self.assertEqual(result["resolution"]["domain_route"], "dragon")
        self.assertEqual(result["resolution"]["reason_code"], "dragon_riding_not_grounded")
        self.assertEqual(result["player_state"]["current_location"], "skeld_village")
        self._assert_event(result, f"{self.event_prefix}case_4")

    def test_case_5_unverified_mansion_does_not_become_location(self) -> None:
        result = self._commit(
            "我要回我在 Skeld 最大的豪宅。",
            action("travel", "返回豪宅", destination="我在 Skeld 最大的豪宅"),
            "case_5",
        )
        self.assertEqual(result["resolution"]["status"], "blocked")
        self.assertEqual(result["resolution"]["reason_code"], "destination_not_grounded")
        self.assertEqual(result["player_state"]["current_location"], "skeld_village")
        self._assert_event(result, f"{self.event_prefix}case_5")

    def test_case_6_goal_add_is_idempotent(self) -> None:
        structured = action(
            "other", "声明长期目标",
            explicit_goal={"operation": "add", "goal": "找到一枚龙蛋"},
        )
        first = self._commit("我的目标是找到一枚龙蛋。", structured, "case_6a")
        second = self._commit("我的目标是找到一枚龙蛋。", structured, "case_6b")
        self.assertEqual(first["resolution"]["reason_code"], "goal_added")
        self.assertEqual(second["resolution"]["reason_code"], "goal_already_present")
        self.assertEqual(second["player_state"]["goals"], ["找到一枚龙蛋"])
        self._assert_event(second, f"{self.event_prefix}case_6b")

    def test_case_7_goal_remove_and_retry_are_safe(self) -> None:
        self.persistence.upsert_player_state(
            player_id=self.player_id,
            current_location="skeld_village",
            inventory=[],
            goals=["找到一枚龙蛋", "探索北境"],
        )
        structured = action(
            "other", "取消寻找龙蛋",
            explicit_goal={"operation": "remove", "goal": "寻找龙蛋"},
        )
        first = self._commit("我不想再找龙蛋了。", structured, "case_7a")
        second = self._commit("我不想再找龙蛋了。", structured, "case_7b")
        self.assertEqual(first["resolution"]["reason_code"], "goal_removed")
        self.assertEqual(second["resolution"]["reason_code"], "goal_not_present")
        self.assertEqual(second["player_state"]["goals"], ["探索北境"])
        self._assert_event(second, f"{self.event_prefix}case_7b")

    def test_case_8_astrid_conflict_routes_without_npc_mutation(self) -> None:
        result = self._commit(
            "我要杀掉 Astrid。",
            action("conflict", "杀掉 Astrid", target="Astrid"),
            "case_8",
        )
        self.assertEqual(result["resolution"]["status"], "partial")
        self.assertEqual(result["resolution"]["effect_scope"], "domain_route")
        self.assertEqual(result["resolution"]["domain_route"], "npc")
        self.assertEqual(result["resolution"]["state_changes"], {})
        self._assert_event(result, f"{self.event_prefix}case_8")

    def test_atomic_failure_rolls_back_player_state(self) -> None:
        duplicate_id = f"{self.event_prefix}atomic"
        first = self._commit(
            "我在酒馆喝一杯。",
            action("rest_wait", "在酒馆喝一杯"),
            "atomic",
        )
        self.assertEqual(first["player_state"]["goals"], [])
        structured = action(
            "other", "声明长期目标",
            explicit_goal={"operation": "add", "goal": "探索 Old Ruins"},
        )
        with self.assertRaises(IntegrityError):
            commit_action_resolution(
                player_id=self.player_id,
                player_input="我的目标是探索 Old Ruins。",
                structured_action=structured,
                persistence=self.persistence,
                world_skeleton=self.skeleton,
                event_id=duplicate_id,
            )
        self.assertEqual(self.persistence.get_player_state(self.player_id)["goals"], [])

    def test_read_only_preview_changes_no_rows(self) -> None:
        before = copy.deepcopy(self.persistence.get_player_state(self.player_id))
        with self.session_factory() as session:
            event_count = session.scalar(select(func.count()).select_from(InteractionEvent))
        resolution = resolve_current_action(
            player_id=self.player_id,
            structured_action=action("explore", "往北一直走", direction="北"),
            persistence=self.persistence,
            world_skeleton=self.skeleton,
        )
        self.assertEqual(resolution["effect_scope"], "narrative_only")
        self.assertEqual(self.persistence.get_player_state(self.player_id), before)
        with self.session_factory() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(InteractionEvent)),
                event_count,
            )


if __name__ == "__main__":
    unittest.main()
