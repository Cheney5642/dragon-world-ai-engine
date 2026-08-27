"""Offline safety tests for Persistent NPC Memory v0.1."""

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

from npc.memory import (
    DuplicateMemoryError,
    MemoryStoreError,
    NoPersistentMemoryRequiredError,
    build_memory_preview,
    commit_memory_preview,
    confirm_and_commit_memory,
    initialize_memory_store,
    load_memory_schema,
    load_memory_store,
    load_memory_store_schema,
    validate_memory_record,
    validate_memory_store,
)
from scripts.commit_npc_memory import (
    build_case_interaction_event,
    load_memory_case,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
FROZEN_PATHS = (
    PROJECT_ROOT / "prompts" / "npc_response_system.md",
    PROJECT_ROOT / "schemas" / "npc_profile.schema.json",
    PROJECT_ROOT / "schemas" / "npc_context.schema.json",
    PROJECT_ROOT / "schemas" / "npc_response.schema.json",
    PROJECT_ROOT / "schemas" / "npc_interaction_event.schema.json",
    PROJECT_ROOT / "npc" / "context_builder.py",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "interaction_event.py",
)
PROTECTED_PATHS = (SEED_PATH, SAVE_PATH, PROFILES_PATH, *FROZEN_PATHS)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.memory_schema = load_memory_schema()
        cls.store_schema = load_memory_store_schema()
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
                "Protected state or Frozen Baseline changed during NPC Memory tests: "
                + ", ".join(str(path) for path in changed)
            )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temporary_directory.name) / "npc_memories.json"
        initialize_memory_store(self.store_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def build_case_preview(
        self,
        case_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        memory_case = load_memory_case(case_number)
        event = build_case_interaction_event(memory_case)
        event_before = copy.deepcopy(event)
        memory = build_memory_preview(event)
        self.assertEqual(event, event_before)
        validate_memory_record(memory, self.memory_schema)
        return memory_case, event, memory

    def test_case_1_non_candidate_produces_no_memory(self) -> None:
        memory_case = load_memory_case(1)
        event = build_case_interaction_event(memory_case)
        before = self.store_path.read_bytes()
        with self.assertRaisesRegex(
            NoPersistentMemoryRequiredError,
            "No persistent memory required",
        ):
            build_memory_preview(event)
        self.assertEqual(self.store_path.read_bytes(), before)
        self.assertEqual(load_memory_store(self.store_path)["memories"], [])

    def test_case_2_preview_is_reported_player_intention_and_read_only(self) -> None:
        case, _, memory = self.build_case_preview(2)
        before = self.store_path.read_bytes()
        self.assertEqual(memory["memory_type"], case["expected"]["memory_type"])
        self.assertIn(case["expected"]["content_contains"], memory["content"])
        self.assertEqual(
            memory["epistemic_status"],
            case["expected"]["epistemic_status"],
        )
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_case_3_cancel_keeps_store_unchanged(self) -> None:
        _, _, memory = self.build_case_preview(3)
        before = self.store_path.read_bytes()
        result = confirm_and_commit_memory(
            memory,
            self.store_path,
            input_fn=lambda _prompt: "no",
        )
        self.assertIsNone(result)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_case_4_confirm_commits_memory_with_provenance(self) -> None:
        case, event, memory = self.build_case_preview(4)
        committed = confirm_and_commit_memory(
            memory,
            self.store_path,
            input_fn=lambda _prompt: "yes",
        )
        store = load_memory_store(self.store_path)
        self.assertEqual(committed, memory)
        self.assertEqual(len(store["memories"]), case["expected"]["memory_count"])
        saved = store["memories"][0]
        self.assertEqual(saved["source_event_id"], event["event_id"])
        self.assertEqual(saved["npc_id"], case["expected"]["npc_id"])
        self.assertEqual(saved["player_id"], case["expected"]["player_id"])

    def test_case_5_duplicate_source_event_is_rejected(self) -> None:
        case, event, first_memory = self.build_case_preview(5)
        commit_memory_preview(first_memory, self.store_path)
        second_memory = build_memory_preview(copy.deepcopy(event))
        before_second_attempt = self.store_path.read_bytes()

        def unexpected_prompt(_: str) -> str:
            raise AssertionError("duplicate Memory must be rejected before prompting")

        with self.assertRaisesRegex(
            DuplicateMemoryError,
            "already exists",
        ):
            confirm_and_commit_memory(
                second_memory,
                self.store_path,
                input_fn=unexpected_prompt,
            )
        store = load_memory_store(self.store_path)
        self.assertEqual(len(store["memories"]), case["expected"]["memory_count"])
        self.assertEqual(self.store_path.read_bytes(), before_second_attempt)

    def test_case_6_future_plan_never_becomes_executed_fact(self) -> None:
        case, _, memory = self.build_case_preview(6)
        self.assertEqual(memory["memory_type"], "player_intention")
        self.assertIn(case["expected"]["content_contains"], memory["content"])
        self.assertNotIn(
            case["expected"]["content_must_not_contain"],
            memory["content"],
        )
        self.assertEqual(memory["epistemic_status"], "reported_by_player")

    def test_case_7_player_claim_memory_is_not_world_truth(self) -> None:
        case, _, memory = self.build_case_preview(7)
        self.assertEqual(memory["memory_type"], "player_claim")
        self.assertIn(case["expected"]["content_contains"], memory["content"])
        self.assertNotEqual(
            memory["content"],
            case["expected"]["content_must_not_equal"],
        )
        self.assertEqual(memory["epistemic_status"], "reported_by_player")
        serialized = json.dumps(memory).casefold()
        self.assertNotIn("verified_world_fact", serialized)
        self.assertNotIn("knowledge_update", serialized)
        self.assertNotIn("world_mutation", serialized)

    def test_case_8_only_temporary_memory_store_changes(self) -> None:
        protected_before = {path: file_hash(path) for path in PROTECTED_PATHS}
        _, _, memory = self.build_case_preview(8)
        store_before = file_hash(self.store_path)
        commit_memory_preview(memory, self.store_path)
        self.assertNotEqual(file_hash(self.store_path), store_before)
        self.assertEqual(
            {path: file_hash(path) for path in PROTECTED_PATHS},
            protected_before,
        )

    def test_memory_and_store_schemas_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.memory_schema)
        Draft202012Validator.check_schema(self.store_schema)
        validate_memory_store(
            load_memory_store(self.store_path),
            store_schema=self.store_schema,
            memory_schema=self.memory_schema,
        )

    def test_memory_ids_are_unique_and_not_array_indexes(self) -> None:
        _, event, first = self.build_case_preview(2)
        second = build_memory_preview(copy.deepcopy(event))
        self.assertNotEqual(first["memory_id"], second["memory_id"])
        self.assertRegex(first["memory_id"], r"^npc_memory_[0-9a-f]{32}$")
        self.assertRegex(second["memory_id"], r"^npc_memory_[0-9a-f]{32}$")

    def test_atomic_write_failure_preserves_original_store(self) -> None:
        _, _, memory = self.build_case_preview(2)
        before = self.store_path.read_bytes()
        with patch("npc.memory.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaisesRegex(MemoryStoreError, "safely write"):
                commit_memory_preview(memory, self.store_path)
        self.assertEqual(self.store_path.read_bytes(), before)
        self.assertEqual(list(self.store_path.parent.glob("*.tmp")), [])

    def test_store_rejects_duplicate_provenance_even_with_new_memory_id(self) -> None:
        _, event, first = self.build_case_preview(2)
        second = build_memory_preview(copy.deepcopy(event))
        invalid_store = {"version": "0.1", "memories": [first, second]}
        with self.assertRaisesRegex(MemoryStoreError, "Duplicate NPC/source event"):
            validate_memory_store(invalid_store)


if __name__ == "__main__":
    unittest.main()
