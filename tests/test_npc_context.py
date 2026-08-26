"""Offline information-boundary tests for NPC Context Builder v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from npc.context_builder import (
    NpcContextError,
    build_npc_context,
    load_anchor_profiles,
    load_context_schema,
    load_profile_schema,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = load_json(SEED_PATH)
        cls.profiles = load_anchor_profiles()
        cls.profile_schema = load_profile_schema()
        cls.context_schema = load_context_schema()
        cls.seed_hash = file_hash(SEED_PATH)
        cls.save_hash = file_hash(SAVE_PATH)

    @classmethod
    def tearDownClass(cls) -> None:
        if file_hash(SEED_PATH) != cls.seed_hash:
            raise AssertionError("world_seed.json changed during NPC Context tests")
        if file_hash(SAVE_PATH) != cls.save_hash:
            raise AssertionError("current_world.json changed during NPC Context tests")

    def build_astrid(self, world_state: dict[str, Any] | None = None) -> dict[str, Any]:
        return build_npc_context(
            "npc_astrid",
            copy.deepcopy(world_state or self.world_state),
            profiles_document=copy.deepcopy(self.profiles),
            profile_schema=self.profile_schema,
            context_schema=self.context_schema,
        )

    def test_case_1_same_location_is_true(self) -> None:
        context = self.build_astrid()
        self.assertTrue(context["shared_context"]["same_location"])
        self.assertEqual(context["runtime_state"]["current_location"], "skeld_village")
        self.assertEqual(context["player"]["current_location"], "skeld_village")

    def test_case_2_different_location_is_false(self) -> None:
        world_state = copy.deepcopy(self.world_state)
        world_state["player"]["current_location"] = "stormcliff"
        context = self.build_astrid(world_state)
        self.assertFalse(context["shared_context"]["same_location"])
        self.assertEqual(context["runtime_state"]["current_location"], "skeld_village")
        self.assertEqual(context["player"]["current_location"], "stormcliff")

    def test_case_3_known_entity_is_explicit_and_minimal(self) -> None:
        context = self.build_astrid()
        self.assertEqual(
            context["knowledge"]["known_entities"],
            [
                {
                    "id": "npc_bjorn",
                    "name": "Bjorn",
                    "species": "human",
                    "occupation": "blacksmith",
                }
            ],
        )

    def test_case_4_other_npc_private_profile_is_hidden(self) -> None:
        context = self.build_astrid()
        known_bjorn = context["knowledge"]["known_entities"][0]
        self.assertEqual(
            set(known_bjorn),
            {"id", "name", "species", "occupation"},
        )
        serialized = json.dumps(known_bjorn).casefold()
        for private_field in (
            "personality",
            "background",
            "goals",
            "knowledge",
            "memory_policy",
            "relationship_defaults",
            "current_goal",
            "mood",
        ):
            self.assertNotIn(private_field, serialized)

    def test_case_5_raw_world_state_is_not_embedded(self) -> None:
        context = self.build_astrid()
        self.assertEqual(
            set(context),
            {"npc", "runtime_state", "player", "shared_context", "knowledge"},
        )
        for forbidden_key in (
            "world",
            "locations",
            "npcs",
            "global_state",
            "rules",
            "relationships",
            "memories",
        ):
            self.assertNotIn(forbidden_key, context)
        self.assertNotIn("village_safety", json.dumps(context))

    def test_case_6_output_matches_context_schema(self) -> None:
        Draft202012Validator.check_schema(self.context_schema)
        Draft202012Validator(self.context_schema).validate(self.build_astrid())

    def test_case_7_unknown_npc_id_fails_without_creation(self) -> None:
        before = copy.deepcopy(self.world_state)
        with self.assertRaisesRegex(NpcContextError, "Unknown NPC Profile id"):
            build_npc_context(
                "npc_unknown",
                self.world_state,
                profiles_document=self.profiles,
                profile_schema=self.profile_schema,
                context_schema=self.context_schema,
            )
        self.assertEqual(self.world_state, before)

    def test_case_8_profile_and_world_state_id_mismatch_fails(self) -> None:
        world_state = copy.deepcopy(self.world_state)
        world_state["npcs"]["astrid"]["id"] = "npc_astrid_mismatch"
        before = copy.deepcopy(world_state)
        with self.assertRaisesRegex(
            NpcContextError,
            "does not resolve to Persistent World State",
        ):
            self.build_astrid(world_state)
        self.assertEqual(world_state, before)


if __name__ == "__main__":
    unittest.main()
