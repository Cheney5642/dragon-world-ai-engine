"""Offline integration tests for Runtime Interaction Event → Memory Commit Bridge."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from npc.memory import (
    DuplicateMemoryError,
    MemoryStoreError,
    NoPersistentMemoryRequiredError,
    NpcMemoryError,
    build_memory_preview,
    commit_memory_preview,
    confirm_and_commit_memory,
    initialize_memory_store,
    load_memory_store,
)
from npc.interaction_event import NpcInteractionEventError
from scripts.commit_npc_memory import (
    build_case_interaction_event,
    load_event_source,
    load_memory_case,
    load_runtime_interaction_event,
)
from scripts.inspect_interaction_event import _build_from_case, write_event_output
from scripts.reset_npc_memories import reset_memory_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMAL_STORE_PATH = PROJECT_ROOT / "data" / "saves" / "npc_memories.json"
PROTECTED_PATHS = (
    PROJECT_ROOT / "data" / "world_seed.json",
    PROJECT_ROOT / "data" / "saves" / "current_world.json",
    PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json",
    PROJECT_ROOT / "prompts" / "npc_response_system.md",
    PROJECT_ROOT / "schemas" / "npc_profile.schema.json",
    PROJECT_ROOT / "schemas" / "npc_context.schema.json",
    PROJECT_ROOT / "schemas" / "npc_response.schema.json",
    PROJECT_ROOT / "schemas" / "npc_interaction_event.schema.json",
    PROJECT_ROOT / "npc" / "context_builder.py",
    PROJECT_ROOT / "npc" / "response_runtime.py",
    PROJECT_ROOT / "npc" / "interaction_event.py",
    FORMAL_STORE_PATH,
)


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NpcMemoryBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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
                "Formal Store, World State, or Frozen Baseline changed during Bridge tests: "
                + ", ".join(str(path) for path in changed)
            )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.store_path = temporary_root / "npc_memories.json"
        self.event_path = temporary_root / "runtime_event.json"
        initialize_memory_store(self.store_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def export_runtime_case(self, case_number: int) -> dict:
        _, event = _build_from_case(case_number)
        write_event_output(event, self.event_path)
        return load_runtime_interaction_event(self.event_path)

    def test_golden_case_source_mode_still_builds_preview(self) -> None:
        args = SimpleNamespace(case=2, event_file=None)
        source_mode, event = load_event_source(args)
        memory = build_memory_preview(event)
        self.assertEqual(source_mode, "golden_fixture")
        self.assertEqual(memory["memory_type"], "player_intention")

    def test_runtime_event_file_generates_preview(self) -> None:
        store_before = self.store_path.read_bytes()
        event = self.export_runtime_case(6)
        args = SimpleNamespace(case=None, event_file=self.event_path)
        source_mode, loaded_event = load_event_source(args)
        memory = build_memory_preview(loaded_event)
        self.assertEqual(source_mode, "runtime_event")
        self.assertEqual(loaded_event, event)
        self.assertEqual(memory["memory_type"], "player_intention")
        self.assertIn("intends to go to Stormcliff alone tomorrow", memory["content"])
        self.assertEqual(memory["epistemic_status"], "reported_by_player")
        self.assertEqual(self.store_path.read_bytes(), store_before)

    def test_runtime_event_confirm_commits_to_temporary_store(self) -> None:
        event = self.export_runtime_case(6)
        memory = build_memory_preview(event)
        result = confirm_and_commit_memory(
            memory,
            self.store_path,
            input_fn=lambda _prompt: "yes",
        )
        store = load_memory_store(self.store_path)
        self.assertEqual(result, memory)
        self.assertEqual(store["memories"], [memory])

    def test_runtime_event_duplicate_is_rejected(self) -> None:
        event = self.export_runtime_case(6)
        first = build_memory_preview(event)
        commit_memory_preview(first, self.store_path)
        second = build_memory_preview(event)
        before = self.store_path.read_bytes()
        with self.assertRaisesRegex(DuplicateMemoryError, "already exists"):
            commit_memory_preview(second, self.store_path)
        self.assertEqual(self.store_path.read_bytes(), before)
        self.assertEqual(len(load_memory_store(self.store_path)["memories"]), 1)

    def test_non_candidate_runtime_event_produces_no_memory(self) -> None:
        store_before = self.store_path.read_bytes()
        event = self.export_runtime_case(1)
        with self.assertRaisesRegex(
            NoPersistentMemoryRequiredError,
            "No persistent memory required",
        ):
            build_memory_preview(event)
        self.assertEqual(self.store_path.read_bytes(), store_before)

    def test_invalid_runtime_event_schema_is_rejected(self) -> None:
        self.event_path.write_text(
            json.dumps({"event_type": "npc_dialogue"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(NpcMemoryError, "invalid"):
            load_runtime_interaction_event(self.event_path)
        self.assertEqual(load_memory_store(self.store_path)["memories"], [])

    def test_runtime_event_cancel_does_not_write_store(self) -> None:
        event = self.export_runtime_case(6)
        memory = build_memory_preview(event)
        before = self.store_path.read_bytes()
        result = confirm_and_commit_memory(
            memory,
            self.store_path,
            input_fn=lambda _prompt: "n",
        )
        self.assertIsNone(result)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_reset_requires_confirmation_and_uses_temporary_store(self) -> None:
        event = build_case_interaction_event(load_memory_case(2))
        commit_memory_preview(build_memory_preview(event), self.store_path)
        before_unconfirmed = self.store_path.read_bytes()
        with self.assertRaisesRegex(MemoryStoreError, "requires --confirm"):
            reset_memory_store(self.store_path, confirmed=False)
        self.assertEqual(self.store_path.read_bytes(), before_unconfirmed)

        reset_store = reset_memory_store(self.store_path, confirmed=True)
        self.assertEqual(reset_store, {"version": "0.1", "memories": []})
        self.assertEqual(load_memory_store(self.store_path), reset_store)

    def test_event_export_cannot_replace_protected_state(self) -> None:
        _, event = _build_from_case(6)
        protected_path = PROJECT_ROOT / "data" / "world_seed.json"
        before = protected_path.read_bytes()
        with self.assertRaisesRegex(NpcInteractionEventError, "protected state"):
            write_event_output(event, protected_path)
        self.assertEqual(protected_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
