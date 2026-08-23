"""Offline safety checks for Player Commit v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import create_player  # noqa: E402


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PlayerCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = create_player.load_json_file(create_player.SCHEMA_PATH)
        test_data = create_player.load_json_file(create_player.TEST_CASES_PATH)
        cases = {case["id"]: case["expected_output"] for case in test_data["test_cases"]}
        cls.valid_result = cases["case_1"]
        cls.clarification_result = cases["case_6"]
        cls.seed_hash = file_hash(create_player.WORLD_PATH)

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.save_path = Path(self.temporary_directory.name) / "current_world.json"
        shutil.copyfile(create_player.WORLD_PATH, self.save_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()
        self.assertEqual(file_hash(create_player.WORLD_PATH), self.seed_hash)

    def test_needs_clarification_blocks_commit_without_prompt(self) -> None:
        before = self.save_path.read_bytes()

        def unexpected_prompt(_: str) -> str:
            raise AssertionError("clarification result must not prompt for commit")

        with self.assertRaises(create_player.ClarificationRequiredError):
            create_player.confirm_and_commit_player(
                copy.deepcopy(self.clarification_result),
                self.schema,
                self.save_path,
                input_fn=unexpected_prompt,
            )
        self.assertEqual(self.save_path.read_bytes(), before)

    def test_cancelled_confirmation_never_changes_save(self) -> None:
        for answer in ("", "n", "no", "anything else"):
            with self.subTest(answer=answer):
                before = self.save_path.read_bytes()
                committed = create_player.confirm_and_commit_player(
                    copy.deepcopy(self.valid_result),
                    self.schema,
                    self.save_path,
                    input_fn=lambda _prompt, value=answer: value,
                )
                self.assertIsNone(committed)
                self.assertEqual(self.save_path.read_bytes(), before)

    def test_valid_player_commit_changes_only_player_state(self) -> None:
        before = create_player.load_current_save(self.save_path)
        committed_player = create_player.confirm_and_commit_player(
            copy.deepcopy(self.valid_result),
            self.schema,
            self.save_path,
            input_fn=lambda _prompt: "yes",
        )
        after = create_player.load_current_save(self.save_path)

        self.assertIsNotNone(committed_player)
        self.assertEqual(after["player"]["id"], "player_001")
        self.assertEqual(after["player"]["name"], "Eirik")
        for section in ("world", "locations", "npcs", "global_state"):
            self.assertEqual(after[section], before[section])

    def test_existing_player_cannot_be_overwritten(self) -> None:
        create_player.confirm_and_commit_player(
            copy.deepcopy(self.valid_result),
            self.schema,
            self.save_path,
            input_fn=lambda _prompt: "y",
        )
        before_second_attempt = self.save_path.read_bytes()

        def unexpected_prompt(_: str) -> str:
            raise AssertionError("existing player must block before confirmation")

        with self.assertRaises(create_player.ExistingPlayerError):
            create_player.confirm_and_commit_player(
                copy.deepcopy(self.valid_result),
                self.schema,
                self.save_path,
                input_fn=unexpected_prompt,
            )
        self.assertEqual(self.save_path.read_bytes(), before_second_attempt)

    def test_missing_save_is_not_created(self) -> None:
        missing_save = Path(self.temporary_directory.name) / "missing_world.json"
        with self.assertRaises(create_player.CurrentSaveNotFoundError):
            create_player.load_current_save(missing_save)
        self.assertFalse(missing_save.exists())

    def test_committed_save_remains_valid_json(self) -> None:
        create_player.confirm_and_commit_player(
            copy.deepcopy(self.valid_result),
            self.schema,
            self.save_path,
            input_fn=lambda _prompt: "y",
        )
        with self.save_path.open("r", encoding="utf-8") as file:
            parsed = json.load(file)
        self.assertEqual(parsed["player"]["name"], "Eirik")

    def test_evaluation_mode_never_touches_persistent_save(self) -> None:
        save_before = (
            create_player.SAVE_PATH.read_bytes()
            if create_player.SAVE_PATH.exists()
            else None
        )
        provider = SimpleNamespace(provider="mock", model="mock-model")

        for arguments in (["--test"], ["--test-case", "6"]):
            with self.subTest(arguments=arguments):
                with (
                    patch.object(sys, "argv", ["create_player.py", *arguments]),
                    patch.object(
                        create_player,
                        "create_llm_client",
                        return_value=provider,
                    ),
                    patch.object(create_player, "run_test_mode", return_value=0),
                    patch.object(create_player, "load_current_save") as load_save,
                    patch.object(
                        create_player,
                        "confirm_and_commit_player",
                    ) as commit,
                ):
                    self.assertEqual(create_player.main(), 0)
                    load_save.assert_not_called()
                    commit.assert_not_called()

        save_after = (
            create_player.SAVE_PATH.read_bytes()
            if create_player.SAVE_PATH.exists()
            else None
        )
        self.assertEqual(save_after, save_before)


if __name__ == "__main__":
    unittest.main()
