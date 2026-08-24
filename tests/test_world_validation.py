"""Offline safety and deterministic checks for World Validation v0.1."""

from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import interpret_action  # noqa: E402
from scripts import validate_action  # noqa: E402


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target(kind: str, entity_id: str | None, name: str) -> dict[str, Any]:
    return {"type": kind, "id": entity_id, "name": name}


def step(
    verb: str,
    target_value: dict[str, Any] | None = None,
    goal: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    return {
        "verb": verb,
        "target": target_value,
        "goal": goal,
        "method": method,
    }


def action(
    raw_input: str,
    action_kind: str,
    steps: list[dict[str, Any]],
    *,
    speech: str | None = None,
    claimed_facts: list[str] | None = None,
) -> dict[str, Any]:
    claims = claimed_facts or []
    return {
        "raw_input": raw_input,
        "action_kind": action_kind,
        "steps": steps,
        "speech": speech,
        "claimed_facts": claims,
        "requires_world_check": (
            action_kind not in {"speech", "self_expression"} or bool(claims)
        ),
        "needs_clarification": False,
    }


class WorldValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world_state = interpret_action.load_current_world()
        cls.validation_schema = validate_action.load_validation_schema()
        cls.seed_hash = file_hash(PROJECT_ROOT / "data" / "world_seed.json")
        cls.save_hash = file_hash(interpret_action.SAVE_PATH)
        cls.cases = {
            "case_1": action(
                "find Astrid",
                "interaction",
                [step("go find", target("npc", "npc_astrid", "Astrid"))],
            ),
            "case_2": action(
                "fly to Stormcliff",
                "movement",
                [step("fly", target("location", "stormcliff", "Stormcliff"))],
            ),
            "case_3": action(
                "find Bjorn and steal his hammer",
                "compound",
                [
                    step("approach", target("npc", "npc_bjorn", "Bjorn")),
                    step(
                        "steal",
                        target("object", None, "Bjorn's hammer"),
                        method="secretly",
                    ),
                ],
            ),
            "case_4": action(
                "I have an AK47",
                "other",
                [step("claim", target("object", None, "AK47"))],
                claimed_facts=["The Player claims current possession of an AK47."],
            ),
            "case_5": action(
                "I am Odin!",
                "speech",
                [step("say")],
                speech="I am Odin!",
            ),
            "case_6": action(
                "go to Stormcliff",
                "movement",
                [step("go", target("location", "stormcliff", "Stormcliff"))],
            ),
            "case_7": action(
                "invite Astrid",
                "interaction",
                [step("invite", target("npc", "npc_astrid", "Astrid"))],
            ),
            "case_8": action(
                "find Ragnar",
                "interaction",
                [step("find", target("npc", None, "Ragnar"))],
            ),
        }

    @classmethod
    def tearDownClass(cls) -> None:
        if file_hash(PROJECT_ROOT / "data" / "world_seed.json") != cls.seed_hash:
            raise AssertionError("world_seed.json changed during validation tests")
        if file_hash(interpret_action.SAVE_PATH) != cls.save_hash:
            raise AssertionError("current_world.json changed during validation tests")

    def test_deterministic_baseline_statuses(self) -> None:
        expected = {
            "case_1": "allowed",
            "case_2": "blocked",
            "case_3": "conditional",
            "case_4": "blocked",
            "case_5": "allowed",
            "case_6": "allowed",
            "case_7": "conditional",
            "case_8": "conditional",
        }
        for case_id, expected_status in expected.items():
            with self.subTest(case_id=case_id):
                assessment = validate_action.build_deterministic_assessment(
                    self.cases[case_id], self.world_state
                )
                self.assertEqual(
                    assessment.recommended_overall_status,
                    expected_status,
                )

    def test_context_contains_only_relevant_entities(self) -> None:
        intent = self.cases["case_1"]
        assessment = validate_action.build_deterministic_assessment(
            intent, self.world_state
        )
        context = validate_action.build_validation_context(
            intent, self.world_state, assessment
        )
        self.assertEqual(
            [npc["id"] for npc in context["relevant_npcs"]],
            ["npc_astrid"],
        )
        self.assertEqual(
            {location["id"] for location in context["relevant_locations"]},
            {"skeld_village"},
        )
        self.assertNotIn("personality", str(context))
        self.assertNotIn("memories", str(context))
        self.assertNotIn("knowledge", str(context))

    def test_unknown_hammer_is_not_converted_to_false(self) -> None:
        assessment = validate_action.build_deterministic_assessment(
            self.cases["case_3"], self.world_state
        )
        hammer_checks = [
            check
            for check in assessment.checks
            if "hammer" in check["fact"].casefold()
        ]
        self.assertEqual(len(hammer_checks), 1)
        self.assertEqual(hammer_checks[0]["status"], "unknown")

    def test_model_cannot_reverse_deterministic_block(self) -> None:
        assessment = validate_action.build_deterministic_assessment(
            self.cases["case_2"], self.world_state
        )
        invalid_result = {
            "overall_status": "allowed",
            "checks": copy.deepcopy(assessment.checks),
            "missing_requirements": list(assessment.missing_requirements),
            "conflicts": list(assessment.conflicts),
            "requires_npc_decision": assessment.requires_npc_decision,
            "requires_further_resolution": assessment.requires_further_resolution,
            "validated_interpretation": "The action can continue.",
        }
        validate_action.validate_world_validation_schema(
            invalid_result, self.validation_schema
        )
        with self.assertRaises(validate_action.WorldValidationError):
            validate_action.validate_deterministic_consistency(
                invalid_result, assessment
            )

        grounded = validate_action.apply_deterministic_validation(
            invalid_result, assessment
        )
        self.assertEqual(grounded["overall_status"], "blocked")
        validate_action.validate_world_validation_result(
            grounded, self.validation_schema, assessment
        )

    def test_evaluation_entry_points_are_read_only(self) -> None:
        provider = SimpleNamespace(provider="mock", model="mock-model")
        before = interpret_action.SAVE_PATH.read_bytes()
        for arguments in (["--test"], ["--test-case", "3"]):
            with self.subTest(arguments=arguments):
                with (
                    patch.object(sys, "argv", ["validate_action.py", *arguments]),
                    patch.object(
                        validate_action,
                        "create_llm_client",
                        return_value=provider,
                    ),
                    patch.object(
                        validate_action,
                        "run_test_mode",
                        return_value=0,
                    ),
                ):
                    self.assertEqual(validate_action.main(), 0)
        self.assertEqual(interpret_action.SAVE_PATH.read_bytes(), before)

    def test_action_clarification_stops_before_world_validation(self) -> None:
        intent = copy.deepcopy(self.cases["case_8"])
        intent["needs_clarification"] = True
        provider = SimpleNamespace(provider="mock", model="mock-model")
        with (
            patch.object(sys, "argv", ["validate_action.py"]),
            patch.object(
                validate_action,
                "create_llm_client",
                return_value=provider,
            ),
            patch.object(
                interpret_action,
                "display_player_status",
            ),
            patch.object(
                interpret_action,
                "read_action_input",
                return_value=intent["raw_input"],
            ),
            patch.object(
                interpret_action,
                "request_action_interpretation",
                return_value=intent,
            ),
            patch.object(
                validate_action,
                "request_world_validation",
            ) as world_validation,
        ):
            self.assertEqual(validate_action.main(), 0)
            world_validation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
