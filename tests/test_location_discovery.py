"""Targeted D5 vertical-slice validation; no real LLM calls."""

from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import delete, func, select

from api.app import create_app
from core.free_action_resolution import commit_action_resolution, load_world_skeleton
from core.location_discovery import (
    DYNAMIC_LOCATION_REGISTRY_STATE_ID,
    LocationDiscoveryError,
    generate_location_candidate,
    ground_location_candidate,
    is_location_discovery_eligible,
    merge_location_registries,
    stable_location_id_for_source,
)
from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    InteractionEvent,
    Npc,
    Player,
    PlayerDragonBond,
    PlayerState,
    WorldStateEntry,
)
from database.persistence import PostgresPersistenceAdapter


def action(
    family: str,
    text: str,
    *,
    target: str | None = None,
    destination: str | None = None,
    direction: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    return {
        "action_family": family,
        "action": text,
        "target": target,
        "destination": destination,
        "direction": direction,
        "intent": intent,
        "method": None,
        "explicit_goal": None,
        "needs_clarification": False,
    }


def resolution(reason: str = "open_exploration_recorded") -> dict[str, Any]:
    return {
        "status": "success",
        "effect_scope": "narrative_only",
        "reason_code": reason,
        "domain_route": None,
        "state_changes": {},
    }


class StubProvider:
    def __init__(self, action_result: dict[str, Any], candidate: dict[str, Any]) -> None:
        self.action_result = action_result
        self.candidate = candidate
        self.calls: list[str] = []

    def create_structured_output(self, **kwargs: Any) -> str:
        schema_name = kwargs["schema_name"]
        self.calls.append(schema_name)
        result = (
            self.action_result
            if schema_name == "free_action_interpretation"
            else self.candidate
        )
        return json.dumps(result, ensure_ascii=False)


async def asgi_request(
    application: Any,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    messages: list[dict[str, object]] = []
    sent = False
    request_body = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")

    async def receive() -> dict[str, object]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": request_body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await application(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        },
        receive,
        send,
    )
    status = next(
        int(message["status"])
        for message in messages
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        bytes(message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(response_body.decode("utf-8"))


class LocationDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine()
        self.session_factory = create_session_factory(self.engine)
        self.persistence = PostgresPersistenceAdapter(self.session_factory)
        self.token = uuid.uuid4().hex
        self.player_id = f"test_d5_{self.token}"
        self.event_id = f"test_d5_event_{self.token}"
        self.skeleton = load_world_skeleton()
        self.explore = action(
            "explore",
            "沿着北侧探索未知区域",
            direction="北侧",
            intent="寻找从未去过的地方",
        )
        self.candidate = {
            "name": f"测试风痕岭{self.token[:6]}",
            "location_type": "ridge",
            "short_description": "灰白岩脊伸向寒雾笼罩的北方。",
            "environment_tags": ["寒风", "岩脊"],
            "discovery_reason": "沿北侧地势继续探索时发现了隐蔽山路。",
        }
        with self.session_factory.begin() as session:
            session.add(
                Player(
                    player_id=self.player_id,
                    name="D5 Test",
                    species="human",
                    occupation=None,
                    background=None,
                    traits=[],
                )
            )
            session.add(
                PlayerState(
                    player_id=self.player_id,
                    current_location="skeld_village",
                    inventory=[],
                    goals=[],
                )
            )

    def tearDown(self) -> None:
        with self.session_factory.begin() as session:
            registry = session.get(
                WorldStateEntry,
                DYNAMIC_LOCATION_REGISTRY_STATE_ID,
            )
            if registry is not None:
                value = copy.deepcopy(registry.state_value)
                locations = value.get("locations", {})
                value["locations"] = {
                    location_id: location
                    for location_id, location in locations.items()
                    if self.token[:6] not in str(location.get("name", ""))
                }
                if value["locations"]:
                    registry.state_value = value
                else:
                    session.delete(registry)
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.player_id == self.player_id
                )
            )
            session.execute(
                delete(PlayerState).where(PlayerState.player_id == self.player_id)
            )
            session.execute(delete(Player).where(Player.player_id == self.player_id))
        self.engine.dispose()

    def _source_event(self) -> dict[str, Any]:
        return commit_action_resolution(
            player_id=self.player_id,
            player_input="沿着北侧探索未知区域",
            structured_action=self.explore,
            persistence=self.persistence,
            world_skeleton=self.skeleton,
            event_id=self.event_id,
        )

    def _grounded(self) -> dict[str, Any]:
        return ground_location_candidate(
            candidate=self.candidate,
            structured_action=self.explore,
            resolution=resolution(),
            source_interaction_event_id=self.event_id,
            current_location_id="skeld_village",
            locations=self.skeleton["locations"],
        )

    def _discover(self) -> dict[str, Any]:
        self._source_event()
        return self.persistence.commit_location_discovery(
            player_id=self.player_id,
            source_interaction_event_id=self.event_id,
            location=self._grounded(),
        )

    def test_case_1_known_travel_is_not_discovery_eligible(self) -> None:
        structured = action(
            "travel",
            "前往 Stormcliff",
            destination="Stormcliff",
        )
        self.assertFalse(
            is_location_discovery_eligible(structured, resolution("known_travel"))
        )
        self.assertEqual(self.persistence.get_dynamic_location_registry()["locations"], {})

    def test_case_2_open_exploration_generates_grounded_candidate(self) -> None:
        provider = StubProvider(self.explore, self.candidate)
        generated = generate_location_candidate(
            structured_action=self.explore,
            current_location_id="skeld_village",
            locations=self.skeleton["locations"],
            provider_client=provider,  # type: ignore[arg-type]
        )
        grounded = ground_location_candidate(
            candidate=generated,
            structured_action=self.explore,
            resolution=resolution(),
            source_interaction_event_id=self.event_id,
            current_location_id="skeld_village",
            locations=self.skeleton["locations"],
        )
        self.assertEqual(provider.calls, ["location_candidate"])
        self.assertEqual(grounded["location_id"], stable_location_id_for_source(self.event_id))
        self.assertEqual(grounded["connections"], ["skeld_village"])

    def test_case_3_dynamic_location_is_persisted(self) -> None:
        result = self._discover()
        registry = self.persistence.get_dynamic_location_registry()
        source = self.persistence.get_interaction_event(self.event_id)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(
            registry["locations"][result["location"]["location_id"]]["name"],
            self.candidate["name"],
        )
        self.assertEqual(
            source["event_payload"]["structured_action"],
            self.explore,
        )
        self.assertEqual(
            source["event_payload"]["location_discovery"]["location_id"],
            result["location"]["location_id"],
        )

    def test_case_4_registry_readback_survives_new_adapter(self) -> None:
        result = self._discover()
        reloaded = PostgresPersistenceAdapter(self.session_factory)
        self.assertIn(
            result["location"]["location_id"],
            reloaded.get_dynamic_location_registry()["locations"],
        )

    def test_cases_5_and_6_dynamic_location_is_travelable(self) -> None:
        result = self._discover()
        location = result["location"]
        travel = action("travel", "前往新地点", destination=location["name"])
        committed = commit_action_resolution(
            player_id=self.player_id,
            player_input=f"我要去 {location['name']}。",
            structured_action=travel,
            persistence=self.persistence,
            event_id=f"{self.event_id}_travel",
        )
        self.assertEqual(committed["resolution"]["reason_code"], "known_travel")
        self.assertEqual(
            committed["player_state"]["current_location"],
            location["location_id"],
        )

    def test_case_7_no_npc_dragon_or_bond_is_created(self) -> None:
        with self.session_factory() as session:
            before = (
                session.scalar(select(func.count()).select_from(Npc)),
                session.scalar(select(func.count()).select_from(Dragon)),
                session.scalar(select(func.count()).select_from(PlayerDragonBond)),
            )
        self._discover()
        with self.session_factory() as session:
            after = (
                session.scalar(select(func.count()).select_from(Npc)),
                session.scalar(select(func.count()).select_from(Dragon)),
                session.scalar(select(func.count()).select_from(PlayerDragonBond)),
            )
        self.assertEqual(after, before)

    def test_case_8_same_source_retry_is_idempotent(self) -> None:
        first = self._discover()
        second = self.persistence.commit_location_discovery(
            player_id=self.player_id,
            source_interaction_event_id=self.event_id,
            location=self._grounded(),
        )
        self.assertEqual(first["location"]["location_id"], second["location"]["location_id"])
        self.assertEqual(second["status"], "already_applied")
        self.assertEqual(len(self.persistence.get_dynamic_location_registry()["locations"]), 1)

    def test_api_execute_and_world_readback_use_dynamic_registry(self) -> None:
        provider = StubProvider(self.explore, self.candidate)
        application = create_app(
            action_provider_client=provider,  # type: ignore[arg-type]
            location_provider_client=provider,  # type: ignore[arg-type]
            dragon_encounter_roll=0.0,
            persistence_adapter=self.persistence,
        )
        status, payload = asyncio.run(
            asgi_request(
                application,
                "/api/action/execute",
                method="POST",
                body={"player_id": self.player_id, "player_input": "沿北侧探索未知区域"},
            )
        )
        self.assertEqual(status, 200)
        discovery = payload["location_discovery"]
        self.assertIsNotNone(discovery)
        self.assertEqual(
            provider.calls,
            ["free_action_interpretation", "location_candidate"],
        )
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["current_location"],
            "skeld_village",
        )

        travel = action("travel", "前往新地点", destination=discovery["name"])
        commit_action_resolution(
            player_id=self.player_id,
            player_input=f"我要去 {discovery['name']}。",
            structured_action=travel,
            persistence=self.persistence,
            event_id=f"{self.event_id}_api_travel",
        )
        seed = copy.deepcopy(self.skeleton)
        seed["player"]["id"] = self.player_id
        seed["npcs"] = {}
        with tempfile.TemporaryDirectory() as temporary_directory:
            seed_path = Path(temporary_directory) / "world_seed.json"
            seed_path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
            with patch("api.app.WORLD_SEED_PATH", seed_path):
                world_status, world = asyncio.run(
                    asgi_request(application, "/api/world")
                )
        self.assertEqual(world_status, 200)
        self.assertEqual(world["current_location"]["id"], discovery["location_id"])
        self.assertEqual(world["current_location"]["name"], discovery["name"])

    def test_dragon_search_and_invalid_candidate_fail_closed(self) -> None:
        dragon_search = action(
            "explore",
            "沿北方寻找龙",
            direction="北方",
            intent="寻找龙",
        )
        self.assertFalse(
            is_location_discovery_eligible(dragon_search, resolution())
        )
        invalid = dict(self.candidate)
        invalid["short_description"] = "这里居住着一群巨龙。"
        with self.assertRaises(LocationDiscoveryError):
            ground_location_candidate(
                candidate=invalid,
                structured_action=self.explore,
                resolution=resolution(),
                source_interaction_event_id=self.event_id,
                current_location_id="skeld_village",
                locations=self.skeleton["locations"],
            )


if __name__ == "__main__":
    unittest.main()
