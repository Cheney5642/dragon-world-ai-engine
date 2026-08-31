"""Offline API tests for Step 6.6-A NPC API Integration v0.1."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from api.app import create_app
from llm import LLMProviderError
from npc.memory import (
    MEMORY_STORE_PATH,
    load_memory_store,
    write_memory_store_atomically,
)
from npc.relationship_store import (
    RELATIONSHIP_STORE_PATH,
    load_relationship_store,
    write_relationship_store_atomically,
)
from scripts.commit_npc_memory import build_case_interaction_event, load_memory_case
from scripts.commit_npc_relationship import load_relationship_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"
RUNTIME_CASES_PATH = PROJECT_ROOT / "data" / "npc_interaction_runtime_test_cases.json"
MEMORY_FIXTURES_PATH = PROJECT_ROOT / "data" / "npc_memory_retrieval_test_cases.json"
RELATIONSHIP_FIXTURES_PATH = (
    PROJECT_ROOT / "data" / "npc_relationship_response_test_cases.json"
)
PROTECTED_PATHS = (
    SEED_PATH,
    SAVE_PATH,
    MEMORY_STORE_PATH,
    RELATIONSHIP_STORE_PATH,
    PROFILES_PATH,
)


def file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


async def asgi_request(
    application: Any,
    path: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    request_sent = False
    request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    await application(scope, receive, send)
    status = next(
        int(message["status"])
        for message in messages
        if message["type"] == "http.response.start"
    )
    payload = b"".join(
        bytes(message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(payload.decode("utf-8"))


class MockProvider:
    provider = "offline-api-test"
    model = "offline-api-test"

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.response = response
        self.failure = failure
        self.calls = 0

    def create_structured_output(self, **_: Any) -> str:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if self.response is None:
            raise AssertionError("Mock response was not configured.")
        return json.dumps(self.response, ensure_ascii=False)


class NpcApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        cls.seed["player"]["name"] = "Eirik"
        cls.seed["player"]["species"] = "human"
        cls.seed["player"]["occupation"] = "blacksmith apprentice"
        cls.seed["player"]["current_location"] = "skeld_village"

        runtime_document = json.loads(RUNTIME_CASES_PATH.read_text(encoding="utf-8"))
        cls.runtime_cases = {
            case["id"]: case for case in runtime_document["cases"]
        }
        memory_document = json.loads(
            MEMORY_FIXTURES_PATH.read_text(encoding="utf-8")
        )
        cls.memory_fixtures = {
            memory["memory_id"]: memory
            for memory in memory_document["memory_fixtures"]
        }
        relationship_document = json.loads(
            RELATIONSHIP_FIXTURES_PATH.read_text(encoding="utf-8")
        )
        cls.relationship_fixtures = relationship_document["relationship_fixtures"]
        cls.protected_hashes = {path: file_hash(path) for path in PROTECTED_PATHS}

    @classmethod
    def tearDownClass(cls) -> None:
        changed = [
            path
            for path, digest in cls.protected_hashes.items()
            if file_hash(path) != digest
        ]
        if changed:
            raise AssertionError(
                "NPC API tests changed formal Persistent State: "
                + ", ".join(str(path) for path in changed)
            )

    def _environment(
        self,
        *,
        response: dict[str, Any] | None = None,
        failure: Exception | None = None,
        memory_store: dict[str, Any] | None = None,
        relationship_store: dict[str, Any] | None = None,
        player_location: str = "skeld_village",
    ) -> tuple[Any, MockProvider, Path, Path, Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        save_path = root / "current_world.json"
        memory_path = root / "npc_memories.json"
        relationship_path = root / "npc_relationships.json"

        world = copy.deepcopy(self.seed)
        world["player"]["current_location"] = player_location
        save_path.write_text(
            json.dumps(world, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_memory_store_atomically(
            copy.deepcopy(memory_store or {"version": "0.1", "memories": []}),
            memory_path,
        )
        write_relationship_store_atomically(
            copy.deepcopy(
                relationship_store or {"version": "0.1", "relationships": []}
            ),
            relationship_path,
        )
        provider = MockProvider(copy.deepcopy(response), failure=failure)
        application = create_app(
            save_path,
            memory_store_path=memory_path,
            relationship_store_path=relationship_path,
            npc_provider_client=provider,
        )
        return application, provider, save_path, memory_path, relationship_path

    def _case_environment(
        self,
        case_id: str,
        *,
        player_location: str = "skeld_village",
    ) -> tuple[Any, MockProvider, Path, Path, Path, dict[str, Any]]:
        case = self.runtime_cases[case_id]
        memory_store = {
            "version": "0.1",
            "memories": [
                copy.deepcopy(self.memory_fixtures[memory_id])
                for memory_id in case["memory_fixture_ids"]
            ],
        }
        relationship_store = copy.deepcopy(
            self.relationship_fixtures[case["relationship_fixture"]]
        )
        environment = self._environment(
            response=case["mock_response"],
            memory_store=memory_store,
            relationship_store=relationship_store,
            player_location=player_location,
        )
        return (*environment, case)

    @staticmethod
    def _interact_body(case: dict[str, Any]) -> dict[str, str]:
        return {
            "npc_id": case["npc_id"],
            "player_id": case["player_id"],
            "utterance": case["player_utterance"],
        }

    def test_01_knowledge_question(self) -> None:
        app, provider, *_, case = self._case_environment("case_1")
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["interaction_available"])
        self.assertIn("铁匠", payload["npc_response"]["speech"])
        self.assertFalse(payload["mutation_plan"]["has_any_mutation"])
        self.assertEqual(provider.calls, 1)

    def test_02_memory_recall(self) -> None:
        app, provider, *_, case = self._case_environment("case_2")
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        self.assertIn("记得", payload["npc_response"]["speech"])
        self.assertFalse(payload["mutation_plan"]["memory"]["candidate"])
        self.assertEqual(provider.calls, 1)

    def test_03_relationship_aware_response(self) -> None:
        app, provider, *_, case = self._case_environment("case_3")
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        self.assertIn("担心", payload["npc_response"]["speech"])
        self.assertEqual(provider.calls, 1)

    def test_04_false_claim_remains_grounded(self) -> None:
        app, _, *_, case = self._case_environment("case_4")
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["npc_response"]["response_type"], "disagreement")
        self.assertTrue(payload["interaction_event"]["player_claims"])
        self.assertFalse(payload["mutation_plan"]["has_any_mutation"])

    def test_05_memory_candidate_preview(self) -> None:
        app, _, *_, case = self._case_environment("case_5")
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        memory = payload["mutation_plan"]["memory"]
        self.assertTrue(memory["candidate"])
        self.assertTrue(memory["commit_available"])
        self.assertEqual(memory["preview"]["memory_type"], "player_intention")

    def test_06_relationship_candidate_preview(self) -> None:
        app, _, *_, case = self._case_environment("case_6")
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        relationship = payload["mutation_plan"]["relationship"]
        self.assertEqual(relationship["signal"], "potential_positive")
        self.assertEqual(relationship["preview"]["decision"], "no_change")
        self.assertFalse(relationship["commit_available"])

    def test_07_both_candidates_are_routed(self) -> None:
        response = copy.deepcopy(self.runtime_cases["case_5"]["mock_response"])
        app, provider, *_ = self._environment(response=response)
        body = {
            "npc_id": "npc_astrid",
            "player_id": "player_001",
            "utterance": "我明天准备一个人去 Stormcliff，谢谢你，我愿意帮助你。",
        }
        status, payload = asyncio.run(asgi_request(app, "/api/npc/interact", body))
        plan = payload["mutation_plan"]
        self.assertEqual(status, 200)
        self.assertTrue(plan["memory"]["candidate"])
        self.assertEqual(plan["relationship"]["signal"], "potential_positive")
        self.assertIsNotNone(plan["memory"]["preview"])
        self.assertIsNotNone(plan["relationship"]["preview"])
        self.assertEqual(provider.calls, 1)

    def test_08_different_location_is_business_result_without_llm(self) -> None:
        app, provider, *_, case = self._case_environment(
            "case_7",
            player_location="stormcliff",
        )
        status, payload = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["interaction_available"])
        self.assertIsNone(payload["npc_response"])
        self.assertIsNone(payload["interaction_event"])
        self.assertIsNone(payload["mutation_plan"])
        self.assertEqual(provider.calls, 0)

    def test_09_memory_commit(self) -> None:
        app, provider, _, memory_path, _ = self._environment()
        event = build_case_interaction_event(load_memory_case(6))
        status, payload = asyncio.run(
            asgi_request(
                app,
                "/api/npc/memory/commit",
                {"interaction_event": event},
            )
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["committed"])
        self.assertEqual(payload["domain"], "memory")
        self.assertEqual(len(load_memory_store(memory_path)["memories"]), 1)
        self.assertEqual(provider.calls, 0)

    def test_10_memory_duplicate_is_business_rejection(self) -> None:
        app, _, _, memory_path, _ = self._environment()
        event = build_case_interaction_event(load_memory_case(6))
        first, _ = asyncio.run(
            asgi_request(app, "/api/npc/memory/commit", {"interaction_event": event})
        )
        second, payload = asyncio.run(
            asgi_request(app, "/api/npc/memory/commit", {"interaction_event": event})
        )
        self.assertEqual(first, 200)
        self.assertEqual(second, 409)
        self.assertEqual(payload["detail"]["error_type"], "business_rejection")
        self.assertEqual(payload["detail"]["code"], "duplicate_event")
        self.assertEqual(len(load_memory_store(memory_path)["memories"]), 1)

    def test_11_relationship_commit(self) -> None:
        app, provider, _, _, relationship_path = self._environment()
        event = load_relationship_case(4)["interaction_event"]
        status, payload = asyncio.run(
            asgi_request(
                app,
                "/api/npc/relationship/commit",
                {"interaction_event": event},
            )
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["committed"])
        record = load_relationship_store(relationship_path)["relationships"][0]
        self.assertEqual((record["familiarity"], record["trust"]), (2, 1))
        self.assertEqual(provider.calls, 0)

    def test_12_relationship_duplicate_is_business_rejection(self) -> None:
        app, _, _, _, relationship_path = self._environment()
        event = load_relationship_case(4)["interaction_event"]
        first, _ = asyncio.run(
            asgi_request(
                app,
                "/api/npc/relationship/commit",
                {"interaction_event": event},
            )
        )
        second, payload = asyncio.run(
            asgi_request(
                app,
                "/api/npc/relationship/commit",
                {"interaction_event": event},
            )
        )
        self.assertEqual(first, 200)
        self.assertEqual(second, 409)
        self.assertEqual(payload["detail"]["code"], "duplicate_event")
        record = load_relationship_store(relationship_path)["relationships"][0]
        self.assertEqual((record["familiarity"], record["trust"]), (2, 1))

    def test_13_invalid_npc(self) -> None:
        response = self.runtime_cases["case_1"]["mock_response"]
        app, provider, *_ = self._environment(response=response)
        status, payload = asyncio.run(
            asgi_request(
                app,
                "/api/npc/interact",
                {
                    "npc_id": "npc_unknown",
                    "player_id": "player_001",
                    "utterance": "你好。",
                },
            )
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"]["code"], "invalid_npc")
        self.assertEqual(provider.calls, 0)

    def test_14_invalid_player(self) -> None:
        response = self.runtime_cases["case_1"]["mock_response"]
        app, provider, *_ = self._environment(response=response)
        status, payload = asyncio.run(
            asgi_request(
                app,
                "/api/npc/interact",
                {
                    "npc_id": "npc_astrid",
                    "player_id": "player_999",
                    "utterance": "你好。",
                },
            )
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"]["code"], "invalid_player")
        self.assertEqual(provider.calls, 0)

    def test_15_commit_endpoints_never_call_llm(self) -> None:
        provider_failure = LLMProviderError("Commit must not call the provider.")
        app, provider, *_ = self._environment(failure=provider_failure)
        event = build_case_interaction_event(load_memory_case(6))
        status, _ = asyncio.run(
            asgi_request(
                app,
                "/api/npc/memory/commit",
                {"interaction_event": event},
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(provider.calls, 0)

    def test_16_interaction_preview_changes_no_persistent_store(self) -> None:
        app, _, save_path, memory_path, relationship_path, case = (
            self._case_environment("case_5")
        )
        before = tuple(
            file_hash(path) for path in (save_path, memory_path, relationship_path)
        )
        status, _ = asyncio.run(
            asgi_request(app, "/api/npc/interact", self._interact_body(case))
        )
        after = tuple(
            file_hash(path) for path in (save_path, memory_path, relationship_path)
        )
        self.assertEqual(status, 200)
        self.assertEqual(before, after)

    def test_17_api_contract_forbids_direct_mutation_values(self) -> None:
        app, *_ = self._environment()
        openapi = app.openapi()
        interact_ref = openapi["paths"]["/api/npc/interact"]["post"][
            "requestBody"
        ]["content"]["application/json"]["schema"]["$ref"]
        interact_schema = openapi["components"]["schemas"][
            interact_ref.rsplit("/", 1)[-1]
        ]
        self.assertEqual(
            set(interact_schema["properties"]),
            {"npc_id", "player_id", "utterance"},
        )
        commit_ref = openapi["paths"]["/api/npc/relationship/commit"]["post"][
            "requestBody"
        ]["content"]["application/json"]["schema"]["$ref"]
        commit_schema = openapi["components"]["schemas"][
            commit_ref.rsplit("/", 1)[-1]
        ]
        self.assertEqual(set(commit_schema["properties"]), {"interaction_event"})
        serialized = json.dumps(commit_schema).casefold()
        for forbidden in ("trust", "familiarity", "attitude", "memory_record"):
            self.assertNotIn(forbidden, serialized)

    def test_18_provider_failure_is_system_error(self) -> None:
        app, provider, *_ = self._environment(
            failure=LLMProviderError("offline provider failure")
        )
        status, payload = asyncio.run(
            asgi_request(
                app,
                "/api/npc/interact",
                {
                    "npc_id": "npc_astrid",
                    "player_id": "player_001",
                    "utterance": "你好。",
                },
            )
        )
        self.assertEqual(status, 502)
        self.assertEqual(payload["detail"]["error_type"], "system_error")
        self.assertEqual(payload["detail"]["code"], "provider_failure")
        self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
