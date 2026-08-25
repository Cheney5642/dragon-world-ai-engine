"""Offline mutation-boundary tests for Action Execution v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import execute_action  # noqa: E402
from scripts import interpret_action  # noqa: E402


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ActionExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.execution_schema = execute_action.load_execution_schema()
        cls.seed_hash = file_hash(execute_action.WORLD_SEED_PATH)
        cls.persistent_save_hash = file_hash(execute_action.SAVE_PATH)

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.save_path = Path(self.temporary_directory.name) / "current_world.json"
        shutil.copyfile(execute_action.SAVE_PATH, self.save_path)
        with self.save_path.open("r", encoding="utf-8") as file:
            fixture = json.load(file)
        fixture["player"]["current_location"] = "skeld_village"
        with self.save_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(fixture, file, ensure_ascii=False, indent=2)
            file.write("\n")
        self.world_state = interpret_action.load_current_world(self.save_path)
        self.allowed = execute_action.fixture_validation("allowed")
        self.movement = execute_action.fixture_action(
            "movement",
            [
                execute_action.fixture_step(
                    "go",
                    execute_action.fixture_target(
                        "location", "stormcliff", "Stormcliff"
                    ),
                )
            ],
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()
        self.assertEqual(file_hash(execute_action.WORLD_SEED_PATH), self.seed_hash)
        self.assertEqual(
            file_hash(execute_action.SAVE_PATH), self.persistent_save_hash
        )

    def movement_plan(self) -> dict:
        plan = execute_action.build_execution_plan(
            self.movement, self.allowed, self.world_state
        )
        execute_action.validate_execution_schema(plan, self.execution_schema)
        return plan

    def test_allowed_movement_proposes_only_current_location(self) -> None:
        plan = self.movement_plan()
        execute_action.validate_mutation_plan(
            plan, self.allowed, self.world_state
        )
        self.assertEqual(plan["execution_type"], "movement")
        self.assertEqual(len(plan["proposed_mutations"]), 1)
        self.assertEqual(
            plan["proposed_mutations"][0],
            {
                "entity_type": "player",
                "entity_id": "player_001",
                "field": "current_location",
                "old_value": "skeld_village",
                "new_value": "stormcliff",
            },
        )

    def test_movement_commit_changes_only_player_location(self) -> None:
        plan = self.movement_plan()
        before = interpret_action.load_current_world(self.save_path)
        committed_player = execute_action.commit_execution_plan(
            plan, self.allowed, self.save_path
        )
        after = interpret_action.load_current_world(self.save_path)
        self.assertEqual(committed_player["current_location"], "stormcliff")
        self.assertEqual(after["player"]["current_location"], "stormcliff")
        for field, value in before["player"].items():
            if field != "current_location":
                self.assertEqual(after["player"][field], value)
        for section in ("world", "locations", "npcs", "global_state"):
            self.assertEqual(after[section], before[section])

    def test_cancelled_confirmation_does_not_change_save(self) -> None:
        plan = self.movement_plan()
        before = self.save_path.read_bytes()
        result = execute_action.confirm_and_commit_execution(
            plan,
            self.allowed,
            self.save_path,
            input_fn=lambda _prompt: "no",
        )
        self.assertIsNone(result)
        self.assertEqual(self.save_path.read_bytes(), before)

    def test_blocked_action_cannot_enter_executor(self) -> None:
        with self.assertRaises(execute_action.ExecutionEligibilityError):
            execute_action.build_execution_plan(
                self.movement,
                execute_action.fixture_validation("blocked"),
                self.world_state,
            )

    def test_conditional_action_cannot_enter_executor(self) -> None:
        with self.assertRaises(execute_action.ExecutionEligibilityError):
            execute_action.build_execution_plan(
                self.movement,
                execute_action.fixture_validation("conditional"),
                self.world_state,
            )

    def test_find_astrid_is_encounter_without_mutation(self) -> None:
        action = execute_action.fixture_action(
            "interaction",
            [
                execute_action.fixture_step(
                    "go find",
                    execute_action.fixture_target("npc", "npc_astrid", "Astrid"),
                )
            ],
        )
        plan = execute_action.build_execution_plan(
            action, self.allowed, self.world_state
        )
        execute_action.validate_execution_schema(plan, self.execution_schema)
        execute_action.validate_mutation_plan(
            plan, self.allowed, self.world_state
        )
        self.assertEqual(plan["execution_type"], "encounter")
        self.assertEqual(plan["proposed_mutations"], [])
        self.assertEqual(plan["requires_next_system"], "npc_interaction")
        self.assertEqual(plan["resolved_entities"][0]["entity_id"], "npc_astrid")

    def test_speech_does_not_mutate_player_identity(self) -> None:
        action = execute_action.fixture_action(
            "speech",
            [execute_action.fixture_step("say")],
            speech="我是奥丁！",
        )
        plan = execute_action.build_execution_plan(
            action, self.allowed, self.world_state
        )
        updated = execute_action.apply_execution_plan_in_memory(
            plan, self.allowed, self.world_state
        )
        self.assertEqual(plan["execution_type"], "speech")
        self.assertEqual(plan["proposed_mutations"], [])
        self.assertEqual(updated["player"], self.world_state["player"])

    def test_mutation_validator_rejects_non_allowlisted_field(self) -> None:
        plan = self.movement_plan()
        plan["proposed_mutations"][0]["field"] = "inventory"
        with self.assertRaises(execute_action.ActionExecutionError):
            execute_action.validate_mutation_plan(
                plan, self.allowed, self.world_state
            )

    def test_mutation_validator_rejects_stale_old_value(self) -> None:
        plan = self.movement_plan()
        plan["proposed_mutations"][0]["old_value"] = "old_ruins"
        with self.assertRaises(execute_action.ActionExecutionError):
            execute_action.validate_mutation_plan(
                plan, self.allowed, self.world_state
            )

    def test_world_seed_cannot_be_commit_target(self) -> None:
        plan = self.movement_plan()
        before = execute_action.WORLD_SEED_PATH.read_bytes()
        with self.assertRaises(execute_action.ActionExecutionError):
            execute_action.commit_execution_plan(
                plan,
                self.allowed,
                execute_action.WORLD_SEED_PATH,
                execution_schema=self.execution_schema,
            )
        self.assertEqual(execute_action.WORLD_SEED_PATH.read_bytes(), before)

    def test_cli_evaluation_is_read_only(self) -> None:
        before_seed = file_hash(execute_action.WORLD_SEED_PATH)
        before_save = file_hash(execute_action.SAVE_PATH)
        self.assertEqual(
            execute_action.run_execution_test_mode(
                interpret_action.load_current_world(),
                self.execution_schema,
            ),
            0,
        )
        self.assertEqual(file_hash(execute_action.WORLD_SEED_PATH), before_seed)
        self.assertEqual(file_hash(execute_action.SAVE_PATH), before_save)


if __name__ == "__main__":
    unittest.main()
