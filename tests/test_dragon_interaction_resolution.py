"""D4-B offline deterministic Dragon interaction resolution tests."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from core.dragon_interaction_resolution import resolve_dragon_interaction


DRAGON_ID = "dragon_kael_test"


def action(
    family: str,
    text: str,
    *,
    target: str | None = "Kael",
    intent: str | None = None,
    method: str | None = None,
    needs_clarification: bool = False,
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
        "needs_clarification": needs_clarification,
    }


def dragon(
    *,
    archetype_id: str = "balanced_wild",
    behavior_state: str = "watching",
    taming_state: str = "wild",
    location: str = "stormcliff",
) -> dict[str, Any]:
    return {
        "dragon_id": DRAGON_ID,
        "archetype_id": archetype_id,
        "name": "Kael",
        "current_location": location,
        "behavior_state": behavior_state,
        "taming_state": taming_state,
        "temperament_traits": ["谨慎", "善于观察"],
    }


def bond(
    familiarity: int = 0,
    trust: int = 0,
    fear: int = 0,
    bond_value: int = 0,
    *,
    riding_unlocked: bool = False,
) -> dict[str, Any]:
    return {
        "familiarity": familiarity,
        "trust": trust,
        "fear": fear,
        "bond": bond_value,
        "riding_unlocked": riding_unlocked,
    }


class DragonInteractionResolutionTests(unittest.TestCase):
    def resolve(
        self,
        structured_action: dict[str, Any],
        *,
        dragon_value: dict[str, Any] | None = None,
        player_location: str = "stormcliff",
        bond_value: dict[str, Any] | None = None,
        recent_history: list[dict[str, Any]] | None = None,
        positive_categories: list[str] | None = None,
        inventory: list[Any] | None = None,
        source: str = "interaction_event_d4b_test",
    ) -> dict[str, Any]:
        return resolve_dragon_interaction(
            structured_action,
            source_interaction_event_id=source,
            player_id="player_001",
            dragon_id=DRAGON_ID,
            dragon=dragon() if dragon_value is None else dragon_value,
            player_location=player_location,
            bond=bond_value,
            recent_history=recent_history or [],
            positive_categories=positive_categories or [],
            player_inventory=inventory or [],
        )

    def test_case_1_wild_no_bond_observe_is_neutral(self) -> None:
        result = self.resolve(action("observe_search", "远远观察 Kael"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["interaction_type"], "observe")
        self.assertEqual(result["dragon_reaction"], "wary")
        self.assertEqual(result["relationship_effect"], "neutral")
        self.assertEqual(set(result["state_changes"].values()), {0})

    def test_case_2_slow_approach_is_cautious_and_small(self) -> None:
        result = self.resolve(
            action("interact", "慢慢靠近 Kael", method="缓慢而小心地靠近")
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["interaction_type"], "approach")
        self.assertEqual(result["dragon_reaction"], "wary")
        self.assertEqual(result["state_changes"]["familiarity_delta"], 1)
        self.assertEqual(result["state_changes"]["trust_delta"], 0)
        self.assertEqual(result["state_changes"]["bond_delta"], 0)

    def test_case_3_grounded_food_offer_is_positive(self) -> None:
        result = self.resolve(
            action("interact", "把食物放下然后后退", method="放下食物并后退"),
            inventory=[{"item_id": "fish_001", "category": "food", "quantity": 1}],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["interaction_type"], "offer_food")
        self.assertEqual(result["dragon_reaction"], "accepting")
        self.assertEqual(result["relationship_effect"], "positive")
        self.assertEqual(result["positive_category"], "food")
        self.assertEqual(result["anti_farming"], "full")
        self.assertEqual(result["state_changes"]["familiarity_delta"], 1)
        self.assertEqual(result["state_changes"]["trust_delta"], 1)
        self.assertIsNone(result["significant_event"])

    def test_case_4_reckless_hug_is_blocked_and_defensive(self) -> None:
        result = self.resolve(action("interact", "突然冲过去抱住 Kael"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["interaction_type"], "touch")
        self.assertEqual(result["dragon_reaction"], "defensive")
        self.assertEqual(result["relationship_effect"], "negative")
        self.assertLessEqual(result["state_changes"]["trust_delta"], 0)
        self.assertEqual(result["positive_category"], None)

    def test_case_5_wild_ride_attempt_is_blocked(self) -> None:
        result = self.resolve(
            action("travel", "骑 Kael 前往 Skeld", intent="骑乘 Kael")
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["interaction_type"], "ride_attempt")
        self.assertEqual(result["reason_code"], "dragon_not_tamed")
        self.assertEqual(set(result["state_changes"].values()), {0})

    def test_case_6_three_consecutive_food_offers_diminish(self) -> None:
        food_action = action("interact", "放下食物给 Kael", method="放下食物")
        inventory = [{"category": "food", "quantity": 3}]
        first = self.resolve(food_action, inventory=inventory, source="event_food_1")
        second = self.resolve(
            food_action,
            inventory=inventory,
            recent_history=[first],
            source="event_food_2",
        )
        third = self.resolve(
            food_action,
            inventory=inventory,
            recent_history=[second, first],
            source="event_food_3",
        )
        self.assertEqual(
            [first["anti_farming"], second["anti_farming"], third["anti_farming"]],
            ["full", "familiarity_only", "zero"],
        )
        self.assertEqual(second["state_changes"]["trust_delta"], 0)
        self.assertEqual(set(third["state_changes"].values()), {0})

    def test_case_7_first_positive_is_proposed_without_mutating_inputs(self) -> None:
        dragon_value = dragon()
        inventory = [{"category": "food", "quantity": 1}]
        dragon_before = copy.deepcopy(dragon_value)
        inventory_before = copy.deepcopy(inventory)
        result = self.resolve(
            action("interact", "放下食物给 Kael"),
            dragon_value=dragon_value,
            inventory=inventory,
        )
        self.assertEqual(result["relationship_effect"], "positive")
        self.assertEqual(dragon_value, dragon_before)
        self.assertEqual(inventory, inventory_before)
        self.assertNotIn("after", result["state_changes"])

    def test_case_8_multiple_positive_contexts_have_distinct_categories(self) -> None:
        close = self.resolve(
            action("interact", "慢慢靠近 Kael", method="小心靠近")
        )
        food = self.resolve(
            action("interact", "放下食物给 Kael"),
            inventory=[{"type": "food", "quantity": 1}],
        )
        touch = self.resolve(
            action("interact", "轻轻触碰 Kael", method="小心触碰"),
            dragon_value=dragon(taming_state="tolerant"),
            bond_value=bond(2, 2, 0, 0),
        )
        self.assertEqual(
            {close["positive_category"], food["positive_category"], touch["positive_category"]},
            {"close_presence", "food", "touch"},
        )

    def test_case_9_player_taming_claim_does_not_change_truth(self) -> None:
        dragon_value = dragon()
        before = copy.deepcopy(dragon_value)
        result = self.resolve(action("other", "Kael 已经被我驯服了"), dragon_value=dragon_value)
        self.assertEqual(result["interaction_type"], "other")
        self.assertEqual(result["relationship_effect"], "neutral")
        self.assertEqual(set(result["state_changes"].values()), {0})
        self.assertEqual(dragon_value, before)

    def test_case_10_taming_threshold_is_preview_only(self) -> None:
        dragon_value = dragon(taming_state="bonding")
        before = copy.deepcopy(dragon_value)
        result = self.resolve(
            action("interact", "轻轻触碰 Kael", method="小心触碰"),
            dragon_value=dragon_value,
            bond_value=bond(3, 2, 0, 1),
            positive_categories=["food", "close_presence"],
        )
        self.assertEqual(result["next_taming_state_preview"], "tamed")
        self.assertIsNone(result["significant_event"])
        self.assertEqual(dragon_value, before)
        self.assertEqual(dragon_value["taming_state"], "bonding")

    def test_case_11_tamed_but_locked_ride_is_blocked(self) -> None:
        result = self.resolve(
            action("travel", "骑上 Kael", intent="骑乘"),
            dragon_value=dragon(taming_state="tamed"),
            bond_value=bond(5, 5, 0, 4, riding_unlocked=False),
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "dragon_riding_not_unlocked")

    def test_case_12_cross_location_physical_interaction_is_blocked(self) -> None:
        result = self.resolve(
            action("interact", "慢慢靠近 Kael", method="小心靠近"),
            player_location="skeld",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "dragon_not_in_interaction_range")
        self.assertEqual(set(result["state_changes"].values()), {0})

    def test_case_13_threat_is_negative_and_schema_clamped(self) -> None:
        result = self.resolve(
            action("conflict", "挥剑威胁 Kael"),
            dragon_value=dragon(archetype_id="powerful_wild"),
            bond_value=bond(2, 1, 0, 1),
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["interaction_type"], "threaten")
        self.assertEqual(result["dragon_reaction"], "defensive")
        self.assertEqual(result["relationship_effect"], "negative")
        self.assertEqual(result["state_changes"]["trust_delta"], -1)
        self.assertEqual(result["state_changes"]["fear_delta"], 1)
        self.assertEqual(result["state_changes"]["bond_delta"], -1)
        self.assertEqual(result["anti_farming"], "not_applicable")

    def test_case_14_third_repeated_positive_has_zero_gain(self) -> None:
        result = self.resolve(
            action("interact", "慢慢后退", method="后退"),
            recent_history=[
                {"interaction_type": "retreat"},
                {"interaction_type": "retreat"},
            ],
        )
        self.assertEqual(result["anti_farming"], "zero")
        self.assertEqual(set(result["state_changes"].values()), {0})

    def test_different_effective_type_resets_consecutive_repeat_chain(self) -> None:
        result = self.resolve(
            action("interact", "放下食物给 Kael"),
            inventory=[{"category": "food", "quantity": 1}],
            recent_history=[
                {"interaction_type": "approach"},
                {"interaction_type": "offer_food"},
                {"interaction_type": "offer_food"},
            ],
        )
        self.assertEqual(result["anti_farming"], "full")

    def test_unstructured_food_claim_fails_closed(self) -> None:
        result = self.resolve(
            action("interact", "拿出一条鱼喂 Kael"),
            inventory=["fish"],
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "offered_food_not_grounded")

    def test_agile_archetype_is_more_cautious_about_reckless_approach(self) -> None:
        result = self.resolve(
            action("interact", "冲过去靠近 Kael"),
            dragon_value=dragon(archetype_id="agile_wild"),
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["dragon_reaction"], "defensive")

    def test_needs_clarification_fails_closed(self) -> None:
        result = self.resolve(
            action(
                "other",
                "处理那条龙",
                target="那条龙",
                needs_clarification=True,
            )
        )
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(set(result["state_changes"].values()), {0})

    def test_case_19_calm_communication_is_positive_without_bond_delta(self) -> None:
        result = self.resolve(
            action(
                "interact",
                "我平静地和 Kael 说话",
                intent="安抚 Kael",
                method="轻声说话",
            )
        )
        self.assertEqual(result["interaction_type"], "communicate")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["dragon_reaction"], "wary")
        self.assertEqual(result["relationship_effect"], "positive")
        self.assertEqual(result["positive_category"], "communication")
        self.assertEqual(result["state_changes"]["familiarity_delta"], 1)
        self.assertEqual(result["state_changes"]["trust_delta"], 1)
        self.assertEqual(result["state_changes"]["bond_delta"], 0)

    def test_case_20_three_consecutive_communications_diminish(self) -> None:
        communicate = action(
            "interact",
            "轻声和 Kael 说话",
            intent="平静交流",
        )
        first = self.resolve(communicate, source="event_talk_1")
        second = self.resolve(
            communicate,
            recent_history=[first],
            source="event_talk_2",
        )
        third = self.resolve(
            communicate,
            recent_history=[second, first],
            source="event_talk_3",
        )
        self.assertEqual(
            [first["anti_farming"], second["anti_farming"], third["anti_farming"]],
            ["full", "familiarity_only", "zero"],
        )
        self.assertEqual(second["state_changes"]["trust_delta"], 0)
        self.assertEqual(set(third["state_changes"].values()), {0})

    def test_case_21_three_mvp_positive_categories_are_reachable(self) -> None:
        close = self.resolve(
            action("interact", "慢慢靠近 Kael", method="小心靠近")
        )
        communication = self.resolve(
            action("interact", "平静地和 Kael 说话", method="轻声说话"),
            bond_value=bond(1, 0, 0, 0),
            positive_categories=["close_presence"],
        )
        touch = self.resolve(
            action("interact", "轻轻触碰 Kael", method="小心触碰"),
            dragon_value=dragon(taming_state="tolerant"),
            bond_value=bond(3, 2, 0, 0),
            positive_categories=["close_presence", "communication"],
        )
        self.assertEqual(close["positive_category"], "close_presence")
        self.assertEqual(communication["positive_category"], "communication")
        self.assertEqual(touch["positive_category"], "touch")
        self.assertEqual(touch["relationship_effect"], "positive")
        self.assertEqual(touch["next_taming_state_preview"], "bonding")

    def test_case_22_tolerant_threshold_is_explicit_preview_only(self) -> None:
        dragon_value = dragon()
        before = copy.deepcopy(dragon_value)
        result = self.resolve(
            action("interact", "轻声和 Kael 交流", method="平静说话"),
            dragon_value=dragon_value,
            bond_value=bond(1, 0, 0, 0),
        )
        self.assertEqual(result["next_taming_state_preview"], "tolerant")
        self.assertEqual(dragon_value, before)
        self.assertEqual(dragon_value["taming_state"], "wild")

    def test_case_23_third_category_previews_tamed_without_commit(self) -> None:
        dragon_value = dragon(taming_state="bonding")
        before = copy.deepcopy(dragon_value)
        result = self.resolve(
            action("interact", "轻轻触碰 Kael", method="小心触碰"),
            dragon_value=dragon_value,
            bond_value=bond(3, 2, 0, 1),
            positive_categories=["close_presence", "communication"],
        )
        self.assertEqual(result["positive_category"], "touch")
        self.assertEqual(result["next_taming_state_preview"], "tamed")
        self.assertIsNone(result["significant_event"])
        self.assertEqual(dragon_value, before)

    def test_case_24_other_player_history_does_not_affect_anti_farming(self) -> None:
        result = self.resolve(
            action("interact", "平静地和 Kael 说话", method="轻声说话"),
            recent_history=[
                {
                    "player_id": "player_other",
                    "dragon_id": DRAGON_ID,
                    "interaction_type": "communicate",
                },
                {
                    "player_id": "player_other",
                    "dragon_id": DRAGON_ID,
                    "interaction_type": "communicate",
                },
            ],
        )
        self.assertEqual(result["anti_farming"], "full")


if __name__ == "__main__":
    unittest.main()
