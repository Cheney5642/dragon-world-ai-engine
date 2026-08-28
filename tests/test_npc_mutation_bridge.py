"""Offline tests for Unified NPC Mutation Bridge v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from npc.memory import (
    MEMORY_STORE_PATH,
    DuplicateMemoryError,
    load_memory_store,
    write_memory_store_atomically,
)
from npc.mutation_bridge import (
    MutationUnavailableError,
    NpcMutationBridgeError,
    commit_npc_mutation_plan,
    load_npc_mutation_plan_schema,
    prepare_npc_mutation_plan,
    validate_npc_mutation_plan,
)
from npc.relationship_store import (
    RELATIONSHIP_STORE_PATH,
    DuplicateRelationshipEventError,
    load_relationship_store,
    write_relationship_store_atomically,
)
from scripts.run_npc_mutation_bridge import (
    load_bridge_case,
    resolve_case_event,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    MEMORY_STORE_PATH,
    RELATIONSHIP_STORE_PATH,
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "npc" / "interaction_runtime.py",
    PROJECT_ROOT / "npc" / "interaction_event.py",
    PROJECT_ROOT / "npc" / "memory.py",
    PROJECT_ROOT / "npc" / "relationship.py",
    PROJECT_ROOT / "npc" / "relationship_store.py",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcMutationBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan_schema = load_npc_mutation_plan_schema()
        cls.cases = {
            f"case_{index}": load_bridge_case(index)
            for index in range(1, 9)
        }
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
                "Mutation Bridge tests changed formal Persistent State or a Frozen "
                "Baseline: " + ", ".join(str(path) for path in changed)
            )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.memory_store_path = root / "npc_memories.json"
        self.relationship_store_path = root / "npc_relationships.json"
        write_memory_store_atomically(
            {"version": "0.1", "memories": []},
            self.memory_store_path,
        )
        write_relationship_store_atomically(
            {"version": "0.1", "relationships": []},
            self.relationship_store_path,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def event_for(self, case_number: int) -> dict:
        return resolve_case_event(self.cases[f"case_{case_number}"])

    def prepare(self, case_number: int) -> tuple[dict, dict]:
        event = self.event_for(case_number)
        plan = prepare_npc_mutation_plan(
            event,
            relationship_store_path=self.relationship_store_path,
            plan_schema=self.plan_schema,
        )
        validate_npc_mutation_plan(plan, event, self.plan_schema)
        return event, plan

    def store_hashes(self) -> tuple[str | None, str | None]:
        return (
            file_hash(self.memory_store_path),
            file_hash(self.relationship_store_path),
        )

    def test_case_1_no_candidate_has_no_commit_and_no_write(self) -> None:
        before = self.store_hashes()
        event, plan = self.prepare(1)
        self.assertFalse(plan["memory"]["candidate"])
        self.assertIsNone(plan["memory"]["preview"])
        self.assertFalse(plan["relationship"]["commit_available"])
        self.assertFalse(plan["has_any_mutation"])
        result = commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=False,
            commit_relationship=False,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertFalse(result["memory"]["committed"])
        self.assertEqual(self.store_hashes(), before)

    def test_case_2_memory_preview_preserves_player_intention_boundary(self) -> None:
        _, plan = self.prepare(2)
        memory = plan["memory"]["preview"]
        self.assertTrue(plan["memory"]["commit_available"])
        self.assertEqual(memory["memory_type"], "player_intention")
        self.assertEqual(memory["epistemic_status"], "reported_by_player")
        self.assertIn("intends to go to Stormcliff alone tomorrow", memory["content"])
        self.assertIsNone(plan["relationship"]["preview"])

    def test_memory_cancel_is_read_only(self) -> None:
        before = self.store_hashes()
        event, plan = self.prepare(2)
        commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=False,
            commit_relationship=False,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertEqual(self.store_hashes(), before)

    def test_memory_confirm_commits_only_memory_store(self) -> None:
        before_relationship = file_hash(self.relationship_store_path)
        event, plan = self.prepare(2)
        result = commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=True,
            commit_relationship=False,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertTrue(result["memory"]["committed"])
        self.assertEqual(len(load_memory_store(self.memory_store_path)["memories"]), 1)
        self.assertEqual(file_hash(self.relationship_store_path), before_relationship)

    def test_case_3_duplicate_memory_reuses_frozen_idempotency(self) -> None:
        event, plan = self.prepare(3)
        kwargs = {
            "commit_memory": True,
            "commit_relationship": False,
            "memory_store_path": self.memory_store_path,
            "relationship_store_path": self.relationship_store_path,
        }
        commit_npc_mutation_plan(event, plan, **kwargs)
        with self.assertRaisesRegex(
            DuplicateMemoryError,
            "already exists",
        ):
            commit_npc_mutation_plan(event, plan, **kwargs)
        self.assertEqual(len(load_memory_store(self.memory_store_path)["memories"]), 1)

    def test_case_4_relationship_preview_uses_frozen_evaluator(self) -> None:
        _, plan = self.prepare(4)
        preview = plan["relationship"]["preview"]
        self.assertEqual(preview["decision"], "change_proposed")
        self.assertEqual(preview["proposed_relationship"]["familiarity"], 2)
        self.assertEqual(preview["proposed_relationship"]["trust"], 1)
        self.assertEqual(preview["proposed_relationship"]["attitude"], "warm")
        self.assertTrue(plan["relationship"]["commit_available"])

    def test_relationship_cancel_is_read_only(self) -> None:
        before = self.store_hashes()
        event, plan = self.prepare(4)
        commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=False,
            commit_relationship=False,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertEqual(self.store_hashes(), before)

    def test_relationship_confirm_commits_only_relationship_store(self) -> None:
        before_memory = file_hash(self.memory_store_path)
        event, plan = self.prepare(4)
        result = commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=False,
            commit_relationship=True,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertTrue(result["relationship"]["committed"])
        records = load_relationship_store(self.relationship_store_path)["relationships"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["trust"], 1)
        self.assertEqual(file_hash(self.memory_store_path), before_memory)

    def test_case_5_duplicate_relationship_reuses_frozen_idempotency(self) -> None:
        event, plan = self.prepare(5)
        kwargs = {
            "commit_memory": False,
            "commit_relationship": True,
            "memory_store_path": self.memory_store_path,
            "relationship_store_path": self.relationship_store_path,
        }
        commit_npc_mutation_plan(event, plan, **kwargs)
        with self.assertRaisesRegex(
            DuplicateRelationshipEventError,
            "already applied",
        ):
            commit_npc_mutation_plan(event, plan, **kwargs)
        record = load_relationship_store(self.relationship_store_path)["relationships"][0]
        self.assertEqual(record["trust"], 1)

    def test_case_6_unsupported_claim_cannot_raise_relationship(self) -> None:
        _, plan = self.prepare(6)
        memory = plan["memory"]["preview"]
        relationship = plan["relationship"]["preview"]
        self.assertEqual(memory["memory_type"], "player_claim")
        self.assertEqual(memory["epistemic_status"], "reported_by_player")
        self.assertIn("claims that he saved", memory["content"])
        self.assertEqual(relationship["decision"], "no_change")
        self.assertFalse(plan["relationship"]["commit_available"])
        self.assertEqual(
            relationship["proposed_relationship"],
            relationship["current_relationship"],
        )

    def test_case_7_both_candidates_can_be_confirmed_independently(self) -> None:
        event, plan = self.prepare(7)
        self.assertTrue(plan["memory"]["commit_available"])
        self.assertTrue(plan["relationship"]["commit_available"])

        memory_result = commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=True,
            commit_relationship=False,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertTrue(memory_result["memory"]["committed"])
        self.assertFalse(memory_result["relationship"]["committed"])

        relationship_result = commit_npc_mutation_plan(
            event,
            plan,
            commit_memory=False,
            commit_relationship=True,
            memory_store_path=self.memory_store_path,
            relationship_store_path=self.relationship_store_path,
        )
        self.assertTrue(relationship_result["relationship"]["committed"])
        self.assertEqual(len(load_memory_store(self.memory_store_path)["memories"]), 1)
        self.assertEqual(
            len(load_relationship_store(self.relationship_store_path)["relationships"]),
            1,
        )
        self.assertFalse(relationship_result["cross_store_transaction"])

    def test_case_8_preview_without_confirmation_changes_no_store(self) -> None:
        before = self.store_hashes()
        _, plan = self.prepare(8)
        self.assertFalse(plan["has_any_mutation"])
        self.assertEqual(self.store_hashes(), before)

    def test_unavailable_domain_cannot_be_forced_to_commit(self) -> None:
        event, plan = self.prepare(1)
        with self.assertRaisesRegex(MutationUnavailableError, "No Memory mutation"):
            commit_npc_mutation_plan(
                event,
                plan,
                commit_memory=True,
                commit_relationship=False,
                memory_store_path=self.memory_store_path,
                relationship_store_path=self.relationship_store_path,
            )

    def test_plan_schema_and_event_derived_fields_are_enforced(self) -> None:
        event, plan = self.prepare(7)
        tampered = copy.deepcopy(plan)
        tampered["relationship"]["signal"] = "none"
        with self.assertRaises(NpcMutationBridgeError):
            validate_npc_mutation_plan(tampered, event, self.plan_schema)

    def test_preview_does_not_mutate_event_or_injected_store(self) -> None:
        event = self.event_for(7)
        relationship_store = load_relationship_store(self.relationship_store_path)
        before = (copy.deepcopy(event), copy.deepcopy(relationship_store))
        prepare_npc_mutation_plan(
            event,
            relationship_store_document=relationship_store,
            plan_schema=self.plan_schema,
        )
        self.assertEqual((event, relationship_store), before)

    def test_bridge_has_zero_llm_calls(self) -> None:
        event = self.event_for(7)
        with patch(
            "llm.create_llm_client",
            side_effect=AssertionError("Mutation Bridge must not create an LLM client"),
        ):
            prepare_npc_mutation_plan(
                event,
                relationship_store_path=self.relationship_store_path,
                plan_schema=self.plan_schema,
            )

    def test_dataset_contains_exactly_eight_reference_only_cases(self) -> None:
        self.assertEqual(
            set(self.cases),
            {f"case_{index}" for index in range(1, 9)},
        )
        for case in self.cases.values():
            self.assertIn("event_fixture", case)
            self.assertNotIn("interaction_event", case)


if __name__ == "__main__":
    unittest.main()
