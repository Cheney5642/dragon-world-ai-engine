"""Offline grounding and mutation-boundary tests for NPC Response Runtime v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from npc.context_builder import build_npc_context
from npc.response_runtime import (
    NpcInteractionUnavailableError,
    NpcResponseError,
    build_response_user_message,
    generate_npc_response,
    load_response_prompt,
    load_response_schema,
    validate_npc_response,
)
from scripts.talk_to_npc import load_test_cases


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_response() -> dict[str, Any]:
    return {
        "npc_id": "npc_astrid",
        "response_type": "answer",
        "speech": "Bjorn 是 Skeld 的铁匠。",
        "knowledge_status": "known",
        "referenced_knowledge": {
            "entity_ids": ["npc_bjorn"],
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


class NpcResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = load_json(SEED_PATH)
        cls.schema = load_response_schema()
        cls.prompt = load_response_prompt()
        cls.seed_hash = file_hash(SEED_PATH)
        cls.save_hash = file_hash(SAVE_PATH)
        cls.profiles_hash = file_hash(PROFILES_PATH)

    @classmethod
    def tearDownClass(cls) -> None:
        if file_hash(SEED_PATH) != cls.seed_hash:
            raise AssertionError("world_seed.json changed during NPC Response tests")
        if file_hash(SAVE_PATH) != cls.save_hash:
            raise AssertionError("current_world.json changed during NPC Response tests")
        if file_hash(PROFILES_PATH) != cls.profiles_hash:
            raise AssertionError("Anchor NPC Profiles changed during NPC Response tests")

    def test_valid_mock_response_passes_schema_and_context_grounding(self) -> None:
        context = build_npc_context("npc_astrid", copy.deepcopy(self.world_state))
        response = valid_response()
        Draft202012Validator.check_schema(self.schema)
        validate_npc_response(response, self.schema, context)

    def test_reference_outside_context_is_rejected(self) -> None:
        context = build_npc_context("npc_astrid", copy.deepcopy(self.world_state))
        response = valid_response()
        response["referenced_knowledge"]["entity_ids"] = ["npc_haldor"]
        with self.assertRaisesRegex(NpcResponseError, "outside the supplied Context"):
            validate_npc_response(response, self.schema, context)

    def test_response_for_wrong_npc_is_rejected(self) -> None:
        context = build_npc_context("npc_astrid", copy.deepcopy(self.world_state))
        response = valid_response()
        response["npc_id"] = "npc_bjorn"
        with self.assertRaisesRegex(NpcResponseError, "does not match Context id"):
            validate_npc_response(response, self.schema, context)

    def test_non_colocated_interaction_stops_before_provider_call(self) -> None:
        world_state = copy.deepcopy(self.world_state)
        world_state["player"]["current_location"] = "stormcliff"
        provider = MockProvider(valid_response())
        with self.assertRaisesRegex(NpcInteractionUnavailableError, "not co-located"):
            generate_npc_response(
                "npc_astrid",
                "Astrid，你能听见我吗？",
                world_state,
                provider_client=provider,  # type: ignore[arg-type]
                system_prompt=self.prompt,
                response_schema=self.schema,
            )
        self.assertEqual(provider.calls, 0)

    def test_provider_receives_only_context_and_current_utterance(self) -> None:
        context = build_npc_context("npc_astrid", copy.deepcopy(self.world_state))
        message = build_response_user_message(context, "Bjorn 是做什么的？")
        self.assertIn("npc_context", message)
        self.assertIn("player_utterance", message)
        for forbidden in (
            "global_state",
            "world.rules",
            "village_safety",
            "relationships",
            "memories",
            "inventory",
            "current_goal",
        ):
            self.assertNotIn(forbidden, message)

    def test_generate_response_is_read_only_with_mock_provider(self) -> None:
        world_state = copy.deepcopy(self.world_state)
        before = copy.deepcopy(world_state)
        provider = MockProvider(valid_response())
        result = generate_npc_response(
            "npc_astrid",
            "Bjorn 是做什么的？",
            world_state,
            provider_client=provider,  # type: ignore[arg-type]
            system_prompt=self.prompt,
            response_schema=self.schema,
        )
        self.assertEqual(result, valid_response())
        self.assertEqual(provider.calls, 1)
        self.assertEqual(world_state, before)

    def test_response_contract_contains_no_mutation_fields(self) -> None:
        schema_text = json.dumps(self.schema).casefold()
        for forbidden in (
            "relationship_delta",
            "memory_write",
            "quest_update",
            "state_mutations",
            "proposed_mutations",
        ):
            self.assertNotIn(forbidden, schema_text)
        self.assertFalse(self.schema["additionalProperties"])

    def test_golden_dataset_has_eight_cases_and_case_8_setup(self) -> None:
        cases = load_test_cases()
        self.assertEqual([case["id"] for case in cases], [f"case_{i}" for i in range(1, 9)])
        self.assertEqual(
            cases[7]["setup"]["player_current_location"],
            "stormcliff",
        )


if __name__ == "__main__":
    unittest.main()
