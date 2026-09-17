"""D7 presentation-only Scene Visual tests without real provider calls."""

from __future__ import annotations

import unittest

from multimodal.scene_renderer import (
    DisabledSceneImageProvider,
    build_visual_context,
    render_scene_visual,
    visual_trigger,
)


class StubImageProvider:
    name = "stub"
    enabled = True

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider unavailable")
        return "https://images.example.test/dragon-world.png"


def world(*, mounted: bool = False) -> dict[str, object]:
    return {
        "player": {"player_id": "player_001"},
        "world": {"name": "Dragon Isles", "day": 1, "hour": 8, "weather": "cloudy"},
        "current_location": {
            "id": "stormcliff",
            "name": "Stormcliff",
            "type": "wild_area",
            "description": "常年受到强风和暴风雨影响的海崖",
        },
        "nearby_npcs": [],
        "nearby_dragons": [
            {
                "dragon_id": "dragon_kael",
                "name": "Kael",
                "appearance": {"description": "dark scales"},
                "behavior_state": "watching",
                "taming_state": "tamed",
            }
        ],
        "riding": {
            "is_mounted": mounted,
            "mounted_dragon_id": "dragon_kael" if mounted else None,
            "mounted_dragon_name": "Kael" if mounted else None,
        },
    }


def result(trigger: str | None) -> dict[str, object]:
    base: dict[str, object] = {
        "location_discovery": None,
        "dragon_encounter": {"outcome": "none"},
        "dragon_riding": None,
    }
    if trigger == "discovery":
        base["location_discovery"] = {"location_id": "dynamic_1"}
    elif trigger == "encounter":
        base["dragon_encounter"] = {"outcome": "direct_encounter"}
    elif trigger == "mount":
        base["dragon_riding"] = {
            "status": "success",
            "reason_code": "riding_mounted",
        }
    elif trigger == "arrival":
        base["dragon_riding"] = {
            "status": "success",
            "reason_code": "riding_arrived",
        }
    return base


class SceneRendererTests(unittest.TestCase):
    def test_ordinary_action_has_no_visual_trigger(self) -> None:
        provider = StubImageProvider()
        self.assertIsNone(
            render_scene_visual(
                action_result=result(None),
                world=world(),
                provider=provider,
            )
        )
        self.assertEqual(provider.prompts, [])

    def test_four_high_value_triggers_are_supported(self) -> None:
        expected = {
            "discovery": "dynamic_location_discovery",
            "encounter": "dragon_encounter",
            "mount": "dragon_mount",
            "arrival": "mounted_travel_arrival",
        }
        for case, trigger in expected.items():
            with self.subTest(case=case):
                self.assertEqual(visual_trigger(result(case)), trigger)

    def test_visual_context_uses_formal_world_truth(self) -> None:
        context = build_visual_context(
            trigger="dragon_encounter",
            world=world(),
        )
        self.assertEqual(context["camera"], "first_person")
        self.assertEqual(context["player_location"]["location_id"], "stormcliff")
        self.assertEqual(context["weather"], "cloudy")
        self.assertEqual(context["dragon_presence"][0]["name"], "Kael")

    def test_mount_and_arrival_use_dragon_back_camera(self) -> None:
        provider = StubImageProvider()
        visual = render_scene_visual(
            action_result=result("arrival"),
            world=world(mounted=True),
            provider=provider,
        )
        assert visual is not None
        self.assertEqual(visual["status"], "generated")
        self.assertEqual(visual["camera"], "first_person_dragon_back")
        self.assertEqual(
            visual["image_url"],
            "https://images.example.test/dragon-world.png",
        )
        self.assertIn("first_person_dragon_back", provider.prompts[0])

    def test_provider_failure_is_graceful(self) -> None:
        visual = render_scene_visual(
            action_result=result("encounter"),
            world=world(),
            provider=StubImageProvider(fail=True),
        )
        assert visual is not None
        self.assertEqual(visual["status"], "failed")
        self.assertIsNone(visual["image_url"])

    def test_missing_key_disabled_state_is_graceful(self) -> None:
        visual = render_scene_visual(
            action_result=result("discovery"),
            world=world(),
            provider=DisabledSceneImageProvider("missing key"),
        )
        assert visual is not None
        self.assertEqual(visual["status"], "disabled")
        self.assertIsNone(visual["image_url"])


if __name__ == "__main__":
    unittest.main()
