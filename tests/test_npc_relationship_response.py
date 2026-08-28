"""Offline Mock-provider tests for Relationship-aware NPC Response v0.3."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from npc.memory import MEMORY_STORE_PATH
from npc.relationship_store import RELATIONSHIP_STORE_PATH
from npc.response_runtime import load_response_schema
from npc.response_runtime_v0_3 import (
    generate_npc_response_with_relationship,
    load_relationship_response_prompt,
    prepare_relationship_aware_context,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
DATASET_PATH = PROJECT_ROOT / "data" / "npc_relationship_response_test_cases.json"
MEMORY_DATASET_PATH = PROJECT_ROOT / "data" / "npc_memory_retrieval_test_cases.json"
PROTECTED_PATHS = (
    SEED_PATH,
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    MEMORY_STORE_PATH,
    RELATIONSHIP_STORE_PATH,
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "response_runtime_v0_2.py",
    PROJECT_ROOT / "npc" / "relationship_store.py",
    PROJECT_ROOT / "prompts" / "npc_response_system.md",
    PROJECT_ROOT / "prompts" / "npc_response_memory_system_v0.2.md",
    PROJECT_ROOT / "schemas" / "npc_response.schema.json",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MockProvider:
    provider = "mock"
    model = "mock-model"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls = 0
        self.last_request: dict[str, Any] | None = None

    def create_structured_output(self, **request: Any) -> str:
        self.calls += 1
        self.last_request = request
        return json.dumps(self.response, ensure_ascii=False)


class NpcRelationshipResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        cls.world_state["player"]["name"] = "Eirik"
        cls.world_state["player"]["species"] = "human"
        cls.world_state["player"]["occupation"] = "blacksmith apprentice"

        dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        cls.relationship_fixtures = dataset["relationship_fixtures"]
        cls.cases = {case["id"]: case for case in dataset["cases"]}
        memory_dataset = json.loads(MEMORY_DATASET_PATH.read_text(encoding="utf-8"))
        cls.memory_fixtures = {
            item["memory_id"]: item for item in memory_dataset["memory_fixtures"]
        }
        cls.schema = load_response_schema()
        cls.prompt = load_relationship_response_prompt()
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
                "Relationship Response tests changed Persistent State or a Frozen "
                "Baseline: " + ", ".join(str(path) for path in changed)
            )

    def _memory_store_for(self, case: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": "0.1",
            "memories": [
                copy.deepcopy(self.memory_fixtures[memory_id])
                for memory_id in case["memory_fixture_ids"]
            ],
        }

    def _run_case(
        self,
        case_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], MockProvider]:
        case = self.cases[case_id]
        provider = MockProvider(copy.deepcopy(case["mock_response"]))
        result = generate_npc_response_with_relationship(
            case["npc_id"],
            case["player_utterance"],
            copy.deepcopy(self.world_state),
            case["player_id"],
            memory_store_document=self._memory_store_for(case),
            relationship_store_document=copy.deepcopy(
                self.relationship_fixtures[case["relationship_fixture"]]
            ),
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        _, recall, relationship = prepare_relationship_aware_context(
            case["npc_id"],
            case["player_utterance"],
            copy.deepcopy(self.world_state),
            case["player_id"],
            memory_store_document=self._memory_store_for(case),
            relationship_store_document=copy.deepcopy(
                self.relationship_fixtures[case["relationship_fixture"]]
            ),
        )
        self.assertEqual(provider.calls, 1)
        self.assertIsNotNone(provider.last_request)
        self.assertIn('"relationship_context"', provider.last_request["user_message"])
        self.assertIn('"memory_recall_context"', provider.last_request["user_message"])
        expected = case["expected_relationship"]
        for field, value in expected.items():
            self.assertEqual(relationship[field], value)
        return result, recall, provider

    def test_case_1_default_neutral(self) -> None:
        result, _, _ = self._run_case("case_1")
        self.assertNotIn("担心", result["speech"])
        self.assertNotIn("亲爱", result["speech"])

    def test_case_2_warm_relationship(self) -> None:
        result, _, _ = self._run_case("case_2")
        self.assertIn("担心", result["speech"])
        self.assertIn("小心", result["speech"])

    def test_case_3_warm_is_not_romance(self) -> None:
        result, _, _ = self._run_case("case_3")
        self.assertIn("并不表示", result["speech"])
        self.assertIn("恋人", result["speech"])

    def test_case_4_high_trust_is_not_truth(self) -> None:
        result, _, _ = self._run_case("case_4")
        self.assertEqual(result["response_type"], "disagreement")
        self.assertIn("铁匠", result["speech"])
        self.assertIn("不是国王", result["speech"])
        self.assertEqual(result["referenced_knowledge"]["entity_ids"], ["npc_bjorn"])

    def test_case_5_familiarity_does_not_invent_history(self) -> None:
        result, recall, _ = self._run_case("case_5")
        self.assertEqual(recall["retrieved_memories"], [])
        self.assertEqual(result["knowledge_status"], "unknown")
        self.assertIn("没有", result["speech"])
        self.assertIn("不能凭空编造", result["speech"])

    def test_case_6_relationship_and_relevant_memory(self) -> None:
        result, recall, provider = self._run_case("case_6")
        self.assertEqual(len(recall["retrieved_memories"]), 1)
        self.assertIn("你之前告诉我", result["speech"])
        self.assertIn("担心", result["speech"])
        self.assertIn(
            "Eirik intends to go to Stormcliff alone tomorrow",
            provider.last_request["user_message"],
        )

    def test_case_7_wrong_npc_isolation(self) -> None:
        result, _, provider = self._run_case("case_7")
        self.assertEqual(result["npc_id"], "npc_bjorn")
        self.assertIn('"npc_id": "npc_bjorn"', provider.last_request["user_message"])
        self.assertNotIn('"attitude": "warm"', provider.last_request["user_message"])

    def test_case_8_no_persistent_record(self) -> None:
        result, _, provider = self._run_case("case_8")
        self.assertEqual(result["response_type"], "question")
        self.assertIn(
            '"relationship_exists": false',
            provider.last_request["user_message"],
        )

    def test_prompt_contains_relationship_safety_boundaries(self) -> None:
        for phrase in (
            "Relationship does not decide WHAT",
            "Warm is not romance",
            "Trust is not truth",
            "Familiarity is not shared history",
            "relationship_exists=false",
        ):
            self.assertIn(phrase, self.prompt)

    def test_dataset_contains_exactly_eight_golden_cases(self) -> None:
        self.assertEqual(
            set(self.cases),
            {f"case_{index}" for index in range(1, 9)},
        )

    def test_injected_documents_and_world_state_remain_unchanged(self) -> None:
        case = self.cases["case_6"]
        world = copy.deepcopy(self.world_state)
        memory_store = self._memory_store_for(case)
        relationship_store = copy.deepcopy(self.relationship_fixtures["astrid_warm"])
        before = (
            copy.deepcopy(world),
            copy.deepcopy(memory_store),
            copy.deepcopy(relationship_store),
        )
        generate_npc_response_with_relationship(
            case["npc_id"],
            case["player_utterance"],
            world,
            memory_store_document=memory_store,
            relationship_store_document=relationship_store,
            provider_client=MockProvider(copy.deepcopy(case["mock_response"])),  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertEqual((world, memory_store, relationship_store), before)


if __name__ == "__main__":
    unittest.main()
