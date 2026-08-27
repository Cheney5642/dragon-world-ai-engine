"""Offline tests for deterministic, read-only NPC Memory Retrieval v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from npc.memory import MEMORY_STORE_PATH
from npc.memory_retriever import (
    NpcMemoryRetrievalError,
    load_memory_recall_schema,
    retrieve_relevant_memories,
    validate_memory_recall_context,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "data" / "npc_memory_retrieval_test_cases.json"
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    MEMORY_STORE_PATH,
    PROJECT_ROOT / "prompts" / "npc_response_system.md",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "context_builder.py",
    PROJECT_ROOT / "npc" / "memory.py",
)
CURRENT_WORLD_CONTEXT = {
    "world_day": 2,
    "world_hour": 13,
    "location_id": "skeld_village",
}


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset() -> dict[str, Any]:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AssertionError("Memory Retrieval dataset must be an object")
    return document


class NpcMemoryRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_dataset()
        cls.fixtures = {
            memory["memory_id"]: memory
            for memory in cls.dataset["memory_fixtures"]
        }
        cls.cases = {case["id"]: case for case in cls.dataset["cases"]}
        cls.recall_schema = load_memory_recall_schema()
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
                "Retrieval tests changed Persistent State or a Frozen Baseline: "
                + ", ".join(str(path) for path in changed)
            )

    def run_case(self, case_number: int) -> dict[str, Any]:
        case = self.cases[f"case_{case_number}"]
        store = {
            "version": "0.1",
            "memories": [
                copy.deepcopy(self.fixtures[memory_id])
                for memory_id in case["fixture_ids"]
            ],
        }
        store_before = copy.deepcopy(store)
        context_before = copy.deepcopy(CURRENT_WORLD_CONTEXT)
        recall = retrieve_relevant_memories(
            case["npc_id"],
            case["player_id"],
            case["player_utterance"],
            copy.deepcopy(CURRENT_WORLD_CONTEXT),
            store_document=store,
            recall_schema=self.recall_schema,
        )
        self.assertEqual(store, store_before)
        self.assertEqual(CURRENT_WORLD_CONTEXT, context_before)
        validate_memory_recall_context(recall, self.recall_schema)
        return recall

    def test_case_1_direct_recall_ranks_leaving_skeld_first(self) -> None:
        recall = self.run_case(1)
        self.assertEqual(
            recall["retrieved_memories"][0]["memory_id"],
            self.cases["case_1"]["expected_top_memory_id"],
        )

    def test_case_2_specific_recent_plan_ranks_stormcliff_first(self) -> None:
        recall = self.run_case(2)
        self.assertEqual(
            recall["retrieved_memories"][0]["memory_id"],
            self.cases["case_2"]["expected_top_memory_id"],
        )

    def test_case_3_irrelevant_memory_is_not_retrieved(self) -> None:
        self.assertEqual(self.run_case(3)["retrieved_memories"], [])

    def test_case_4_wrong_npc_memory_is_isolated(self) -> None:
        self.assertEqual(self.run_case(4)["retrieved_memories"], [])

    def test_case_5_wrong_player_memory_is_isolated(self) -> None:
        self.assertEqual(self.run_case(5)["retrieved_memories"], [])

    def test_case_6_false_claim_remains_attributed_subjective_recall(self) -> None:
        recalled = self.run_case(6)["retrieved_memories"][0]
        self.assertEqual(
            recalled["memory_id"],
            self.cases["case_6"]["expected_top_memory_id"],
        )
        self.assertEqual(recalled["memory_type"], "player_claim")
        self.assertEqual(recalled["epistemic_status"], "reported_by_player")
        self.assertIn("claims", recalled["content"])

    def test_case_7_intention_is_retrieved_without_becoming_completion(self) -> None:
        recalled = self.run_case(7)["retrieved_memories"][0]
        self.assertEqual(
            recalled["memory_id"],
            self.cases["case_7"]["expected_top_memory_id"],
        )
        self.assertEqual(recalled["memory_type"], "player_intention")
        self.assertIn("intends", recalled["content"])

    def test_case_8_empty_store_returns_empty_recall(self) -> None:
        self.assertEqual(self.run_case(8)["retrieved_memories"], [])

    def test_top_k_is_capped_at_three_and_is_deterministic(self) -> None:
        template = self.fixtures["npc_memory_22222222222222222222222222222222"]
        memories = []
        for index in range(1, 6):
            memory = copy.deepcopy(template)
            digit = format(index + 5, "x")
            memory["memory_id"] = "npc_memory_" + digit * 32
            memory["source_event_id"] = "npc_event_" + digit * 32
            memory["world_context"]["world_hour"] = 8 + index
            memories.append(memory)
        store = {"version": "0.1", "memories": memories}
        first = retrieve_relevant_memories(
            "npc_astrid",
            "player_001",
            "我准备去 Stormcliff。",
            CURRENT_WORLD_CONTEXT,
            store_document=store,
        )
        second = retrieve_relevant_memories(
            "npc_astrid",
            "player_001",
            "我准备去 Stormcliff。",
            CURRENT_WORLD_CONTEXT,
            store_document=store,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first["retrieved_memories"]), 3)

    def test_limit_outside_one_to_three_is_rejected(self) -> None:
        for invalid_limit in (0, 4):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(NpcMemoryRetrievalError, "1 to 3"):
                    retrieve_relevant_memories(
                        "npc_astrid",
                        "player_001",
                        "记得吗？",
                        CURRENT_WORLD_CONTEXT,
                        invalid_limit,
                        store_document={"version": "0.1", "memories": []},
                    )

    def test_dataset_contains_exactly_eight_golden_cases(self) -> None:
        self.assertEqual(
            [case["id"] for case in self.dataset["cases"]],
            [f"case_{index}" for index in range(1, 9)],
        )


if __name__ == "__main__":
    unittest.main()
