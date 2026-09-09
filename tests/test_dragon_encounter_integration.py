"""D3-D PostgreSQL orchestration and API integration tests (offline)."""

from __future__ import annotations

import asyncio
import copy
import json
import unittest
import uuid
from typing import Any
from unittest.mock import patch

from sqlalchemy import delete, func, select

from api.app import create_app
from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    DragonEvent,
    InteractionEvent,
    Npc,
    NpcMemory,
    NpcRelationship,
    Player,
    PlayerDragonBond,
    PlayerState,
)
from database.persistence import PostgresPersistenceAdapter
from dragon.candidate_runtime import commit_new_dragon_encounter


async def asgi_request(
    application: Any,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    messages: list[dict[str, object]] = []
    sent = False
    request_body = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else b""
    )

    async def receive() -> dict[str, object]:
        nonlocal sent
        if not sent:
            sent = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }
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
            "headers": (
                [(b"content-type", b"application/json")]
                if request_body
                else []
            ),
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


class StubProvider:
    provider = "offline-test"
    model = "offline-test"

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[str] = []

    def create_structured_output(self, *, schema_name: str, **_: Any) -> str:
        self.calls.append(schema_name)
        return json.dumps(self.output, ensure_ascii=False)


class RejectingProvider:
    provider = "offline-test"
    model = "offline-test"

    def create_structured_output(self, **_: Any) -> str:
        raise AssertionError("Dragon Candidate provider must not be called.")


