"""Offline smoke tests for the read-only Dragon World Web API endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from api.app import app, create_app
from core.action_pipeline import ActionPipelineResources
from scripts import execute_action, interpret_action, validate_action
from scripts.interpret_action import SAVE_PATH


def file_hash() -> str:
    return hashlib.sha256(SAVE_PATH.read_bytes()).hexdigest()


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

    def create_structured_output(self, *, schema_name: str, **_: Any) -> str:
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
    def test_health(self) -> None:
        status, payload = asyncio.run(asgi_request("/health"))
        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {"status": "ok", "service": "dragon-world-api"},
        )

    def test_world_summary_is_read_only_and_public(self) -> None:
        before = file_hash()
        status, payload = asyncio.run(asgi_request("/api/world"))
        after = file_hash()

        self.assertEqual(status, 200)
        self.assertEqual(before, after)
        self.assertEqual(
            set(payload),
            {"player", "world", "current_location", "nearby_npcs"},
        )
        self.assertEqual(
            set(payload["player"]),
            {
                "id",
                "name",
                "species",
                "occupation",
                "current_location",
                "goals",
                "inventory",
            },
        )
        self.assertEqual(
            set(payload["world"]),
            {"name", "day", "hour", "weather"},
        )
        self.assertEqual(
            set(payload["current_location"]),
            {"id", "name", "type"},
        )
        for npc in payload["nearby_npcs"]:
            self.assertEqual(
                set(npc),
                {"id", "name", "species", "occupation"},
            )

        serialized = json.dumps(payload, ensure_ascii=False).casefold()
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
        world_state = interpret_action.load_current_world()
        raw_input = "Go to the connected location."
        resources, target_id = movement_resources(world_state, raw_input)
        before = file_hash()
        with patch("api.app._load_resources", return_value=resources):
            status, payload = asyncio.run(
                asgi_request(
                    "/api/action/preview",
                    method="POST",
                    body={"input": raw_input},
                )
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["pipeline_status"], "ready")
        self.assertEqual(
            payload["execution_plan"]["proposed_mutations"][0]["new_value"],
            target_id,
        )
        self.assertEqual(before, file_hash())

    def test_action_commit_revalidates_raw_input_on_a_temporary_save(self) -> None:
        production_before = file_hash()
        with tempfile.TemporaryDirectory() as directory:
            temporary_save = Path(directory) / "current_world.json"
            shutil.copy2(SAVE_PATH, temporary_save)
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


if __name__ == "__main__":
    unittest.main()
