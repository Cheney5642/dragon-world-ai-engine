"""Offline tests for Unified NPC Interaction Runtime v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from npc.interaction_runtime import (
    NpcInteractionRuntimeError,
    load_interaction_runtime_result_schema,
    run_npc_interaction,
    validate_interaction_runtime_result,
)
from npc.memory import MEMORY_STORE_PATH
from npc.relationship_store import RELATIONSHIP_STORE_PATH
from npc.response_runtime import load_response_schema
from npc.response_runtime_v0_3 import load_relationship_response_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
CASES_PATH = PROJECT_ROOT / "data" / "npc_interaction_runtime_test_cases.json"
MEMORY_CASES_PATH = PROJECT_ROOT / "data" / "npc_memory_retrieval_test_cases.json"
RELATIONSHIP_CASES_PATH = (
    PROJECT_ROOT / "data" / "npc_relationship_response_test_cases.json"
)
PROTECTED_PATHS = (
    SEED_PATH,
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    MEMORY_STORE_PATH,
    RELATIONSHIP_STORE_PATH,
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "npc" / "context_builder.py",
    PROJECT_ROOT / "npc" / "memory_retriever.py",
    PROJECT_ROOT / "npc" / "relationship_context.py",
    PROJECT_ROOT / "npc" / "response_runtime_v0_3.py",
    PROJECT_ROOT / "npc" / "interaction_event.py",
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


class NpcInteractionRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        cls.world_state["player"]["name"] = "Eirik"
        cls.world_state["player"]["species"] = "human"
        cls.world_state["player"]["occupation"] = "blacksmith apprentice"

        runtime_dataset = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case for case in runtime_dataset["cases"]}
        memory_dataset = json.loads(MEMORY_CASES_PATH.read_text(encoding="utf-8"))
        cls.memory_fixtures = {
            item["memory_id"]: item for item in memory_dataset["memory_fixtures"]
        }
        relationship_dataset = json.loads(
            RELATIONSHIP_CASES_PATH.read_text(encoding="utf-8")
        )
        cls.relationship_fixtures = relationship_dataset["relationship_fixtures"]
        cls.result_schema = load_interaction_runtime_result_schema()
        cls.response_schema = load_response_schema()
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
                "Unified NPC Runtime tests changed Persistent State or a Frozen "
                "Baseline: " + ", ".join(str(path) for path in changed)
            )

    def _memory_store(self, case: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": "0.1",
            "memories": [
                copy.deepcopy(self.memory_fixtures[memory_id])
                for memory_id in case["memory_fixture_ids"]
            ],
        }

    def _world_state(self, case: dict[str, Any]) -> dict[str, Any]:
        world_state = copy.deepcopy(self.world_state)
        override = case.get("world_override", {})
        if "player_current_location" in override:
            world_state["player"]["current_location"] = override[
                "player_current_location"
            ]
        return world_state

    def _run_case(
        self,
        case_id: str,
    ) -> tuple[dict[str, Any], MockProvider, dict[str, Any], dict[str, Any], dict[str, Any]]:
        case = self.cases[case_id]
        world_state = self._world_state(case)
        memory_store = self._memory_store(case)
        relationship_store = copy.deepcopy(
            self.relationship_fixtures[case["relationship_fixture"]]
        )
        provider = MockProvider(copy.deepcopy(case["mock_response"]))
        result = run_npc_interaction(
            case["npc_id"],
            case["player_id"],
            case["player_utterance"],
            world_state,
            memory_store_document=memory_store,
            relationship_store_document=relationship_store,
            provider_client=provider,
            system_prompt=self.prompt,
            response_schema=self.response_schema,
            result_schema=self.result_schema,
        )
        validate_interaction_runtime_result(result, self.result_schema)
        expected_calls = 1 if result["interaction_available"] else 0
        self.assertEqual(provider.calls, expected_calls)
        return result, provider, world_state, memory_store, relationship_store

    def _assert_expected_event(self, case_id: str, result: dict[str, Any]) -> None:
        expected = self.cases[case_id]["expected"]
        self.assertEqual(result["interaction_available"], expected["interaction_available"])
        self.assertEqual(result["memory_candidate"], expected["memory_candidate"])
        self.assertEqual(result["relationship_signal"], expected["relationship_signal"])
        if not expected["interaction_available"]:
            return
        event = result["interaction_event"]
        self.assertEqual(event["topic"], expected["topic"])
        self.assertEqual(len(event["player_claims"]), expected["player_claims_count"])
        if "claim_contains" in expected:
            self.assertTrue(
                any(expected["claim_contains"] in claim for claim in event["player_claims"])
            )
        self.assertEqual(
            len(result["memory_recall_context"]["retrieved_memories"]),
            expected["retrieved_memory_count"],
        )

    def test_case_1_ordinary_knowledge_question(self) -> None:
        result, provider, *_ = self._run_case("case_1")
        self._assert_expected_event("case_1", result)
        self.assertIn("铁匠", result["npc_response"]["speech"])
        self.assertEqual(provider.calls, 1)

    def test_case_2_memory_recall(self) -> None:
        result, provider, *_ = self._run_case("case_2")
        self._assert_expected_event("case_2", result)
        self.assertIn("你之前告诉我", result["npc_response"]["speech"])
        self.assertIn(
            "Eirik intends to go to Stormcliff alone tomorrow",
            provider.last_request["user_message"],
        )

    def test_case_3_relationship_aware_response(self) -> None:
        result, provider, *_ = self._run_case("case_3")
        self._assert_expected_event("case_3", result)
        expected = self.cases["case_3"]["expected"]["relationship"]
        for field, value in expected.items():
            self.assertEqual(result["relationship_context"][field], value)
        self.assertIn('"attitude": "warm"', provider.last_request["user_message"])

    def test_case_4_false_claim_remains_a_claim(self) -> None:
        result, *_ = self._run_case("case_4")
        self._assert_expected_event("case_4", result)
        self.assertEqual(result["npc_response"]["response_type"], "disagreement")
        self.assertNotIn("verified_facts", result["interaction_event"])

    def test_case_5_memory_candidate_is_output_only(self) -> None:
        result, _, _, memory_store, _ = self._run_case("case_5")
        before = copy.deepcopy(memory_store)
        self._assert_expected_event("case_5", result)
        self.assertTrue(result["memory_candidate"])
        self.assertEqual(memory_store, before)

    def test_case_6_relationship_signal_is_output_only(self) -> None:
        result, _, _, _, relationship_store = self._run_case("case_6")
        before = copy.deepcopy(relationship_store)
        self._assert_expected_event("case_6", result)
        self.assertEqual(result["relationship_signal"], "potential_positive")
        self.assertEqual(relationship_store, before)

    def test_case_7_precondition_failure_calls_no_llm(self) -> None:
        result, provider, *_ = self._run_case("case_7")
        self._assert_expected_event("case_7", result)
        self.assertEqual(provider.calls, 0)
        self.assertIsNone(result["npc_response"])
        self.assertIsNone(result["interaction_event"])
        self.assertIn("not co-located", result["unavailable_reason"])

    def test_case_8_complete_pipeline_is_read_only(self) -> None:
        case = self.cases["case_8"]
        world = self._world_state(case)
        memory_store = self._memory_store(case)
        relationship_store = copy.deepcopy(
            self.relationship_fixtures[case["relationship_fixture"]]
        )
        before = (
            copy.deepcopy(world),
            copy.deepcopy(memory_store),
            copy.deepcopy(relationship_store),
        )
        result = run_npc_interaction(
            case["npc_id"],
            case["player_id"],
            case["player_utterance"],
            world,
            memory_store_document=memory_store,
            relationship_store_document=relationship_store,
            provider_client=MockProvider(copy.deepcopy(case["mock_response"])),
            system_prompt=self.prompt,
            response_schema=self.response_schema,
            result_schema=self.result_schema,
        )
        self._assert_expected_event("case_8", result)
        self.assertEqual((world, memory_store, relationship_store), before)

    def test_result_schema_references_frozen_contracts(self) -> None:
        schema_text = json.dumps(self.result_schema)
        for reference in (
            "npc_context.schema.json",
            "npc_memory_recall_context.schema.json",
            "npc_relationship_context.schema.json",
            "npc_response.schema.json",
            "npc_interaction_event.schema.json",
        ):
            self.assertIn(reference, schema_text)
        for forbidden in ("memory_commit", "relationship_commit", "world_mutation"):
            self.assertNotIn(forbidden, schema_text.casefold())

    def test_derived_fields_cannot_diverge_from_event(self) -> None:
        result, *_ = self._run_case("case_5")
        tampered = copy.deepcopy(result)
        tampered["memory_candidate"] = False
        with self.assertRaisesRegex(
            NpcInteractionRuntimeError,
            "memory_candidate must be derived",
        ):
            validate_interaction_runtime_result(tampered, self.result_schema)

    def test_precondition_failure_does_not_create_provider(self) -> None:
        case = self.cases["case_7"]
        with patch(
            "npc.interaction_runtime.create_llm_client",
            side_effect=AssertionError("provider must not be created"),
        ):
            result = run_npc_interaction(
                case["npc_id"],
                case["player_id"],
                case["player_utterance"],
                self._world_state(case),
                memory_store_document=self._memory_store(case),
                relationship_store_document=copy.deepcopy(
                    self.relationship_fixtures[case["relationship_fixture"]]
                ),
                result_schema=self.result_schema,
            )
        self.assertFalse(result["interaction_available"])

    def test_each_valid_golden_case_makes_exactly_one_llm_call(self) -> None:
        for case_number in (1, 2, 3, 4, 5, 6, 8):
            with self.subTest(case=case_number):
                _, provider, *_ = self._run_case(f"case_{case_number}")
                self.assertEqual(provider.calls, 1)

    def test_dataset_contains_exactly_eight_golden_cases(self) -> None:
        self.assertEqual(
            set(self.cases),
            {f"case_{index}" for index in range(1, 9)},
        )


if __name__ == "__main__":
    unittest.main()