def action(
    family: str,
    text: str,
    *,
    target: str | None = None,
    destination: str | None = None,
    direction: str | None = None,
    intent: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    return {
        "action_family": family,
        "action": text,
        "target": target,
        "destination": destination,
        "direction": direction,
        "intent": intent,
        "method": method,
        "explicit_goal": None,
        "needs_clarification": False,
    }


def dragon_candidate(name: str = "Mossveil") -> dict[str, Any]:
    return {
        "name": name,
        "appearance": {
            "description": "A lean green dragon watches between ancient trees.",
            "distinctive_features": ["pale eyes", "fern-like neck ridges"],
        },
        "personality_traits": ["observant", "reserved"],
        "physical_tendency": "medium_balanced",
        "behavioral_tendency": "cautious",
        "ecological_flavor": "It moves quietly beneath the forest canopy.",
    }


class DragonEncounterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine()
        cls.session_factory = create_session_factory(cls.engine)
        cls.persistence = PostgresPersistenceAdapter(cls.session_factory)
        cls.player_id = f"test_d3d_player_{uuid.uuid4().hex}"
        cls.persistence.ensure_player(
            player_id=cls.player_id,
            name="D3-D Test Player",
            species="human",
            occupation=None,
            background=None,
            traits=[],
        )
        cls.persistence.upsert_player_state(
            player_id=cls.player_id,
            current_location="whispering_woods",
            inventory=[],
            goals=[],
            identity_context={},
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup_runtime_data()
        with cls.session_factory.begin() as session:
            session.execute(
                delete(PlayerState).where(PlayerState.player_id == cls.player_id)
            )
            session.execute(delete(Player).where(Player.player_id == cls.player_id))
        cls.engine.dispose()

    @classmethod
    def _cleanup_runtime_data(cls) -> None:
        with cls.session_factory.begin() as session:
            dragon_ids = list(
                session.scalars(
                    select(DragonEvent.dragon_id).where(
                        DragonEvent.player_id == cls.player_id
                    )
                ).all()
            )
            if dragon_ids:
                session.execute(
                    delete(PlayerDragonBond).where(
                        PlayerDragonBond.dragon_id.in_(dragon_ids)
                    )
                )
            session.execute(
                delete(DragonEvent).where(DragonEvent.player_id == cls.player_id)
            )
            if dragon_ids:
                session.execute(delete(Dragon).where(Dragon.dragon_id.in_(dragon_ids)))
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.player_id == cls.player_id
                )
            )

    def setUp(self) -> None:
        self._cleanup_runtime_data()
        self.persistence.upsert_player_state(
            player_id=self.player_id,
            current_location="whispering_woods",
            inventory=[],
            goals=[],
        )
        self.protected_counts = self._protected_counts()
        self.production_player_state = copy.deepcopy(
            self.persistence.get_player_state("player_001")
        )

    def tearDown(self) -> None:
        self._cleanup_runtime_data()
        self.assertEqual(self._protected_counts(), self.protected_counts)
        self.assertEqual(
            self.persistence.get_player_state("player_001"),
            self.production_player_state,
        )

    def _protected_counts(self) -> dict[str, int]:
        with self.session_factory() as session:
            return {
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model)
                )
                for model in (Npc, NpcMemory, NpcRelationship, PlayerDragonBond)
            }

    def _execute(
        self,
        player_input: str,
        structured_action: dict[str, Any],
        *,
        roll: float,
        candidate_provider: Any | None = None,
    ) -> tuple[dict[str, Any], StubProvider, Any]:
        action_provider = StubProvider(structured_action)
        dragon_provider = candidate_provider or RejectingProvider()
        application = create_app(
            action_provider_client=action_provider,  # type: ignore[arg-type]
            dragon_provider_client=dragon_provider,  # type: ignore[arg-type]
            dragon_encounter_roll=roll,
            persistence_adapter=self.persistence,
        )
        status, payload = asyncio.run(
            asgi_request(
                application,
                "/api/action/execute",
                method="POST",
                body={
                    "player_id": self.player_id,
                    "player_input": player_input,
                },
            )
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(action_provider.calls, ["free_action_interpretation"])
        return payload, action_provider, dragon_provider

    def _search_action(self) -> dict[str, Any]:
        return action(
            "observe_search",
            "深入森林寻找龙",
            target="龙",
            intent="寻找龙",
        )

    def _dragon_count(self) -> int:
        with self.session_factory() as session:
            return session.scalar(select(func.count()).select_from(Dragon))

    def test_case_1_ordinary_drink_is_none_and_creates_no_dragon(self) -> None:
        before = self._dragon_count()
        payload, _, _ = self._execute(
            "我在酒馆喝一杯。",
            action("rest_wait", "在酒馆喝酒"),
            roll=1.0,
        )
        self.assertEqual(payload["dragon_encounter"]["outcome"], "none")
        self.assertIsNone(payload["dragon_encounter"]["dragon"])
        self.assertEqual(self._dragon_count(), before)

    def test_case_2_fixed_low_roll_returns_trace_without_dragon(self) -> None:
        before = self._dragon_count()
        payload, _, _ = self._execute(
            "我深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=0.0,
        )
        self.assertEqual(payload["dragon_encounter"]["outcome"], "trace")
        self.assertTrue(payload["dragon_encounter"]["is_final"])
        self.assertEqual(self._dragon_count(), before)

    def test_case_3_high_roll_commits_and_finalizes_new_dragon(self) -> None:
        dragon_provider = StubProvider(dragon_candidate())
        provisional_seen = False

        def commit_after_provisional(**kwargs: Any) -> dict[str, Any]:
            nonlocal provisional_seen
            source = self.persistence.get_interaction_event(
                kwargs["source_interaction_event_id"]
            )
            persisted_decision = source["event_payload"][
                "dragon_encounter_decision"
            ]
            provisional_seen = (
                persisted_decision["is_final"] is False
                and persisted_decision["requires_new_dragon"] is True
                and persisted_decision["dragon_id"] is None
            )
            return commit_new_dragon_encounter(**kwargs)

        with patch(
            "api.app.commit_new_dragon_encounter",
            side_effect=commit_after_provisional,
        ):
            payload, _, _ = self._execute(
                "我深入 Whispering Woods 寻找龙。",
                self._search_action(),
                roll=0.75,
                candidate_provider=dragon_provider,
            )
        encounter = payload["dragon_encounter"]
        self.assertTrue(provisional_seen)
        self.assertEqual(encounter["outcome"], "sighting")
        self.assertTrue(encounter["is_final"])
        self.assertEqual(encounter["source"], "generated")
        self.assertEqual(dragon_provider.calls, ["dragon_candidate"])
        source = self.persistence.get_interaction_event(payload["source_event_id"])
        self.assertEqual(
            source["event_payload"]["dragon_encounter_decision"]["dragon_id"],
            encounter["dragon_id"],
        )

    def test_case_4_same_location_reuses_existing_dragon(self) -> None:
        first_provider = StubProvider(dragon_candidate("Mossveil"))
        first, _, _ = self._execute(
            "我深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=0.75,
            candidate_provider=first_provider,
        )
        count_after_first = self._dragon_count()
        second, _, _ = self._execute(
            "我继续在 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=1.0,
        )
        self.assertEqual(second["dragon_encounter"]["source"], "existing")
        self.assertEqual(
            second["dragon_encounter"]["dragon_id"],
            first["dragon_encounter"]["dragon_id"],
        )
        self.assertEqual(self._dragon_count(), count_after_first)

    def test_case_5_blocked_dragon_ride_has_no_encounter(self) -> None:
        before = self._dragon_count()
        payload, _, _ = self._execute(
            "我要骑我的龙去 Stormcliff。",
            action(
                "travel",
                "骑我的龙去 Stormcliff",
                target="我的龙",
                destination="Stormcliff",
                intent="骑龙前往 Stormcliff",
                method="骑我的龙",
            ),
            roll=1.0,
        )
        self.assertEqual(payload["resolution"]["status"], "blocked")
        self.assertEqual(payload["dragon_encounter"]["outcome"], "none")
        self.assertEqual(self._dragon_count(), before)

    def test_case_6_open_exploration_can_encounter_without_new_location(self) -> None:
        dragon_provider = StubProvider(dragon_candidate("Northwind"))
        before_location = self.persistence.get_player_state(self.player_id)[
            "current_location"
        ]
        payload, _, _ = self._execute(
            "我往北探索并寻找龙。",
            action(
                "explore",
                "往北探索",
                direction="北",
                intent="寻找龙",
            ),
            roll=1.0,
            candidate_provider=dragon_provider,
        )
        self.assertEqual(payload["resolution"]["effect_scope"], "narrative_only")
        self.assertEqual(payload["dragon_encounter"]["source"], "generated")
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["current_location"],
            before_location,
        )

    def test_case_7_recent_history_penalty_uses_persisted_source_events(self) -> None:
        first, _, _ = self._execute(
            "我深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=0.0,
        )
        second, _, _ = self._execute(
            "我继续深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=0.0,
        )
        self.assertEqual(first["dragon_encounter"]["context_score"], 8)
        self.assertEqual(second["dragon_encounter"]["context_score"], 8)
        history = self.persistence.list_recent_dragon_encounter_decisions(
            self.player_id,
            location_id="whispering_woods",
        )
        self.assertEqual(len(history), 2)

        dragon_provider = StubProvider(dragon_candidate("Historywing"))
        sighting, _, _ = self._execute(
            "我继续深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=0.5,
            candidate_provider=dragon_provider,
        )
        after_sighting, _, _ = self._execute(
            "我再次深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=0.0,
        )
        self.assertEqual(sighting["dragon_encounter"]["outcome"], "sighting")
        self.assertEqual(sighting["dragon_encounter"]["context_score"], 8)
        self.assertEqual(after_sighting["dragon_encounter"]["context_score"], 7)

    def test_case_8_world_reads_back_committed_nearby_dragons(self) -> None:
        production_location = self.production_player_state["current_location"]
        self.persistence.upsert_player_state(
            player_id=self.player_id,
            current_location=production_location,
            inventory=[],
            goals=[],
        )
        dragon_provider = StubProvider(dragon_candidate("Mossveil"))
        encounter, _, _ = self._execute(
            "我深入 Whispering Woods 寻找龙。",
            self._search_action(),
            roll=1.0,
            candidate_provider=dragon_provider,
        )
        application = create_app(persistence_adapter=self.persistence)
        status, world = asyncio.run(asgi_request(application, "/api/world"))
        self.assertEqual(status, 200)
        self.assertEqual(len(world["nearby_dragons"]), 1)
        self.assertEqual(
            world["nearby_dragons"][0]["dragon_id"],
            encounter["dragon_encounter"]["dragon_id"],
        )


if __name__ == "__main__":
    unittest.main()
