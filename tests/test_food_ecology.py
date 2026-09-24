"""Offline tests for model proposed food and habitat grounding."""

from __future__ import annotations

import json
import unittest

from core.food_ecology import (
    choose_food_candidate,
    explicit_food_candidate,
    favorite_food_kind,
    food_action_kind,
    select_food_item,
)


class FoodProvider:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = 0

    def create_structured_output(self, **_: object) -> str:
        self.calls += 1
        return json.dumps({"food_kind": self.kind})


class FoodEcologyTests(unittest.TestCase):
    def test_buying_a_nonfood_item_stays_outside_food_rules(self) -> None:
        self.assertIsNone(food_action_kind({"action": "买一把剑", "target": "剑"}))

    def test_older_named_fish_is_edible_but_fishing_gear_is_not(self) -> None:
        offer = {"action": "把大鱼放在凯尔面前，后退等它取食", "target": "凯尔"}
        fish = {"id": "carried_fish", "name": "一条大鱼", "quantity": 1}
        gear = {"id": "carried_rod", "name": "鱼竿", "quantity": 1}
        self.assertEqual(select_food_item([fish, gear], offer), fish)
        self.assertIsNone(select_food_item([gear], offer))

    def test_fishing_language_is_a_grounded_hunt(self) -> None:
        self.assertEqual(food_action_kind({"action": "在雾蚀凹湾打鱼", "target": "鱼"}), "hunt")
        self.assertEqual(food_action_kind({"action": "打到一条大鱼并装进背包", "target": "一条大鱼"}), "hunt")
        self.assertEqual(choose_food_candidate(
            {"action": "在雾蚀凹湾打鱼", "target": "鱼"},
            location_id="location_dynamic_cove",
            location={"name": "雾蚀凹湾", "type": "wild_area"},
        ), {"food_kind": "fish", "name": "鲜鱼"})

    def test_model_can_choose_only_food_available_in_the_habitat(self) -> None:
        location = {"name": "低语森林", "type": "forest"}
        valid = FoodProvider("venison")
        candidate = choose_food_candidate(
            {"action": "我打猎", "target": None, "intent": None, "method": None},
            location_id="whispering_woods",
            location=location,
            provider_client=valid,  # type: ignore[arg-type]
        )
        self.assertEqual(candidate, {"food_kind": "venison", "name": "鹿肉"})
        self.assertEqual(valid.calls, 1)

        invalid = FoodProvider("human")
        candidate = choose_food_candidate(
            {"action": "我打猎", "target": None, "intent": None, "method": None},
            location_id="whispering_woods",
            location=location,
            provider_client=invalid,  # type: ignore[arg-type]
        )
        self.assertIn(candidate["food_kind"], {"venison", "rabbit", "boar"})

    def test_explicit_food_grounding_has_no_provider_or_random_dependency(self) -> None:
        location = {"name": "低语森林", "type": "forest"}
        self.assertEqual(
            explicit_food_candidate(
                {"action": "我猎取一只鹿", "target": "鹿"},
                location_id="whispering_woods",
                location=location,
            ),
            {"food_kind": "venison", "name": "鹿肉"},
        )
        self.assertIsNone(explicit_food_candidate(
            {"action": "我打猎", "target": None},
            location_id="whispering_woods",
            location=location,
        ))

    def test_dragon_preference_is_stable_and_habitat_specific(self) -> None:
        cliff = {"dragon_id": "kael", "current_location": "stormcliff", "archetype_id": "balanced_wild"}
        forest = {"dragon_id": "kael", "current_location": "whispering_woods", "archetype_id": "balanced_wild"}
        self.assertEqual(favorite_food_kind(cliff), favorite_food_kind(cliff))
        self.assertIn(favorite_food_kind(cliff), {"goat", "mutton", "seabird"})
        self.assertIn(favorite_food_kind(forest), {"venison", "rabbit", "boar"})
        travelled = {**cliff, "current_location": "whispering_woods", "habitat_location": "stormcliff"}
        self.assertEqual(favorite_food_kind(cliff), favorite_food_kind(travelled))


if __name__ == "__main__":
    unittest.main()
