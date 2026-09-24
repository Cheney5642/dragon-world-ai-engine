"""Offline smoke tests for the read-only Dragon World Web API endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sqlalchemy import delete, func, select

from api.app import _grounded_action_feedback, app, create_app
from core.action_pipeline import ActionPipelineResources
from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    InteractionEvent,
    Npc,
    NpcMemory,
    NpcRelationship,
    Player,
    PlayerDragonBond,
    PlayerState,
)
from database.persistence import PostgresPersistenceAdapter
from scripts import execute_action, interpret_action, validate_action
from scripts.interpret_action import SAVE_PATH


def file_hash(path: Path = SAVE_PATH) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


async def asgi_request(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    application: Any = app,
) -> tuple[int, dict[str, Any]]:
    """Issue a minimal HTTP request directly to the ASGI app."""

    messages: list[dict[str, object]] = []
    request_sent = False
    request_body = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else b""
    )

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": (
            [(b"content-type", b"application/json")]
            if request_body
            else []
        ),
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    await application(scope, receive, send)
    status = next(
        int(message["status"])
        for message in messages
        if message["type"] == "http.response.start"
    )
    body = b"".join(
        bytes(message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(body.decode("utf-8"))


class FakeStructuredProvider:
    provider = "offline-test"
    model = "offline-test"

    def __init__(self, outputs: dict[str, dict[str, Any]]) -> None:
        self.outputs = outputs
        self.calls: list[str] = []

    def create_structured_output(self, *, schema_name: str, **_: Any) -> str:
        self.calls.append(schema_name)
        return json.dumps(self.outputs[schema_name], ensure_ascii=False)


def movement_resources(
    world_state: dict[str, Any], raw_input: str
) -> tuple[ActionPipelineResources, str]:
    current_id = world_state["player"]["current_location"]
    connections = world_state["locations"][current_id]["connections"]
    target_id = connections[0]
    target_location = world_state["locations"][target_id]
    action_result = {
        "raw_input": raw_input,
        "action_kind": "movement",
        "steps": [
            {
                "verb": "go",
                "target": {
                    "type": "location",
                    "id": target_id,
                    "name": target_location["name"],
                },
                "goal": f"travel to {target_location['name']}",
                "method": None,
            }
        ],
        "speech": None,
        "claimed_facts": [],
        "requires_world_check": True,
        "needs_clarification": False,
    }
    assessment = validate_action.build_deterministic_assessment(
        action_result,
        world_state,
    )
    validation_result = {
        "overall_status": assessment.recommended_overall_status,
        "checks": assessment.checks,
        "missing_requirements": assessment.missing_requirements,
        "conflicts": assessment.conflicts,
        "requires_npc_decision": assessment.requires_npc_decision,
        "requires_further_resolution": assessment.requires_further_resolution,
        "validated_interpretation": "The movement intent is ready for execution.",
    }
    provider = FakeStructuredProvider(
        {
            "action_interpretation_result": action_result,
            "world_validation_result": validation_result,
        }
    )
    return (
        ActionPipelineResources(
            provider_client=provider,  # type: ignore[arg-type]
            action_prompt="offline action prompt",
            action_schema=interpret_action.load_schema(),
            validation_prompt="offline validation prompt",
            validation_schema=validate_action.load_validation_schema(),
            execution_schema=execute_action.load_execution_schema(),
        ),
        target_id,
    )


class WebApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.save_path = Path(self.directory.name) / "world.json"
        seed_path = Path(__file__).resolve().parents[1] / "data" / "world_seed.json"
        world = json.loads(seed_path.read_text(encoding="utf-8"))
        world["player"]["species"] = "human"
        self.save_path.write_text(json.dumps(world), encoding="utf-8")
        self.fixture_app = create_app(self.save_path)

    def test_health(self) -> None:
        status, payload = asyncio.run(asgi_request("/health"))
        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {"status": "ok", "service": "dragon-world-api"},
        )

    def test_world_summary_is_read_only_and_public(self) -> None:
        before = file_hash(self.save_path)
        status, payload = asyncio.run(asgi_request("/api/world", application=self.fixture_app))
        after = file_hash(self.save_path)

        self.assertEqual(status, 200)
        self.assertEqual(before, after)
        self.assertEqual(
            set(payload),
            {
                "player",
                "world",
                "current_location",
                "nearby_npcs",
                "nearby_dragons",
                "riding",
            },
        )
        self.assertEqual(
            set(payload["player"]),
            {
                "id",
                "player_id",
                "name",
                "display_name",
                "species",
                "occupation",
                "current_location",
                "goals",
                "inventory",
                "identity_initialized",
                "identity_label",
                "identity_summary",
            },
        )
        self.assertEqual(
            set(payload["world"]),
            {"name", "day", "hour", "weather"},
        )
        self.assertEqual(
            set(payload["current_location"]),
            {"id", "name", "type", "description"},
        )
        for npc in payload["nearby_npcs"]:
            self.assertEqual(
                set(npc),
                {"id", "name", "species", "occupation"},
            )
        for dragon in payload["nearby_dragons"]:
            self.assertEqual(
                set(dragon),
                {
                    "dragon_id",
                    "name",
                    "appearance",
                    "personality_traits",
                    "behavior_state",
                    "taming_state",
                    "location",
                    "player_relationship",
                },
            )

        public_non_dragon_payload = {
            key: value for key, value in payload.items() if key != "nearby_dragons"
        }
        serialized = json.dumps(
            public_non_dragon_payload,
            ensure_ascii=False,
        ).casefold()
        for forbidden in (
            "api_key",
            "system prompt",
            "memories",
            "relationships",
            "knowledge",
            "current_goal",
            "personality",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_action_endpoints_accept_raw_input_not_mutations(self) -> None:
        schema = app.openapi()
        request_ref = schema["paths"]["/api/action/commit"]["post"][
            "requestBody"
        ]["content"]["application/json"]["schema"]["$ref"]
        request_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_name]
        self.assertEqual(set(request_schema["properties"]), {"input"})
        self.assertFalse(request_schema["additionalProperties"])
        self.assertNotIn("proposed_mutations", request_schema["properties"])

    def test_action_preview_runs_three_layers_and_is_read_only(self) -> None:
        world_state = interpret_action.load_current_world(self.save_path)
        raw_input = "Go to the connected location."
        resources, target_id = movement_resources(world_state, raw_input)
        before = file_hash(self.save_path)
        fixture_app = self.fixture_app
        with patch("api.app._load_resources", return_value=resources):
            status, payload = asyncio.run(
                asgi_request(
                    "/api/action/preview",
                    method="POST",
                    body={"input": raw_input},
                    application=fixture_app,
                )
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["pipeline_status"], "ready")
        self.assertEqual(
            payload["execution_plan"]["proposed_mutations"][0]["new_value"],
            target_id,
        )
        self.assertEqual(before, file_hash(self.save_path))

    def test_action_commit_revalidates_raw_input_on_a_temporary_save(self) -> None:
        production_before = file_hash()
        with tempfile.TemporaryDirectory() as directory:
            temporary_save = Path(directory) / "current_world.json"
            shutil.copy2(self.save_path, temporary_save)
            world_state = interpret_action.load_current_world(temporary_save)
            raw_input = "Go to the connected location."
            resources, target_id = movement_resources(world_state, raw_input)
            temporary_app = create_app(temporary_save)

            with patch("api.app._load_resources", return_value=resources):
                status, payload = asyncio.run(
                    asgi_request(
                        "/api/action/commit",
                        method="POST",
                        body={"input": raw_input},
                        application=temporary_app,
                    )
                )

            committed_world = interpret_action.load_current_world(temporary_save)
            self.assertEqual(status, 200)
            self.assertTrue(payload["committed"])
            self.assertEqual(payload["pipeline_status"], "committed")
            self.assertEqual(
                committed_world["player"]["current_location"],
                target_id,
            )

        self.assertEqual(production_before, file_hash())


class FreeActionExecuteApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine()
        cls.session_factory = create_session_factory(cls.engine)
        cls.persistence = PostgresPersistenceAdapter(cls.session_factory)
        cls.player_id = f"test_d2d1_{uuid.uuid4().hex}"
        cls.persistence.ensure_player(
            player_id=cls.player_id,
            name="D2-D1 Test Player",
            species="human",
            occupation=None,
            background=None,
            traits=[],
        )
        cls.persistence.upsert_player_state(
            player_id=cls.player_id,
            current_location="skeld_village",
            inventory=[],
            goals=[],
            identity_context={},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        with cls.session_factory.begin() as session:
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.player_id == cls.player_id
                )
            )
            session.execute(
                delete(PlayerState).where(PlayerState.player_id == cls.player_id)
            )
            session.execute(delete(Player).where(Player.player_id == cls.player_id))
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.session_factory.begin() as session:
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.player_id == self.player_id
                )
            )
        self.persistence.upsert_player_state(
            player_id=self.player_id,
            current_location="skeld_village",
            inventory=[],
            goals=[],
        )
        self.protected_counts = self._protected_counts()

    def tearDown(self) -> None:
        self.assertEqual(self._protected_counts(), self.protected_counts)

    def _protected_counts(self) -> dict[str, int]:
        with self.session_factory() as session:
            return {
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model)
                )
                for model in (
                    Npc,
                    NpcMemory,
                    NpcRelationship,
                    Dragon,
                    PlayerDragonBond,
                )
            }

    def _execute(
        self,
        player_input: str,
        structured_action: dict[str, Any],
    ) -> tuple[int, dict[str, Any], FakeStructuredProvider]:
        provider = FakeStructuredProvider(
            {"free_action_interpretation": structured_action}
        )
        application = create_app(
            action_provider_client=provider,  # type: ignore[arg-type]
            persistence_adapter=self.persistence,
        )
        status, payload = asyncio.run(
            asgi_request(
                "/api/action/execute",
                method="POST",
                body={
                    "player_id": self.player_id,
                    "player_input": player_input,
                },
                application=application,
            )
        )
        return status, payload, provider

    def test_case_1_known_travel_uses_d2_and_updates_postgres(self) -> None:
        status, payload, provider = self._execute(
            "我要去 Whispering Woods。",
            {
                "action_family": "travel",
                "action": "前往 Whispering Woods",
                "target": None,
                "destination": "Whispering Woods",
                "direction": None,
                "intent": None,
                "method": None,
                "explicit_goal": None,
                "needs_clarification": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(provider.calls, ["free_action_interpretation"])
        self.assertEqual(payload["resolution"]["reason_code"], "known_travel")
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["current_location"],
            "whispering_woods",
        )

    def test_case_2_explicit_goal_updates_postgres(self) -> None:
        status, payload, provider = self._execute(
            "我的目标是找到一枚龙蛋。",
            {
                "action_family": "other",
                "action": "声明长期目标",
                "target": None,
                "destination": None,
                "direction": None,
                "intent": "找到一枚龙蛋",
                "method": None,
                "explicit_goal": {
                    "operation": "add",
                    "goal": "找到一枚龙蛋",
                },
                "needs_clarification": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(provider.calls, ["free_action_interpretation"])
        self.assertEqual(
            payload["structured_action"]["explicit_goal"],
            {"operation": "add", "goal": "找到一枚龙蛋"},
        )
        self.assertEqual(payload["resolution"]["reason_code"], "goal_added")
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["goals"],
            ["找到一枚龙蛋"],
        )

    def test_case_3_ungrounded_dragon_ride_is_blocked(self) -> None:
        status, payload, provider = self._execute(
            "我要骑我的龙去 Stormcliff。",
            {
                "action_family": "travel",
                "action": "骑我的龙去 Stormcliff",
                "target": "我的龙",
                "destination": "Stormcliff",
                "direction": None,
                "intent": "骑龙前往 Stormcliff",
                "method": "骑我的龙",
                "explicit_goal": None,
                "needs_clarification": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(provider.calls, ["free_action_interpretation"])
        self.assertEqual(payload["resolution"]["status"], "blocked")
        self.assertEqual(payload["resolution"]["domain_route"], "dragon")
        self.assertEqual(
            payload["resolution"]["reason_code"],
            "dragon_riding_not_grounded",
        )
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["current_location"],
            "skeld_village",
        )

    def test_case_4_known_npc_actions_use_general_domain_route(self) -> None:
        for family, verb in (("interact", "对话"), ("conflict", "杀掉")):
            with self.subTest(family=family):
                status, payload, provider = self._execute(
                    f"我要和 Bjorn {verb}。",
                    {
                        "action_family": family,
                        "action": f"{verb} Bjorn",
                        "target": "Bjorn",
                        "destination": None,
                        "direction": None,
                        "intent": None,
                        "method": None,
                        "explicit_goal": None,
                        "needs_clarification": False,
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(provider.calls, ["free_action_interpretation"])
                self.assertEqual(payload["resolution"]["status"], "partial")
                self.assertEqual(
                    payload["resolution"]["effect_scope"], "domain_route"
                )
                self.assertEqual(payload["resolution"]["domain_route"], "npc")
                self.assertEqual(
                    payload["resolution"]["reason_code"], "npc_runtime_required"
                )
                self.assertEqual(payload["resolution"]["state_changes"], {})
                self.assertEqual(
                    self.persistence.get_player_state(self.player_id)[
                        "current_location"
                    ],
                    "skeld_village",
                )

    def test_grounded_note_feedback_uses_real_dragon_traits(self) -> None:
        persistence = SimpleNamespace(
            list_dragons_at_location=lambda _location: [{
                "name": "Kael",
                "age_stage": "juvenile",
                "temperament_traits": ["胆小", "好奇"],
            }]
        )
        message = _grounded_action_feedback(
            player_input="我掏出笔记本记录了 Kael 的性格",
            structured_action={
                "action_family": "other",
                "action": "记录 Kael 的性格",
                "target": "Kael",
            },
            resolution={
                "status": "success",
                "reason_code": "narrative_only",
            },
            player_location="skeld_village",
            world_skeleton={
                "locations": {
                    "skeld_village": {
                        "name": "Skeld",
                        "description": "寒冷的海港村落",
                    }
                }
            },
            persistence=persistence,
        )
        self.assertIn("凯尔", message)
        self.assertIn("胆小、好奇", message)
        self.assertIn("笔记本", message)

    def test_buying_fish_returns_grounded_feedback_and_food_inventory(self) -> None:
        status, payload, provider = self._execute(
            "我在斯凯尔德买一条鱼。",
            {
                "action_family": "create_trade",
                "action": "在斯凯尔德买一条鱼",
                "target": "鱼",
                "destination": None,
                "direction": None,
                "intent": None,
                "method": None,
                "explicit_goal": None,
                "needs_clarification": False,
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(provider.calls, ["free_action_interpretation"])
        self.assertEqual(payload["resolution"]["reason_code"], "food_bought")
        self.assertIn("鲜鱼", payload["player_message"])
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["inventory"][0]["food_kind"],
            "fish",
        )

    def test_ordinary_action_feedback_is_contextual_without_meta_copy(self) -> None:
        persistence = SimpleNamespace(list_dragons_at_location=lambda _location: [])
        message = _grounded_action_feedback(
            player_input="我点起一盏小灯。",
            structured_action={
                "action_family": "other",
                "action": "点起一盏小灯",
                "target": "小灯",
            },
            resolution={
                "status": "success",
                "reason_code": "narrative_only",
            },
            player_location="skeld_village",
            world_skeleton={
                "locations": {
                    "skeld_village": {
                        "name": "Skeld",
                        "description": "寒风掠过港湾，渔船在潮声中轻轻摇晃。",
                    }
                }
            },
            persistence=persistence,
        )
        self.assertIn("点起一盏小灯", message)
        self.assertIn("寒风掠过港湾", message)
        self.assertNotIn("周围的人与事会记住真实发生的部分", message)


if __name__ == "__main__":
    unittest.main()
