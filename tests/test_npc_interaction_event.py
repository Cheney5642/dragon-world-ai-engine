"""Offline tests for the read-only NPC Interaction Event Layer v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from npc.context_builder import build_npc_context
from npc.interaction_event import (
    build_interaction_event,
    load_interaction_event_schema,
)
from npc.memory import build_memory_preview


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
CASES_PATH = PROJECT_ROOT / "data" / "npc_interaction_event_test_cases.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcInteractionEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = load_json(SEED_PATH)
        cls.schema = load_interaction_event_schema()
        document = load_json(CASES_PATH)
        cls.cases = {case["id"]: case for case in document["cases"]}
        cls.protected_hashes = {
            path: file_hash(path)
            for path in (SEED_PATH, SAVE_PATH, PROFILES_PATH)
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
                "Protected state changed during Interaction Event tests: "
                + ", ".join(str(path) for path in changed)
            )

    def build_case(
        self,
        case_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        case = self.cases[f"case_{case_number}"]
        world_state = copy.deepcopy(self.world_state)
        world_state["player"]["name"] = "Eirik"
        context = build_npc_context(case["npc_id"], world_state)
        context_before = copy.deepcopy(context)
        response = copy.deepcopy(case["npc_response"])
        response_before = copy.deepcopy(response)
        event = build_interaction_event(
            context,
            case["player_utterance"],
            response,
        )
        Draft202012Validator(self.schema).validate(event)
        self.assertEqual(context, context_before)
        self.assertEqual(response, response_before)
        return case, context, event

    def build_intention(self, utterance: str) -> dict[str, Any]:
        world_state = copy.deepcopy(self.world_state)
        world_state["player"]["name"] = "Eirik"
        context = build_npc_context("npc_astrid", world_state)
        response = {
            "npc_id": "npc_astrid",
            "response_type": "reaction",
            "speech": "听起来你已经有了明确的计划。",
            "knowledge_status": "not_applicable",
            "referenced_knowledge": {
                "entity_ids": [],
                "location_ids": [],
                "facts": [],
            },
            "requires_followup": False,
        }
        event = build_interaction_event(context, utterance, response)
        Draft202012Validator(self.schema).validate(event)
        return event

    def test_case_1_ordinary_question_is_not_a_claim(self) -> None:
        case, _, event = self.build_case(1)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertEqual(event["player_claims"], [])
        self.assertFalse(event["memory_candidate"])
        self.assertEqual(event["relationship_signal"], "none")

    def test_case_2_significant_departure_goal_is_memory_candidate(self) -> None:
        case, _, event = self.build_case(2)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertTrue(
            any(
                case["expected"]["claim_contains"] in claim
                for claim in event["player_claims"]
            )
        )
        self.assertTrue(event["memory_candidate"])
        self.assertEqual(event["relationship_signal"], "none")

    def test_case_3_player_claim_remains_attributed_and_unverified(self) -> None:
        case, _, event = self.build_case(3)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertTrue(
            any(
                case["expected"]["claim_contains"] in claim
                for claim in event["player_claims"]
            )
        )
        self.assertFalse(event["memory_candidate"])
        self.assertNotIn("verified_facts", event)
        self.assertNotIn("world_facts", event)

    def test_case_4_relationship_declaration_never_becomes_mutation(self) -> None:
        case, _, event = self.build_case(4)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertTrue(
            any(
                case["expected"]["claim_contains"] in claim
                for claim in event["player_claims"]
            )
        )
        self.assertFalse(event["memory_candidate"])
        self.assertIn(
            event["relationship_signal"],
            case["expected"]["relationship_signal_allowed"],
        )
        self.assertNotIn("relationship_mutation", event)
        self.assertNotIn("relationship_delta", event)

    def test_case_5_coastal_question_is_not_a_player_claim(self) -> None:
        case, _, event = self.build_case(5)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertEqual(event["player_claims"], [])
        self.assertFalse(event["memory_candidate"])
        self.assertEqual(event["relationship_signal"], "none")

    def test_case_6_significant_near_term_plan_is_memory_candidate(self) -> None:
        case, _, event = self.build_case(6)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertTrue(
            any(
                case["expected"]["claim_contains"] in claim
                for claim in event["player_claims"]
            )
        )
        self.assertTrue(event["memory_candidate"])
        self.assertEqual(event["relationship_signal"], "none")

    def test_case_7_greeting_is_not_a_memory_candidate(self) -> None:
        case, _, event = self.build_case(7)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertEqual(event["player_claims"], [])
        self.assertFalse(event["memory_candidate"])
        self.assertEqual(event["relationship_signal"], "none")

    def test_v02_old_ruins_plan_is_player_intention_memory(self) -> None:
        event = self.build_intention(
            "我明天准备去 Old Ruins 寻找失踪的商队。"
        )
        self.assertTrue(event["memory_candidate"])
        memory = build_memory_preview(event)
        self.assertEqual(memory["memory_type"], "player_intention")
        self.assertEqual(memory["epistemic_status"], "reported_by_player")

    def test_v02_whispering_woods_plan_is_memory_candidate(self) -> None:
        event = self.build_intention(
            "今晚我要去 Whispering Woods 找药草。"
        )
        self.assertTrue(event["memory_candidate"])

    def test_case_8_builder_is_read_only_for_files_and_inputs(self) -> None:
        before = {
            path: file_hash(path)
            for path in (SEED_PATH, SAVE_PATH, PROFILES_PATH)
        }
        case, context, event = self.build_case(8)
        self.assertEqual(event["topic"], case["expected"]["topic"])
        self.assertEqual(event["npc_id"], context["npc"]["id"])
        self.assertEqual(event["player_id"], context["player"]["id"])
        self.assertEqual(
            before,
            {
                path: file_hash(path)
                for path in (SEED_PATH, SAVE_PATH, PROFILES_PATH)
            },
        )

    def test_event_ids_are_unique_and_schema_valid(self) -> None:
        _, _, first = self.build_case(1)
        _, _, second = self.build_case(1)
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.assertRegex(first["event_id"], r"^npc_event_[0-9a-f]{32}$")
        self.assertRegex(second["event_id"], r"^npc_event_[0-9a-f]{32}$")

    def test_schema_has_no_write_or_numeric_relationship_fields(self) -> None:
        schema_text = json.dumps(self.schema).casefold()
        for forbidden in (
            "memory_write",
            "relationship_delta",
            "trust_score",
            "quest_mutation",
            "world_mutation",
            "state_mutation",
        ):
            self.assertNotIn(forbidden, schema_text)
        self.assertFalse(self.schema["additionalProperties"])

    def test_all_eight_golden_cases_match_schema(self) -> None:
        self.assertEqual(
            list(self.cases),
            [f"case_{number}" for number in range(1, 9)],
        )
        Draft202012Validator.check_schema(self.schema)
        for number in range(1, 9):
            with self.subTest(case=number):
                self.build_case(number)


if __name__ == "__main__":
    unittest.main()
