"""Offline schema and boundary checks for Generic NPC Profile v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_profile.schema.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"

RUNTIME_ONLY_FIELDS = {
    "current_location",
    "current_activity",
    "current_goal",
    "mood",
    "temporary_status",
    "relationships",
    "memories",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys.update(nested_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(nested_keys(child))
    return keys


class NpcProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.profile_document = load_json(PROFILES_PATH)
        cls.world_seed = load_json(SEED_PATH)
        cls.profiles = cls.profile_document["profiles"]
        cls.validator = Draft202012Validator(cls.schema)
        cls.seed_hash = file_hash(SEED_PATH)
        cls.save_hash = file_hash(SAVE_PATH)

    @classmethod
    def tearDownClass(cls) -> None:
        if file_hash(SEED_PATH) != cls.seed_hash:
            raise AssertionError("world_seed.json changed during NPC Profile tests")
        if file_hash(SAVE_PATH) != cls.save_hash:
            raise AssertionError("current_world.json changed during NPC Profile tests")

    def test_schema_and_all_anchor_profiles_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.assertEqual(self.profile_document["version"], "0.1")
        self.assertEqual(len(self.profiles), 3)
        for profile in self.profiles:
            with self.subTest(npc_id=profile["id"]):
                self.validator.validate(profile)

    def test_npc_ids_are_unique(self) -> None:
        profile_ids = [profile["id"] for profile in self.profiles]
        self.assertEqual(len(profile_ids), len(set(profile_ids)))

    def test_profile_ids_align_with_world_state_entities(self) -> None:
        seed_npcs = self.world_seed["npcs"]
        seed_by_id = {npc["id"]: npc for npc in seed_npcs.values()}
        profile_by_id = {profile["id"]: profile for profile in self.profiles}
        self.assertEqual(set(profile_by_id), set(seed_by_id))

        for npc_id, profile in profile_by_id.items():
            with self.subTest(npc_id=npc_id):
                seed_npc = seed_by_id[npc_id]
                self.assertEqual(profile["name"], seed_npc["name"])
                self.assertEqual(profile["species"], seed_npc["species"])
                self.assertEqual(profile["occupation"], seed_npc["occupation"])

    def test_profiles_do_not_duplicate_runtime_state(self) -> None:
        schema_fields = set(self.schema["properties"])
        self.assertTrue(RUNTIME_ONLY_FIELDS.isdisjoint(schema_fields))

        for profile in self.profiles:
            with self.subTest(npc_id=profile["id"]):
                self.assertTrue(
                    RUNTIME_ONLY_FIELDS.isdisjoint(nested_keys(profile))
                )

                invalid_profile = copy.deepcopy(profile)
                invalid_profile["current_location"] = "skeld_village"
                self.assertFalse(self.validator.is_valid(invalid_profile))

    def test_anchor_personalities_are_distinct(self) -> None:
        traits_by_id = {
            profile["id"]: frozenset(profile["personality"]["traits"])
            for profile in self.profiles
        }
        self.assertEqual(len(set(traits_by_id.values())), len(self.profiles))

        ids = list(traits_by_id)
        for index, npc_id in enumerate(ids):
            for other_id in ids[index + 1 :]:
                with self.subTest(npc_id=npc_id, other_id=other_id):
                    self.assertNotEqual(traits_by_id[npc_id], traits_by_id[other_id])
                    self.assertTrue(traits_by_id[npc_id] - traits_by_id[other_id])
                    self.assertTrue(traits_by_id[other_id] - traits_by_id[npc_id])

    def test_knowledge_references_only_existing_entities_and_locations(self) -> None:
        valid_entity_ids = {
            self.world_seed["player"]["id"],
            *(npc["id"] for npc in self.world_seed["npcs"].values()),
        }
        valid_location_ids = set(self.world_seed["locations"])

        for profile in self.profiles:
            with self.subTest(npc_id=profile["id"]):
                self.assertTrue(
                    set(profile["knowledge"]["known_entities"])
                    <= valid_entity_ids
                )
                self.assertTrue(
                    set(profile["knowledge"]["known_locations"])
                    <= valid_location_ids
                )


if __name__ == "__main__":
    unittest.main()
