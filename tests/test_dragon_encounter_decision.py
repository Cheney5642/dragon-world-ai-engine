"""D3-B deterministic encounter decision and read-only boundary tests."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from core.dragon_encounter_decision import (
    _recent_history_penalty,
    decide_current_dragon_encounter,
    decide_dragon_encounter,
)
from core.free_action_resolution import load_world_skeleton


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


def resolution(
    status: str = "success",
    *,
    effect_scope: str = "narrative_only",
    reason_code: str = "test_resolution",
    domain_route: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "effect_scope": effect_scope,
        "reason_code": reason_code,
        "domain_route": domain_route,
        "state_changes": {},
    }


def dragon(
    dragon_id: str,
    *,
    name: str | None = None,
    behavior_state: str = "watching",
) -> dict[str, Any]:
    return {
        "dragon_id": dragon_id,
        "name": name,
        "behavior_state": behavior_state,
    }


def history(
    outcome: str,
    *,
    dragon_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_payload": {
            "encounter_decision": {
                "outcome": outcome,
                "dragon_id": dragon_id,
            }
        }
    }


class ReadOnlyPersistence:
    def __init__(
        self,
        *,
        current_location: str,
        dragons: list[dict[str, Any]] | None = None,
        recent_history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.player_state = {
            "player_id": "player_test",
            "current_location": current_location,
            "inventory": [],
            "goals": [],
            "identity_context": None,
        }
        self.dragons = list(dragons or [])
        self.recent_history = list(recent_history or [])
        self.calls: list[tuple[Any, ...]] = []

    def get_player_state(self, player_id: str) -> dict[str, Any]:
        self.calls.append(("get_player_state", player_id))
        return copy.deepcopy(self.player_state)

    def list_dragons_at_location(self, location_id: str) -> list[dict[str, Any]]:
        self.calls.append(("list_dragons_at_location", location_id))
        return copy.deepcopy(self.dragons)

    def list_recent_dragon_encounter_decisions(
        self,
        player_id: str,
        *,
        location_id: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            (
                "list_recent_dragon_encounter_decisions",
                player_id,
                location_id,
                limit,
            )
        )
        return copy.deepcopy(self.recent_history[:limit])


class DragonEncounterDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skeleton = load_world_skeleton()
        cls.locations = cls.skeleton["locations"]

    def decide(
        self,
        structured_action: dict[str, Any],
        *,
        current_location: str,
        d2_resolution: dict[str, Any] | None = None,
        existing_dragons: list[dict[str, Any]] | None = None,
        recent_history: list[dict[str, Any]] | None = None,
        roll: float = 0.0,
    ) -> dict[str, Any]:
        return decide_dragon_encounter(
            structured_action,
            d2_resolution or resolution(),
            current_location=current_location,
            locations=self.locations,
            existing_dragons=existing_dragons or [],
            recent_history=recent_history or [],
            roll=roll,
        )

    def test_case_1_skeld_tavern_drink_is_none_without_roll(self) -> None:
        called = False

        def forbidden_random() -> float:
            nonlocal called
            called = True
            raise AssertionError("Ineligible action must not consume random roll.")

        result = decide_dragon_encounter(
            action("rest_wait", "在酒馆喝酒"),
            resolution(),
            current_location="skeld_village",
            locations=self.locations,
            random_source=forbidden_random,
        )
        self.assertEqual(result["outcome"], "none")
        self.assertTrue(result["is_final"])
        self.assertFalse(called)

    def test_case_2_giant_footprints_can_deterministically_trace(self) -> None:
        result = self.decide(
            action("observe_search", "寻找巨大的脚印", target="巨大的脚印"),
            current_location="whispering_woods",
            roll=0.2,
        )
        self.assertEqual(result["outcome"], "trace")
        self.assertIsNone(result["dragon_id"])
        self.assertFalse(result["requires_new_dragon"])

    def test_case_3_deep_forest_search_is_contextual_not_guaranteed_direct(self) -> None:
        structured = action(
            "observe_search",
            "深入森林寻找龙",
            target="龙",
            intent="寻找龙",
        )
        low = self.decide(
            structured,
            current_location="whispering_woods",
            roll=0.0,
        )
        higher = self.decide(
            structured,
            current_location="whispering_woods",
            roll=0.5,
        )
        self.assertEqual(low["outcome"], "trace")
        self.assertEqual(higher["outcome"], "sighting")
        self.assertNotEqual(low["outcome"], "direct_encounter")

    def test_case_4_stormcliff_dragon_nest_scores_above_plain_travel(self) -> None:
        nest = self.decide(
            action(
                "observe_search",
                "寻找龙巢",
                target="龙巢",
                intent="寻找龙巢",
            ),
            current_location="stormcliff",
            roll=0.0,
        )
        nest_high_roll = self.decide(
            action(
                "observe_search",
                "寻找龙巢",
                target="龙巢",
                intent="寻找龙巢",
            ),
            current_location="stormcliff",
            roll=1.0,
        )
        travel = self.decide(
            action(
                "travel",
                "前往 Stormcliff 找龙",
                destination="Stormcliff",
                intent="找龙",
            ),
            current_location="stormcliff",
            roll=0.0,
        )
        self.assertGreater(nest["context_score"], travel["context_score"])
        self.assertEqual(nest["outcome"], "trace")
        self.assertEqual(nest_high_roll["outcome"], "direct_encounter")

    def test_case_5_existing_dragon_reuse_prefers_explicit_target(self) -> None:
        result = self.decide(
            action(
                "observe_search",
                "寻找 Ember",
                target="Ember",
                intent="寻找那条龙",
            ),
            current_location="whispering_woods",
            existing_dragons=[
                dragon("dragon_a", name="Ash"),
                dragon("dragon_b", name="Ember"),
            ],
            roll=0.75,
        )
        self.assertEqual(result["outcome"], "direct_encounter")
        self.assertTrue(result["is_final"])
        self.assertEqual(result["dragon_id"], "dragon_b")
        self.assertFalse(result["requires_new_dragon"])

    def test_case_6_direct_without_eligible_dragon_is_provisional(self) -> None:
        result = self.decide(
            action(
                "observe_search",
                "在风暴崖寻找龙巢",
                target="龙巢",
                intent="寻找龙",
            ),
            current_location="stormcliff",
            roll=0.75,
        )
        self.assertEqual(result["outcome"], "direct_encounter")
        self.assertFalse(result["is_final"])
        self.assertTrue(result["requires_new_dragon"])
        self.assertIsNone(result["dragon_id"])

    def test_case_7_three_repeated_searches_apply_recent_history_penalty(self) -> None:
        structured = action(
            "observe_search",
            "我找龙",
            target="龙",
            intent="找龙",
        )
        outcomes = [
            self.decide(
                structured,
                current_location="whispering_woods",
                recent_history=[history("direct_encounter")] * count,
                roll=1.0,
            )["outcome"]
            for count in range(3)
        ]
        self.assertEqual(outcomes, ["direct_encounter", "sighting", "trace"])

    def test_none_trace_none_history_has_no_penalty(self) -> None:
        self.assertEqual(
            _recent_history_penalty(
                [history("none"), history("trace"), history("none")]
            ),
            0,
        )

    def test_three_trace_decisions_have_no_penalty(self) -> None:
        self.assertEqual(
            _recent_history_penalty([history("trace")] * 3),
            0,
        )

    def test_sighting_has_two_point_penalty(self) -> None:
        self.assertEqual(_recent_history_penalty([history("sighting")]), 2)

    def test_direct_encounter_has_two_point_penalty(self) -> None:
        self.assertEqual(
            _recent_history_penalty([history("direct_encounter")]),
            2,
        )

    def test_mixed_history_penalizes_only_high_level_encounters(self) -> None:
        self.assertEqual(
            _recent_history_penalty(
                [
                    history("sighting"),
                    history("trace"),
                    history("none"),
                    history("direct_encounter"),
                ]
            ),
            4,
        )

    def test_high_level_encounter_penalty_still_caps_at_six(self) -> None:
        self.assertEqual(
            _recent_history_penalty([history("sighting")] * 5),
            6,
        )

    def test_none_trace_history_preserves_first_dragon_discovery_space(self) -> None:
        structured = action(
            "observe_search",
            "深入森林仔细寻找龙",
            target="龙",
            intent="寻找龙",
        )
        recent_history = [history("none"), history("trace"), history("none")]
        low = self.decide(
            structured,
            current_location="whispering_woods",
            recent_history=recent_history,
            roll=0.0,
        )
        high = self.decide(
            structured,
            current_location="whispering_woods",
            recent_history=recent_history,
            roll=0.5,
        )
        self.assertEqual(low["context_score"], 8)
        self.assertEqual(low["outcome"], "trace")
        self.assertEqual(high["context_score"], 8)
        self.assertEqual(high["outcome"], "sighting")

    def test_case_8_blocked_dragon_ride_is_none(self) -> None:
        result = self.decide(
            action(
                "travel",
                "骑我的龙去 Stormcliff",
                target="我的龙",
                destination="Stormcliff",
                method="骑龙",
            ),
            current_location="skeld_village",
            d2_resolution=resolution(
                "blocked",
                effect_scope="domain_route",
                reason_code="dragon_riding_not_grounded",
                domain_route="dragon",
            ),
            roll=1.0,
        )
        self.assertEqual(result["outcome"], "none")
        self.assertEqual(result["reason_code"], "d2_action_blocked")

    def test_case_9_open_exploration_is_eligible_without_location_creation(self) -> None:
        structured = action(
            "explore",
            "沿北边森林继续探索寻找龙",
            direction="北边",
            intent="寻找龙",
        )
        before = copy.deepcopy(structured)
        result = self.decide(
            structured,
            current_location="whispering_woods",
            roll=0.0,
        )
        self.assertNotEqual(result["reason_code"], "action_not_eligible")
        self.assertEqual(structured, before)
        self.assertNotIn("current_location", result)

    def test_case_10_trace_read_path_does_not_create_or_mutate_dragon(self) -> None:
        persistence = ReadOnlyPersistence(
            current_location="whispering_woods",
            dragons=[],
        )
        before = copy.deepcopy(persistence.__dict__)
        result = decide_current_dragon_encounter(
            player_id="player_test",
            structured_action=action(
                "observe_search",
                "寻找巨大的脚印",
                target="巨大的脚印",
            ),
            resolution=resolution(),
            persistence=persistence,  # type: ignore[arg-type]
            world_skeleton=self.skeleton,
            roll=0.2,
        )
        self.assertEqual(result["outcome"], "trace")
        self.assertEqual(persistence.player_state, before["player_state"])
        self.assertEqual(persistence.dragons, before["dragons"])
        self.assertEqual(
            [call[0] for call in persistence.calls],
            [
                "get_player_state",
                "list_dragons_at_location",
                "list_recent_dragon_encounter_decisions",
            ],
        )

    def test_case_11_existing_sighting_uses_recent_dragon_then_stable_id(self) -> None:
        structured = action(
            "observe_search",
            "观察附近的龙",
            target="龙",
            intent="观察龙",
        )
        dragons = [dragon("dragon_a"), dragon("dragon_b")]
        recent = self.decide(
            structured,
            current_location="whispering_woods",
            existing_dragons=dragons,
            recent_history=[history("sighting", dragon_id="dragon_b")],
            roll=0.75,
        )
        stable = self.decide(
            structured,
            current_location="whispering_woods",
            existing_dragons=dragons,
            roll=0.25,
        )
        self.assertEqual(recent["outcome"], "sighting")
        self.assertEqual(recent["dragon_id"], "dragon_b")
        self.assertEqual(stable["outcome"], "sighting")
        self.assertEqual(stable["dragon_id"], "dragon_a")

    def test_case_12_ordinary_npc_dialogue_is_none(self) -> None:
        result = self.decide(
            action(
                "interact",
                "和 Astrid 对话",
                target="Astrid",
                intent="询问村庄消息",
            ),
            current_location="skeld_village",
            d2_resolution=resolution(
                "partial",
                effect_scope="domain_route",
                reason_code="npc_runtime_required",
                domain_route="npc",
            ),
            roll=1.0,
        )
        self.assertEqual(result["outcome"], "none")
        self.assertEqual(result["reason_code"], "action_not_eligible")

    def test_direct_encounter_excludes_avoiding_and_flying_dragons(self) -> None:
        result = self.decide(
            action(
                "observe_search",
                "在风暴崖寻找龙巢",
                target="龙巢",
                intent="寻找龙",
            ),
            current_location="stormcliff",
            existing_dragons=[
                dragon("dragon_avoiding", behavior_state="avoiding"),
                dragon("dragon_flying", behavior_state="flying"),
            ],
            roll=0.5,
        )
        self.assertEqual(result["outcome"], "direct_encounter")
        self.assertFalse(result["is_final"])
        self.assertTrue(result["requires_new_dragon"])

    def test_unresolved_explicit_dragon_does_not_reuse_another_dragon(self) -> None:
        result = self.decide(
            action(
                "observe_search",
                "寻找 Frostwing",
                target="Frostwing",
                intent="寻找那条龙",
            ),
            current_location="whispering_woods",
            existing_dragons=[dragon("dragon_a", name="Ember")],
            roll=0.25,
        )
        self.assertEqual(result["outcome"], "sighting")
        self.assertFalse(result["is_final"])
        self.assertTrue(result["requires_new_dragon"])
        self.assertIsNone(result["dragon_id"])


if __name__ == "__main__":
    unittest.main()
