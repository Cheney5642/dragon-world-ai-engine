"""Offline safety tests for Persistent NPC Relationship Store v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from jsonschema import Draft202012Validator

from npc.relationship_store import (
    RELATIONSHIP_STORE_PATH,
    DuplicateRelationshipEventError,
    NoRelationshipChangeRequiredError,
    RelationshipStoreError,
    StaleRelationshipPreviewError,
    build_persistent_relationship_preview,
    commit_relationship_event,
    confirm_and_commit_relationship,
    initialize_relationship_store,
    load_relationship_store,
    load_relationship_store_schema,
    resolve_current_relationship,
    validate_relationship_store,
    write_relationship_store_atomically,
)
from scripts.commit_npc_relationship import (
    load_relationship_case,
    load_runtime_interaction_event,
)
from scripts.reset_npc_relationships import reset_relationship_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "saves" / "npc_memories.json",
    RELATIONSHIP_STORE_PATH,
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "schemas" / "npc_relationship.schema.json",
    PROJECT_ROOT / "schemas" / "npc_relationship_change.schema.json",
    PROJECT_ROOT / "npc" / "relationship.py",
    PROJECT_ROOT / "npc" / "interaction_event.py",
    PROJECT_ROOT / "npc" / "memory.py",
    PROJECT_ROOT / "npc" / "memory_retriever.py",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "response_runtime_v0_2.py",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcRelationshipPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store_schema = load_relationship_store_schema()
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
                "Relationship Persistence tests changed formal State or a Frozen Baseline: "
                + ", ".join(str(path) for path in changed)
            )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.store_path = temporary_root / "npc_relationships.json"
        self.event_path = temporary_root / "runtime_interaction_event.json"
        initialize_relationship_store(self.store_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def event(self, case_number: int) -> dict[str, Any]:
        return copy.deepcopy(load_relationship_case(case_number)["interaction_event"])

    def seed_relationship(
        self,
        *,
        familiarity: int,
        trust: int,
        attitude: str,
        applied_event_id: str = "npc_event_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ) -> None:
        store = {
            "version": "0.1",
            "relationships": [
                {
                    "npc_id": "npc_astrid",
                    "player_id": "player_001",
                    "familiarity": familiarity,
                    "trust": trust,
                    "attitude": attitude,
                    "applied_event_ids": [applied_event_id],
                    "last_source_event_id": applied_event_id,
                }
            ],
        }
        write_relationship_store_atomically(store, self.store_path)

    def test_store_schema_and_empty_store_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.store_schema)
        store = load_relationship_store(self.store_path)
        validate_relationship_store(store, self.store_schema)
        self.assertEqual(store, {"version": "0.1", "relationships": []})

    def test_persistence_golden_dataset_has_eight_cases_and_reuses_c1_events(self) -> None:
        resolved = [load_relationship_case(index) for index in range(1, 9)]
        self.assertEqual(
            [case["id"] for case in resolved],
            [f"case_{index}" for index in range(1, 9)],
        )
        self.assertEqual(
            resolved[4]["interaction_event"]["event_id"],
            resolved[3]["interaction_event"]["event_id"],
        )

    def test_store_rejects_duplicate_npc_player_pair(self) -> None:
        record = {
            "npc_id": "npc_astrid",
            "player_id": "player_001",
            "familiarity": 1,
            "trust": 0,
            "attitude": "neutral",
            "applied_event_ids": ["npc_event_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
            "last_source_event_id": "npc_event_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }
        with self.assertRaisesRegex(RelationshipStoreError, "Duplicate NPC/Player"):
            validate_relationship_store(
                {"version": "0.1", "relationships": [record, copy.deepcopy(record)]}
            )

    def test_default_relationship_is_resolved_but_not_persisted(self) -> None:
        before = self.store_path.read_bytes()
        store = load_relationship_store(self.store_path)
        relationship, persisted = resolve_current_relationship(
            store,
            "npc_astrid",
            "player_001",
        )
        self.assertFalse(persisted)
        self.assertEqual(relationship["familiarity"], 1)
        self.assertEqual(relationship["trust"], 0)
        self.assertEqual(relationship["attitude"], "neutral")
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_case_1_greeting_no_change_never_writes_or_prompts(self) -> None:
        event = self.event(1)
        before = self.store_path.read_bytes()
        preview = build_persistent_relationship_preview(event, self.store_path)
        self.assertEqual(preview["decision"], "no_change")

        def unexpected_prompt(_: str) -> str:
            raise AssertionError("no_change must not ask for confirmation")

        with self.assertRaisesRegex(
            NoRelationshipChangeRequiredError,
            "No persistent relationship change required",
        ):
            confirm_and_commit_relationship(
                event,
                preview,
                self.store_path,
                input_fn=unexpected_prompt,
            )
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_cases_2_3_and_7_are_no_change_and_read_only(self) -> None:
        for case_number in (2, 3, 7):
            with self.subTest(case=case_number):
                before = self.store_path.read_bytes()
                preview = build_persistent_relationship_preview(
                    self.event(case_number),
                    self.store_path,
                )
                self.assertEqual(preview["decision"], "no_change")
                self.assertEqual(self.store_path.read_bytes(), before)

    def test_case_4_preview_is_read_only_and_cancel_keeps_store_unchanged(self) -> None:
        event = self.event(4)
        before = self.store_path.read_bytes()
        preview = build_persistent_relationship_preview(event, self.store_path)
        self.assertEqual(preview["decision"], "change_proposed")
        self.assertEqual(self.store_path.read_bytes(), before)
        result = confirm_and_commit_relationship(
            event,
            preview,
            self.store_path,
            input_fn=lambda _prompt: "no",
        )
        self.assertIsNone(result)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_case_4_confirm_persists_small_positive_change(self) -> None:
        event = self.event(4)
        preview = build_persistent_relationship_preview(event, self.store_path)
        result = confirm_and_commit_relationship(
            event,
            preview,
            self.store_path,
            input_fn=lambda _prompt: "yes",
        )
        self.assertIsNotNone(result)
        record, committed_preview = result  # type: ignore[misc]
        self.assertEqual(committed_preview["decision"], "change_proposed")
        self.assertEqual(record["familiarity"], 2)
        self.assertEqual(record["trust"], 1)
        self.assertEqual(record["attitude"], "warm")
        self.assertEqual(record["applied_event_ids"], [event["event_id"]])
        self.assertEqual(record["last_source_event_id"], event["event_id"])

    def test_case_5_duplicate_event_is_idempotently_rejected(self) -> None:
        event = self.event(4)
        preview = build_persistent_relationship_preview(event, self.store_path)
        commit_relationship_event(event, preview, self.store_path)
        store_before_duplicate = self.store_path.read_bytes()
        with self.assertRaisesRegex(
            DuplicateRelationshipEventError,
            "already applied",
        ):
            build_persistent_relationship_preview(event, self.store_path)
        record = load_relationship_store(self.store_path)["relationships"][0]
        self.assertEqual(record["trust"], 1)
        self.assertEqual(len(record["applied_event_ids"]), 1)
        self.assertEqual(self.store_path.read_bytes(), store_before_duplicate)

    def test_case_6_confirm_persists_small_negative_change(self) -> None:
        event = self.event(6)
        preview = build_persistent_relationship_preview(event, self.store_path)
        record, _ = commit_relationship_event(event, preview, self.store_path)
        self.assertEqual(record["familiarity"], 1)
        self.assertEqual(record["trust"], -1)
        self.assertEqual(record["attitude"], "wary")

    def test_case_8_bounds_produce_no_write_at_maximum(self) -> None:
        self.seed_relationship(familiarity=3, trust=2, attitude="warm")
        before = self.store_path.read_bytes()
        preview = build_persistent_relationship_preview(
            self.event(8),
            self.store_path,
        )
        self.assertEqual(preview["decision"], "no_change")
        self.assertEqual(preview["proposed_relationship"]["trust"], 2)
        self.assertEqual(preview["proposed_relationship"]["familiarity"], 3)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_negative_commit_cannot_cross_minimum_trust(self) -> None:
        self.seed_relationship(familiarity=1, trust=-2, attitude="hostile")
        before = self.store_path.read_bytes()
        preview = build_persistent_relationship_preview(
            self.event(6),
            self.store_path,
        )
        self.assertEqual(preview["decision"], "no_change")
        self.assertEqual(preview["proposed_relationship"]["trust"], -2)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_stale_or_client_modified_preview_is_rejected(self) -> None:
        event = self.event(4)
        preview = build_persistent_relationship_preview(event, self.store_path)
        preview["proposed_relationship"]["trust"] = 2
        preview["changes"]["trust"]["after"] = 2
        preview["changes"]["trust"]["delta"] = 2
        before = self.store_path.read_bytes()
        with self.assertRaisesRegex(StaleRelationshipPreviewError, "stale"):
            commit_relationship_event(event, preview, self.store_path)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_atomic_replace_failure_preserves_original_store(self) -> None:
        event = self.event(4)
        preview = build_persistent_relationship_preview(event, self.store_path)
        before = self.store_path.read_bytes()
        with patch(
            "npc.relationship_store.os.replace",
            side_effect=OSError("simulated replace failure"),
        ):
            with self.assertRaisesRegex(RelationshipStoreError, "safely write"):
                commit_relationship_event(event, preview, self.store_path)
        self.assertEqual(self.store_path.read_bytes(), before)
        self.assertEqual(load_relationship_store(self.store_path)["relationships"], [])

    def test_runtime_event_file_uses_frozen_interaction_contract(self) -> None:
        event = self.event(4)
        self.event_path.write_text(
            json.dumps(event, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        loaded = load_runtime_interaction_event(self.event_path)
        self.assertEqual(loaded, event)
        preview = build_persistent_relationship_preview(loaded, self.store_path)
        self.assertEqual(preview["decision"], "change_proposed")

    def test_reset_requires_confirmation_and_only_resets_temporary_store(self) -> None:
        event = self.event(4)
        preview = build_persistent_relationship_preview(event, self.store_path)
        commit_relationship_event(event, preview, self.store_path)
        before_refusal = self.store_path.read_bytes()
        with self.assertRaisesRegex(RelationshipStoreError, "requires --confirm"):
            reset_relationship_store(self.store_path, confirmed=False)
        self.assertEqual(self.store_path.read_bytes(), before_refusal)
        reset_store = reset_relationship_store(self.store_path, confirmed=True)
        self.assertEqual(reset_store, {"version": "0.1", "relationships": []})

    def test_only_temporary_relationship_store_changes(self) -> None:
        formal_before = file_hash(RELATIONSHIP_STORE_PATH)
        event = self.event(4)
        preview = build_persistent_relationship_preview(event, self.store_path)
        commit_relationship_event(event, preview, self.store_path)
        self.assertEqual(file_hash(RELATIONSHIP_STORE_PATH), formal_before)
        self.assertEqual(len(load_relationship_store(self.store_path)["relationships"]), 1)


if __name__ == "__main__":
    unittest.main()
