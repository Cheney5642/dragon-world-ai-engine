"""D4-D browser/API Dragon interaction integration tests (offline)."""

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
from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    DragonEvent,
    InteractionEvent,
    Player,
    PlayerDragonBond,
    PlayerState,
)
from database.persistence import PostgresPersistenceAdapter


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
    target: str | None = "D4D Dragon",
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


class DragonInteractionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine()
        cls.session_factory = create_session_factory(cls.engine)
        cls.persistence = PostgresPersistenceAdapter(cls.session_factory)
        cls.token = uuid.uuid4().hex
        cls.player_id = f"test_d4d_player_{cls.token}"
        cls.dragon_id = f"test_d4d_dragon_{cls.token}"
        cls.other_dragon_id = f"test_d4d_dragon_other_{cls.token}"
        cls.source_prefix = f"test_d4d_source_{cls.token}_"
        cls.formal_before = cls._formal_snapshot()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup_all()
        assert cls._formal_snapshot() == cls.formal_before
        with cls.session_factory() as session:
            assert session.scalar(
                select(func.count()).select_from(Player).where(
                    Player.player_id.like("test_d4d_%")
                )
            ) == 0
            assert session.scalar(
                select(func.count()).select_from(Dragon).where(
                    Dragon.dragon_id.like("test_d4d_%")
                )
            ) == 0
            assert session.scalar(
                select(func.count()).select_from(InteractionEvent).where(
                    InteractionEvent.event_id.like("test_d4d_%")
                )
            ) == 0
        cls.engine.dispose()

    @classmethod
    def _formal_snapshot(cls) -> dict[str, Any]:
        with cls.session_factory() as session:
            player_state = session.get(PlayerState, "player_001")
            kael = session.scalar(select(Dragon).where(Dragon.name == "Kael"))
            return {
                "player_state": None if player_state is None else {
                    "current_location": player_state.current_location,
                    "inventory": copy.deepcopy(player_state.inventory),
                    "goals": copy.deepcopy(player_state.goals),
                    "identity_context": copy.deepcopy(player_state.identity_context),
                },
                "kael": None if kael is None else {
                    "dragon_id": kael.dragon_id,
                    "current_location": kael.current_location,
                    "taming_state": kael.taming_state,
                    "behavior_state": kael.behavior_state,
                },
                "dragons": session.scalar(select(func.count()).select_from(Dragon)),
                "events": session.scalar(select(func.count()).select_from(DragonEvent)),
                "bonds": session.scalar(
                    select(func.count()).select_from(PlayerDragonBond)
                ),
            }

    @classmethod
    def _cleanup_all(cls) -> None:
        player_ids = [cls.player_id]
        dragon_ids = [cls.dragon_id, cls.other_dragon_id]
        with cls.session_factory.begin() as session:
            session.execute(
                delete(PlayerDragonBond).where(
                    (PlayerDragonBond.player_id.in_(player_ids))
                    | (PlayerDragonBond.dragon_id.in_(dragon_ids))
                )
            )
            session.execute(
                delete(DragonEvent).where(
                    (DragonEvent.player_id.in_(player_ids))
                    | (DragonEvent.dragon_id.in_(dragon_ids))
                )
            )
            session.execute(
                delete(InteractionEvent).where(
                    (InteractionEvent.player_id.in_(player_ids))
                    | (InteractionEvent.event_id.like(f"{cls.source_prefix}%"))
                )
            )
            session.execute(
                delete(PlayerState).where(PlayerState.player_id.in_(player_ids))
            )
            session.execute(delete(Dragon).where(Dragon.dragon_id.in_(dragon_ids)))
            session.execute(delete(Player).where(Player.player_id.in_(player_ids)))

    def setUp(self) -> None:
        self._cleanup_all()
        self.persistence.ensure_player(
            player_id=self.player_id,
            name="D4-D Test Player",
            species="human",
            occupation=None,
            background=None,
            traits=[],
        )
        self.persistence.upsert_player_state(
            player_id=self.player_id,
            current_location="stormcliff",
            inventory=[],
            goals=[],
            identity_context={},
        )
        self._ensure_dragon(self.dragon_id)

    def tearDown(self) -> None:
        self._cleanup_all()

    def _ensure_dragon(
        self,
        dragon_id: str,
        *,
        name: str | None = None,
        location: str = "stormcliff",
        taming_state: str = "wild",
    ) -> None:
        with self.session_factory.begin() as session:
            session.add(
                Dragon(
                    dragon_id=dragon_id,
                    archetype_id="balanced_wild",
                    name=name or (
                        "D4D Dragon"
                        if dragon_id == self.dragon_id
                        else "Other D4D Dragon"
                    ),
                    sex=None,
                    age_stage="adult",
                    appearance={
                        "description": "测试龙",
                        "distinctive_features": [],
                    },
                    temperament_traits=["谨慎"],
                    current_location=location,
                    health_state="healthy",
                    energy=80,
                    hunger=20,
                    alertness=60,
                    behavior_state="watching",
                    taming_state=taming_state,
                )
            )

    def _seed_bond(
        self,
        familiarity: int,
        trust: int,
        fear: int,
        bond: int,
        *,
        riding_unlocked: bool = False,
    ) -> None:
        with self.session_factory.begin() as session:
            session.add(
                PlayerDragonBond(
                    player_id=self.player_id,
                    dragon_id=self.dragon_id,
                    familiarity=familiarity,
                    trust=trust,
                    fear=fear,
                    bond=bond,
                    riding_unlocked=riding_unlocked,
                    last_significant_event_id=None,
                )
            )

    def _set_dragon_state(self, state: str) -> None:
        with self.session_factory.begin() as session:
            dragon = session.get(Dragon, self.dragon_id)
            assert dragon is not None
            dragon.taming_state = state

    def _seed_history(self, interaction_type: str, category: str, index: int) -> None:
        source_id = f"{self.source_prefix}history_{index}"
        snapshot = {
            "familiarity": 0,
            "trust": 0,
            "fear": 0,
            "bond": 0,
            "taming_state": "wild",
        }
        payload = {
            "structured_action": action("interact", f"seed {interaction_type}"),
            "resolution": {
                "status": "partial",
                "effect_scope": "narrative_only",
                "reason_code": "narrative_only",
                "domain_route": None,
                "state_changes": {},
            },
            "world_effect": {},
            "dragon_interaction": {
                "dragon_id": self.dragon_id,
                "player_id": self.player_id,
                "source_interaction_event_id": source_id,
                "status": "success",
                "interaction_type": interaction_type,
                "dragon_reaction": "calm",
                "relationship_effect": "positive",
                "reason_code": "seeded_history",
                "positive_category": category,
                "anti_farming": "full",
                "applied_deltas": {
                    "familiarity": 1,
                    "trust": 1,
                    "fear": 0,
                    "bond": 0,
                },
                "before": snapshot,
                "after": snapshot,
                "taming_transition": None,
                "significant_event_id": None,
                "positive_categories": [category],
                "riding_unlocked": False,
                "is_final": True,
            },
        }
        self.persistence.insert_interaction_event(
            {
                "event_id": source_id,
                "event_type": "free_world_action",
                "player_id": self.player_id,
                "world_context": {
                    "world_day": 1,
                    "world_hour": 8,
                    "location_id": "stormcliff",
                },
                "player_utterance": f"seed {interaction_type}",
                "player_claims": [],
                "event_payload": payload,
            }
        )

    def _execute(
        self,
        player_input: str,
        structured_action: dict[str, Any],
        *,
        roll: float = 0.0,
    ) -> dict[str, Any]:
        action_provider = StubProvider(structured_action)
        application = create_app(
            action_provider_client=action_provider,  # type: ignore[arg-type]
            dragon_provider_client=RejectingProvider(),  # type: ignore[arg-type]
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
        return payload

    def _interaction_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = self.persistence.get_interaction_event(payload["source_event_id"])
        self.assertIsNotNone(event)
        return event  # type: ignore[return-value]

    def _dragon_event_count(self) -> int:
        with self.session_factory() as session:
            return session.scalar(
                select(func.count()).select_from(DragonEvent).where(
                    DragonEvent.player_id == self.player_id
                )
            )

    def test_case_01_dragon_action_enters_d4_without_d3(self) -> None:
        payload = self._execute(
            "我慢慢靠近 D4D Dragon。",
            action("interact", "慢慢靠近 D4D Dragon", method="小心靠近"),
        )
        self.assertEqual(
            payload["dragon_interaction"]["interaction_type"], "approach"
        )
        self.assertEqual(
            payload["dragon_encounter"]["reason_code"],
            "dragon_interaction_handled",
        )
        source = self._interaction_event(payload)["event_payload"]
        self.assertIn("dragon_interaction", source)
        self.assertNotIn("dragon_encounter_decision", source)

    def test_case_02_regular_travel_does_not_enter_d4(self) -> None:
        payload = self._execute(
            "我要去 Skeld。",
            action(
                "travel",
                "前往 Skeld",
                target=None,
                destination="Skeld",
            ),
        )
        self.assertIsNone(payload["dragon_interaction"])
        self.assertEqual(payload["resolution"]["reason_code"], "known_travel")

    def test_case_03_dragon_search_stays_in_d3(self) -> None:
        payload = self._execute(
            "我搜索附近有没有龙。",
            action(
                "observe_search",
                "搜索附近有没有龙",
                target="龙",
                intent="寻找龙",
            ),
        )
        self.assertIsNone(payload["dragon_interaction"])
        self.assertIn(payload["dragon_encounter"]["outcome"], {"none", "trace"})
        self.assertIn(
            "dragon_encounter_decision",
            self._interaction_event(payload)["event_payload"],
        )

    def test_case_04_observe_creates_no_bond_row(self) -> None:
        payload = self._execute(
            "我远远观察 D4D Dragon。",
            action("observe_search", "远远观察 D4D Dragon"),
        )
        self.assertEqual(
            payload["dragon_interaction"]["interaction_type"], "observe"
        )
        self.assertIsNone(
            self.persistence.get_player_dragon_bond(
                player_id=self.player_id,
                dragon_id=self.dragon_id,
            )
        )

    def test_case_05_cautious_approach_persists_familiarity(self) -> None:
        payload = self._execute(
            "我慢慢靠近 D4D Dragon。",
            action("interact", "慢慢靠近 D4D Dragon", method="小心靠近"),
        )
        self.assertEqual(
            payload["dragon_interaction"]["applied_deltas"]["familiarity"],
            1,
        )
        bond = self.persistence.get_player_dragon_bond(
            player_id=self.player_id,
            dragon_id=self.dragon_id,
        )
        self.assertEqual(bond["familiarity"], 1)

    def test_case_06_calm_communication_persists_category(self) -> None:
        payload = self._execute(
            "我平静地和 D4D Dragon 说话。",
            action(
                "interact",
                "平静地和 D4D Dragon 说话",
                method="轻声说话",
            ),
        )
        interaction = payload["dragon_interaction"]
        self.assertEqual(interaction["positive_category"], "communication")
        self.assertEqual(interaction["bond_state"]["trust"], 1)

    def test_case_07_repeated_communication_applies_anti_farming(self) -> None:
        communicate = action(
            "interact",
            "平静地和 D4D Dragon 说话",
            method="轻声说话",
        )
        first = self._execute("第一次交流。", communicate)
        second = self._execute("第二次交流。", communicate)
        third = self._execute("第三次交流。", communicate)
        self.assertEqual(first["dragon_interaction"]["anti_farming"], "full")
        self.assertEqual(
            second["dragon_interaction"]["anti_farming"],
            "familiarity_only",
        )
        self.assertEqual(third["dragon_interaction"]["anti_farming"], "zero")
        self.assertIn("没有新的反应", third["player_message"])

    def test_case_08_positive_interaction_transitions_wild_to_tolerant(self) -> None:
        self._seed_bond(1, 1, 0, 0)
        payload = self._execute(
            "我平静地和 D4D Dragon 说话。",
            action(
                "interact",
                "平静地和 D4D Dragon 说话",
                method="轻声说话",
            ),
        )
        self.assertEqual(
            payload["dragon_interaction"]["taming_transition"],
            {"from": "wild", "to": "tolerant"},
        )
        self.assertIn("开始容忍", payload["player_message"])

    def test_case_09_diverse_interaction_transitions_tolerant_to_bonding(
        self,
    ) -> None:
        self._set_dragon_state("tolerant")
        self._seed_bond(2, 1, 0, 1)
        self._seed_history("approach", "close_presence", 1)
        payload = self._execute(
            "我平静地和 D4D Dragon 说话。",
            action(
                "interact",
                "平静地和 D4D Dragon 说话",
                method="轻声说话",
            ),
        )
        self.assertEqual(
            payload["dragon_interaction"]["taming_transition"],
            {"from": "tolerant", "to": "bonding"},
        )

    def test_case_10_final_positive_interaction_tames_and_events_once(self) -> None:
        self._set_dragon_state("bonding")
        self._seed_bond(3, 2, 0, 2)
        self._seed_history("approach", "close_presence", 1)
        self._seed_history("communicate", "communication", 2)
        before = self._dragon_event_count()
        payload = self._execute(
            "我轻轻触碰 D4D Dragon。",
            action(
                "interact",
                "轻轻触碰 D4D Dragon",
                method="小心触碰",
            ),
        )
        self.assertEqual(
            payload["dragon_interaction"]["taming_transition"],
            {"from": "bonding", "to": "tamed"},
        )
        self.assertEqual(self._dragon_event_count(), before + 1)
        self.assertIn("已经接受了你", payload["player_message"])

    def test_case_11_tamed_ride_remains_blocked_without_unlock(self) -> None:
        self._set_dragon_state("tamed")
        self._seed_bond(4, 3, 0, 2, riding_unlocked=False)
        payload = self._execute(
            "我要骑 D4D Dragon。",
            action(
                "travel",
                "骑 D4D Dragon",
                target="D4D Dragon",
                intent="骑乘",
            ),
        )
        interaction = payload["dragon_interaction"]
        self.assertEqual(interaction["status"], "blocked")
        self.assertEqual(
            interaction["reason_code"],
            "dragon_riding_not_unlocked",
        )
        self.assertFalse(interaction["bond_state"]["riding_unlocked"])

    def test_case_12_different_location_is_blocked_without_movement(self) -> None:
        with self.session_factory.begin() as session:
            dragon = session.get(Dragon, self.dragon_id)
            assert dragon is not None
            dragon.current_location = "old_ruins"
        payload = self._execute(
            "我观察远处的 Dragon。",
            action(
                "observe_search",
                "观察远处的 Dragon",
                target=self.dragon_id,
            ),
        )
        self.assertEqual(payload["dragon_interaction"]["status"], "blocked")
        self.assertEqual(
            payload["dragon_interaction"]["reason_code"],
            "dragon_not_in_interaction_range",
        )
        self.assertEqual(
            self.persistence.get_player_state(self.player_id)["current_location"],
            "stormcliff",
        )

    def test_case_13_unknown_dragon_target_fails_closed(self) -> None:
        payload = self._execute(
            "我慢慢靠近 Dragon Veyra。",
            action(
                "interact",
                "慢慢靠近 Dragon Veyra",
                target="Veyra",
                method="小心靠近",
            ),
        )
        self.assertEqual(payload["dragon_interaction"]["status"], "blocked")
        self.assertEqual(
            payload["dragon_interaction"]["reason_code"],
            "dragon_target_not_grounded",
        )

    def test_case_14_ambiguous_dragon_target_fails_closed(self) -> None:
        self._ensure_dragon(self.other_dragon_id)
        payload = self._execute(
            "我慢慢靠近那条龙。",
            action(
                "interact",
                "慢慢靠近那条龙",
                target="那条龙",
                method="小心靠近",
            ),
        )
        self.assertEqual(payload["dragon_interaction"]["status"], "blocked")
        self.assertEqual(
            payload["dragon_interaction"]["reason_code"],
            "dragon_target_ambiguous",
        )

    def test_case_15_same_source_retry_is_already_applied(self) -> None:
        payload = self._execute(
            "我慢慢靠近 D4D Dragon。",
            action("interact", "慢慢靠近 D4D Dragon", method="小心靠近"),
        )
        retry = self.persistence.commit_dragon_interaction(
            player_id=self.player_id,
            dragon_id=self.dragon_id,
            source_interaction_event_id=payload["source_event_id"],
        )
        self.assertEqual(retry["status"], "already_applied")
        self.assertEqual(
            retry["bond_state"],
            payload["dragon_interaction"]["bond_state"],
        )

    def test_case_16_source_d2_d3_payload_is_preserved(self) -> None:
        source_id = f"{self.source_prefix}audit"
        original = {
            "structured_action": action(
                "interact",
                "慢慢靠近 D4D Dragon",
                method="小心靠近",
            ),
            "resolution": {
                "status": "success",
                "effect_scope": "narrative_only",
                "reason_code": "narrative_only",
                "domain_route": None,
                "state_changes": {},
            },
            "world_effect": {},
            "dragon_encounter_decision": {"outcome": "trace"},
        }
        self.persistence.insert_interaction_event(
            {
                "event_id": source_id,
                "event_type": "free_world_action",
                "player_id": self.player_id,
                "world_context": {
                    "world_day": 1,
                    "world_hour": 8,
                    "location_id": "stormcliff",
                },
                "player_utterance": "慢慢靠近 D4D Dragon",
                "player_claims": [],
                "event_payload": original,
            }
        )
        self.persistence.commit_dragon_interaction(
            player_id=self.player_id,
            dragon_id=self.dragon_id,
            source_interaction_event_id=source_id,
        )
        event = self.persistence.get_interaction_event(source_id)
        self.assertIsNotNone(event)
        payload = event["event_payload"]
        for key, value in original.items():
            self.assertEqual(payload[key], value)
        self.assertIn("dragon_interaction", payload)

    def test_case_17_api_world_reads_back_player_relationship(self) -> None:
        self._execute(
            "我慢慢靠近 D4D Dragon。",
            action("interact", "慢慢靠近 D4D Dragon", method="小心靠近"),
        )
        seed = json.loads(
            Path("data/world_seed.json").read_text(encoding="utf-8")
        )
        seed["player"]["id"] = self.player_id
        with tempfile.TemporaryDirectory() as temp_dir:
            seed_path = Path(temp_dir) / "world_seed.json"
            seed_path.write_text(
                json.dumps(seed, ensure_ascii=False),
                encoding="utf-8",
            )
            application = create_app(persistence_adapter=self.persistence)
            with patch("api.app.WORLD_SEED_PATH", seed_path):
                status, world = asyncio.run(
                    asgi_request(application, "/api/world")
                )
        self.assertEqual(status, 200, world)
        dragon = next(
            item
            for item in world["nearby_dragons"]
            if item["dragon_id"] == self.dragon_id
        )
        self.assertEqual(dragon["player_relationship"]["familiarity"], 1)

    def test_case_18_response_exposes_only_committed_effect(self) -> None:
        payload = self._execute(
            "我慢慢靠近 D4D Dragon。",
            action("interact", "慢慢靠近 D4D Dragon", method="小心靠近"),
        )
        interaction = payload["dragon_interaction"]
        self.assertNotIn("state_changes", interaction)
        self.assertNotIn("next_taming_state_preview", interaction)
        bond = self.persistence.get_player_dragon_bond(
            player_id=self.player_id,
            dragon_id=self.dragon_id,
        )
        self.assertEqual(interaction["bond_state"], bond)
        self.assertEqual(
            interaction["after"]["familiarity"],
            bond["familiarity"],
        )
