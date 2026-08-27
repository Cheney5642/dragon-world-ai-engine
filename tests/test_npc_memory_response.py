"""Offline integration tests for memory-aware NPC Response Runtime v0.2."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from npc.context_builder import build_npc_context
from npc.memory import MEMORY_STORE_PATH
from npc.response_runtime import NpcInteractionUnavailableError, load_response_schema
from npc.response_runtime_v0_2 import (
    generate_npc_response_with_memory,
    load_memory_response_prompt,
    prepare_memory_aware_context,
    validate_memory_aware_response,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
DATASET_PATH = PROJECT_ROOT / "data" / "npc_memory_retrieval_test_cases.json"
PROTECTED_PATHS = (
    SEED_PATH,
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    MEMORY_STORE_PATH,
    PROJECT_ROOT / "prompts" / "npc_response_system.md",
    PROJECT_ROOT / "schemas" / "npc_response.schema.json",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "context_builder.py",
    PROJECT_ROOT / "npc" / "memory.py",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_response(
    speech: str,
    *,
    response_type: str = "answer",
    knowledge_status: str = "not_applicable",
) -> dict[str, Any]:
    return {
        "npc_id": "npc_astrid",
        "response_type": response_type,
        "speech": speech,
        "knowledge_status": knowledge_status,
        "referenced_knowledge": {
            "entity_ids": [],
            "location_ids": [],
            "facts": [],
        },
        "requires_followup": False,
    }


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


class NpcMemoryResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        cls.world_state["player"]["name"] = "Eirik"
        cls.world_state["player"]["species"] = "human"
        cls.world_state["player"]["occupation"] = "blacksmith apprentice"
        dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        cls.fixtures = {
            memory["memory_id"]: memory
            for memory in dataset["memory_fixtures"]
        }
        cls.schema = load_response_schema()
        cls.prompt = load_memory_response_prompt()
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
                "Memory Response tests changed Persistent State or Frozen Baseline: "
                + ", ".join(str(path) for path in changed)
            )

    def store_with(self, *memory_ids: str) -> dict[str, Any]:
        return {
            "version": "0.1",
            "memories": [copy.deepcopy(self.fixtures[item]) for item in memory_ids],
        }

    def test_relevant_memory_is_injected_into_provider_message(self) -> None:
        provider = MockProvider(valid_response("我记得你之前说过想离开 Skeld。"))
        result = generate_npc_response_with_memory(
            "npc_astrid",
            "你还记得我想离开 Skeld 吗？",
            copy.deepcopy(self.world_state),
            store_document=self.store_with(
                "npc_memory_11111111111111111111111111111111"
            ),
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertEqual(result["npc_id"], "npc_astrid")
        self.assertEqual(provider.calls, 1)
        self.assertIn("Eirik intends to leave Skeld", provider.last_request["user_message"])

    def test_irrelevant_memory_is_not_injected(self) -> None:
        response = valid_response("Bjorn 是 Skeld 的铁匠。", knowledge_status="known")
        response["referenced_knowledge"]["entity_ids"] = ["npc_bjorn"]
        provider = MockProvider(response)
        result = generate_npc_response_with_memory(
            "npc_astrid",
            "Bjorn 是做什么的？",
            copy.deepcopy(self.world_state),
            store_document=self.store_with(
                "npc_memory_11111111111111111111111111111111"
            ),
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertIn("铁匠", result["speech"])
        self.assertIn("npc_bjorn", result["referenced_knowledge"]["entity_ids"])
        self.assertNotIn(
            "Eirik intends to leave Skeld",
            provider.last_request["user_message"],
        )

    def test_reported_player_memory_preserves_attribution(self) -> None:
        response = valid_response("我记得你之前说过，Bjorn 是国王；那只是你当时的说法。")
        provider = MockProvider(response)
        result = generate_npc_response_with_memory(
            "npc_astrid",
            "我以前是不是说过 Bjorn 是国王？",
            copy.deepcopy(self.world_state),
            store_document=self.store_with(
                "npc_memory_33333333333333333333333333333333"
            ),
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertIn("你之前说过", result["speech"])
        self.assertIn("只是你当时的说法", result["speech"])
        self.assertEqual(result["referenced_knowledge"]["facts"], [])

    def test_player_intention_is_not_rewritten_as_completed_action(self) -> None:
        response = valid_response(
            "我记得你说过打算独自去 Stormcliff，但那只说明你计划过，不代表已经去过。"
        )
        provider = MockProvider(response)
        result = generate_npc_response_with_memory(
            "npc_astrid",
            "我是不是已经去过 Stormcliff 了？",
            copy.deepcopy(self.world_state),
            store_document=self.store_with(
                "npc_memory_22222222222222222222222222222222"
            ),
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertIn("计划过", result["speech"])
        self.assertIn("不代表已经去过", result["speech"])

    def test_empty_recall_does_not_create_false_memory(self) -> None:
        response = valid_response(
            "我目前没有可确认的相关记忆。",
            response_type="uncertain",
            knowledge_status="unknown",
        )
        provider = MockProvider(response)
        result = generate_npc_response_with_memory(
            "npc_astrid",
            "你还记得我以前说过什么吗？",
            copy.deepcopy(self.world_state),
            store_document={"version": "0.1", "memories": []},
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertEqual(result["knowledge_status"], "unknown")
        self.assertIn("没有可确认", result["speech"])
        self.assertNotIn("npc_memory_", provider.last_request["user_message"])

    def test_output_reuses_existing_response_schema(self) -> None:
        context = build_npc_context("npc_astrid", copy.deepcopy(self.world_state))
        recall = {
            "npc_id": "npc_astrid",
            "player_id": "player_001",
            "retrieved_memories": [],
        }
        validate_memory_aware_response(
            valid_response("我不知道。", response_type="uncertain", knowledge_status="unknown"),
            self.schema,
            context,
            recall,
        )

    def test_memory_cannot_be_promoted_into_referenced_knowledge(self) -> None:
        context, recall = prepare_memory_aware_context(
            "npc_astrid",
            "我是不是说过 Bjorn 是国王？",
            copy.deepcopy(self.world_state),
            store_document=self.store_with(
                "npc_memory_33333333333333333333333333333333"
            ),
        )
        response = valid_response("我记得你这样说过。")
        response["referenced_knowledge"]["facts"] = [
            "Eirik claims that Bjorn is a king."
        ]
        with self.assertRaisesRegex(Exception, "outside the supplied Context"):
            validate_memory_aware_response(response, self.schema, context, recall)

    def test_non_colocated_interaction_stops_before_memory_and_provider(self) -> None:
        world_state = copy.deepcopy(self.world_state)
        world_state["player"]["current_location"] = "stormcliff"
        provider = MockProvider(valid_response("听不见。"))
        with self.assertRaisesRegex(NpcInteractionUnavailableError, "not co-located"):
            generate_npc_response_with_memory(
                "npc_astrid",
                "你能听见吗？",
                world_state,
                store_document={"version": "0.1", "memories": []},
                provider_client=provider,  # type: ignore[arg-type]
                system_prompt=self.prompt,
                response_schema=self.schema,
            )
        self.assertEqual(provider.calls, 0)

    def test_runtime_does_not_mutate_world_or_injected_store(self) -> None:
        world_state = copy.deepcopy(self.world_state)
        store = self.store_with("npc_memory_11111111111111111111111111111111")
        world_before = copy.deepcopy(world_state)
        store_before = copy.deepcopy(store)
        provider = MockProvider(valid_response("我记得你说过想离开 Skeld。"))
        generate_npc_response_with_memory(
            "npc_astrid",
            "记得我想离开 Skeld 吗？",
            world_state,
            store_document=store,
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertEqual(world_state, world_before)
        self.assertEqual(store, store_before)


if __name__ == "__main__":
    unittest.main()
