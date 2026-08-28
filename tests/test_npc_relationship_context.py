"""Offline tests for read-only NPC Relationship Context v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from npc.relationship_context import (
    NpcRelationshipContextError,
    build_relationship_context,
    load_relationship_context_schema,
    validate_relationship_context,
)
from npc.relationship_store import RELATIONSHIP_STORE_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "data" / "npc_relationship_response_test_cases.json"
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "saves" / "npc_memories.json",
    RELATIONSHIP_STORE_PATH,
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "npc" / "relationship_store.py",
    PROJECT_ROOT / "schemas" / "npc_relationship.schema.json",
    PROJECT_ROOT / "schemas" / "npc_relationship_store.schema.json",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcRelationshipContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        cls.fixtures = dataset["relationship_fixtures"]
        cls.schema = load_relationship_context_schema()
        cls.protected_hashes = {
            path: file_hash(path) for path in PROTECTED_PATHS
        }

    @classmethod
    def tearDownClass(cls) -> None:
        changed = [
            path
            for path, digest in cls.protected_hashes.items()
            if file_hash(path) != digest
        ]
        if changed:
            raise AssertionError(
                "Relationship Context tests changed Persistent State or a Frozen "
                "Baseline: " + ", ".join(str(path) for path in changed)
            )

    def test_context_schema_accepts_minimal_view(self) -> None:
        context = {
            "npc_id": "npc_astrid",
            "player_id": "player_001",
            "familiarity": 1,
            "trust": 0,
            "attitude": "neutral",
            "relationship_exists": False,
        }
        validate_relationship_context(context, self.schema)

    def test_persistent_pair_loads_exact_values(self) -> None:
        context = build_relationship_context(
            "npc_astrid",
            "player_001",
            self.fixtures["astrid_warm"],
            context_schema=self.schema,
        )
        self.assertEqual(context["familiarity"], 2)
        self.assertEqual(context["trust"], 1)
        self.assertEqual(context["attitude"], "warm")
        self.assertTrue(context["relationship_exists"])

    def test_missing_pair_uses_default_without_creating_record(self) -> None:
        store = copy.deepcopy(self.fixtures["empty"])
        before = copy.deepcopy(store)
        context = build_relationship_context(
            "npc_astrid",
            "player_001",
            store,
            context_schema=self.schema,
        )
        self.assertEqual(context["familiarity"], 1)
        self.assertEqual(context["trust"], 0)
        self.assertEqual(context["attitude"], "neutral")
        self.assertFalse(context["relationship_exists"])
        self.assertEqual(store, before)

    def test_wrong_npc_relationship_is_isolated(self) -> None:
        context = build_relationship_context(
            "npc_bjorn",
            "player_001",
            self.fixtures["astrid_warm"],
            context_schema=self.schema,
        )
        self.assertEqual(context["npc_id"], "npc_bjorn")
        self.assertEqual(context["familiarity"], 0)
        self.assertEqual(context["attitude"], "neutral")
        self.assertFalse(context["relationship_exists"])

    def test_wrong_player_relationship_is_isolated(self) -> None:
        context = build_relationship_context(
            "npc_astrid",
            "player_002",
            self.fixtures["astrid_warm"],
            context_schema=self.schema,
        )
        self.assertEqual(context["player_id"], "player_002")
        self.assertEqual(context["familiarity"], 0)
        self.assertEqual(context["trust"], 0)
        self.assertFalse(context["relationship_exists"])

    def test_injected_store_is_deep_copied_and_read_only(self) -> None:
        store = copy.deepcopy(self.fixtures["astrid_warm"])
        before = copy.deepcopy(store)
        build_relationship_context("npc_astrid", "player_001", store)
        self.assertEqual(store, before)

    def test_invalid_store_is_rejected(self) -> None:
        invalid = {"version": "0.1", "relationships": [{"npc_id": "npc_astrid"}]}
        with self.assertRaisesRegex(
            NpcRelationshipContextError,
            "Relationship Store could not be resolved",
        ):
            build_relationship_context("npc_astrid", "player_001", invalid)


if __name__ == "__main__":
    unittest.main()
