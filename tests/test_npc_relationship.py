"""Offline tests for deterministic NPC Relationship Evaluation v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from npc.relationship import (
    FAMILIARITY_MAX,
    FAMILIARITY_MIN,
    TRUST_MAX,
    TRUST_MIN,
    NpcRelationshipError,
    create_initial_relationship,
    evaluate_relationship_change,
    load_relationship_change_schema,
    load_relationship_schema,
    validate_relationship,
    validate_relationship_change,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = PROJECT_ROOT / "data" / "npc_relationship_test_cases.json"
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "saves" / "npc_memories.json",
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "schemas" / "npc_profile.schema.json",
    PROJECT_ROOT / "schemas" / "npc_context.schema.json",
    PROJECT_ROOT / "schemas" / "npc_response.schema.json",
    PROJECT_ROOT / "schemas" / "npc_interaction_event.schema.json",
    PROJECT_ROOT / "schemas" / "npc_memory.schema.json",
    PROJECT_ROOT / "schemas" / "npc_memory_store.schema.json",
    PROJECT_ROOT / "npc" / "context_builder.py",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "response_runtime_v0_2.py",
    PROJECT_ROOT / "npc" / "interaction_event.py",
    PROJECT_ROOT / "npc" / "memory.py",
    PROJECT_ROOT / "npc" / "memory_retriever.py",
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcRelationshipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case for case in cls.document["cases"]}
        cls.relationship_schema = load_relationship_schema()
        cls.change_schema = load_relationship_change_schema()
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
                "Relationship tests changed Persistent State or Frozen Baseline: "
                + ", ".join(str(path) for path in changed)
            )

    def evaluate_case(self, case_number: int) -> dict[str, Any]:
        case = self.cases[f"case_{case_number}"]
        relationship = copy.deepcopy(case["current_relationship"])
        event = copy.deepcopy(case["interaction_event"])
        relationship_before = copy.deepcopy(relationship)
        event_before = copy.deepcopy(event)
        preview = evaluate_relationship_change(
            relationship,
            event,
            relationship_schema=self.relationship_schema,
            change_schema=self.change_schema,
        )
        self.assertEqual(relationship, relationship_before)
        self.assertEqual(event, event_before)
        validate_relationship_change(
            preview,
            relationship_schema=self.relationship_schema,
            change_schema=self.change_schema,
        )
        expected = case["expected"]
        self.assertEqual(preview["decision"], expected["decision"])
        self.assertEqual(
            preview["proposed_relationship"]["familiarity"],
            expected["familiarity"],
        )
        self.assertEqual(
            preview["proposed_relationship"]["trust"],
            expected["trust"],
        )
        self.assertEqual(
            preview["proposed_relationship"]["attitude"],
            expected["attitude"],
        )
        return preview

    def test_schemas_and_all_eight_golden_cases_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.relationship_schema)
        Draft202012Validator.check_schema(self.change_schema)
        self.assertEqual(
            [case["id"] for case in self.document["cases"]],
            [f"case_{index}" for index in range(1, 9)],
        )
        for case in self.document["cases"]:
            validate_relationship(case["current_relationship"], self.relationship_schema)

    def test_case_1_greeting_does_not_change_relationship(self) -> None:
        preview = self.evaluate_case(1)
        self.assertFalse(any(item["changed"] for item in preview["changes"].values()))

    def test_case_2_ordinary_question_does_not_change_relationship(self) -> None:
        self.assertEqual(self.evaluate_case(2)["decision"], "no_change")

    def test_case_3_marriage_claim_creates_no_spouse_or_increase(self) -> None:
        preview = self.evaluate_case(3)
        self.assertEqual(preview["decision"], "no_change")
        serialized = json.dumps(preview).casefold()
        for forbidden in ("spouse", "marriage", "romance", "love"):
            self.assertNotIn(forbidden, serialized)

    def test_case_4_grounded_help_proposes_small_positive_change(self) -> None:
        preview = self.evaluate_case(4)
        self.assertEqual(preview["changes"]["familiarity"]["delta"], 1)
        self.assertEqual(preview["changes"]["trust"]["delta"], 1)
        self.assertEqual(preview["changes"]["attitude"]["after"], "warm")

    def test_case_5_repeated_small_talk_is_not_farmable(self) -> None:
        first = self.evaluate_case(5)
        second = self.evaluate_case(5)
        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "no_change")

    def test_case_6_grounded_threat_proposes_small_negative_change(self) -> None:
        preview = self.evaluate_case(6)
        self.assertEqual(preview["changes"]["familiarity"]["delta"], 0)
        self.assertEqual(preview["changes"]["trust"]["delta"], -1)
        self.assertEqual(preview["changes"]["attitude"]["after"], "wary")

    def test_case_7_unsupported_hero_claim_does_not_raise_trust(self) -> None:
        preview = self.evaluate_case(7)
        self.assertEqual(preview["decision"], "no_change")
        self.assertIn("Player claims", preview["reason"])

    def test_case_8_upper_bounds_cannot_be_exceeded(self) -> None:
        preview = self.evaluate_case(8)
        self.assertEqual(preview["proposed_relationship"]["familiarity"], FAMILIARITY_MAX)
        self.assertEqual(preview["proposed_relationship"]["trust"], TRUST_MAX)
        self.assertEqual(preview["decision"], "no_change")

    def test_lower_trust_bound_cannot_be_exceeded(self) -> None:
        case = copy.deepcopy(self.cases["case_6"])
        case["current_relationship"]["trust"] = TRUST_MIN
        case["current_relationship"]["attitude"] = "hostile"
        preview = evaluate_relationship_change(
            case["current_relationship"],
            case["interaction_event"],
        )
        self.assertEqual(preview["proposed_relationship"]["trust"], TRUST_MIN)
        self.assertGreaterEqual(
            preview["proposed_relationship"]["familiarity"],
            FAMILIARITY_MIN,
        )

    def test_initial_relationship_is_conservative_and_not_persistent(self) -> None:
        stranger = create_initial_relationship("npc_astrid", "player_002")
        acquainted = create_initial_relationship(
            "npc_astrid",
            "player_001",
            acquainted=True,
        )
        self.assertEqual(stranger["familiarity"], 0)
        self.assertEqual(acquainted["familiarity"], 1)
        self.assertEqual(stranger["trust"], 0)
        self.assertEqual(acquainted["attitude"], "neutral")

    def test_mismatched_relationship_identity_is_rejected(self) -> None:
        case = copy.deepcopy(self.cases["case_1"])
        case["current_relationship"]["npc_id"] = "npc_bjorn"
        with self.assertRaisesRegex(NpcRelationshipError, "NPC id does not match"):
            evaluate_relationship_change(
                case["current_relationship"],
                case["interaction_event"],
            )

    def test_model_and_preview_contracts_contain_no_commit_or_romance_fields(self) -> None:
        def property_names(value: Any) -> set[str]:
            names: set[str] = set()
            if isinstance(value, dict):
                properties = value.get("properties")
                if isinstance(properties, dict):
                    names.update(str(key).casefold() for key in properties)
                for child in value.values():
                    names.update(property_names(child))
            elif isinstance(value, list):
                for child in value:
                    names.update(property_names(child))
            return names

        schema_fields = property_names(
            {
                "relationship": self.relationship_schema,
                "change": self.change_schema,
            }
        )
        for forbidden in (
            "commit",
            "spouse",
            "marriage",
            "romance",
            "jealousy",
            "loyalty",
            "relationship_type",
        ):
            self.assertNotIn(forbidden, schema_fields)


if __name__ == "__main__":
    unittest.main()
