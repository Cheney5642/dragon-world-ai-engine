"""D6 Dragon Riding persistence and domain acceptance tests."""

from __future__ import annotations

import copy
import asyncio
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import delete, func, select

from api.app import _load_postgres_world, build_world_summary, create_app
from core.dragon_riding import (
    classify_riding_operation,
    commit_riding_action,
    route_grounded_riding_before_d2,
)
from database import create_database_engine, create_session_factory
from database.models import (
    Dragon,
    DragonEvent,
    InteractionEvent,
    Player,
    PlayerDragonBond,
    PlayerState,
    WorldStateEntry,
)
from database.persistence import PersistenceMappingError, PostgresPersistenceAdapter
from tests.test_dragon_encounter_integration import StubProvider, asgi_request
from multimodal.scene_renderer import DisabledSceneImageProvider
from tests.test_scene_renderer import StubImageProvider


def action(
    family: str,
    text: str,
    *,
    target: str | None = None,
    destination: str | None = None,
) -> dict[str, object]:
    return {
        "action_family": family,
        "action": text,
        "target": target,
        "destination": destination,
        "direction": None,
        "intent": text,
        "method": "骑乘" if family == "travel" else None,
        "explicit_goal": None,
        "needs_clarification": False,
    }


class DragonRidingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine()
        self.factory = create_session_factory(self.engine)
        self.persistence = PostgresPersistenceAdapter(self.factory)
        self.token = uuid.uuid4().hex
        self.player_id = f"test_d6_player_{self.token}"
        self.other_player_id = f"test_d6_other_{self.token}"
        self.dragon_id = f"test_d6_dragon_{self.token}"
        self.dragon_name = f"Testwing-{self.token[:8]}"
        with self.factory.begin() as session:
            session.add(
                Player(
                    player_id=self.player_id,
                    name="D6 Rider",
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
                    identity_context={},
                )
            )
            session.add(
                Player(
                    player_id=self.other_player_id,
                    name="D6 New Life",
                    species="human",
                    occupation=None,
                    background=None,
                    traits=[],
                )
            )
            session.add(
                PlayerState(
                    player_id=self.other_player_id,
                    current_location="skeld_village",
                    inventory=[],
                    goals=[],
                    identity_context={},
                )
            )
            session.add(
                Dragon(
                    dragon_id=self.dragon_id,
                    archetype_id="balanced_wild",
                    name=self.dragon_name,
                    sex=None,
                    age_stage="young_adult",
                    appearance={},
                    temperament_traits=["cautious"],
                    current_location="skeld_village",
                    health_state="healthy",
                    energy=70,
                    hunger=42,
                    alertness=68,
                    behavior_state="watching",
                    taming_state="tamed",
                )
            )
            session.add(
                PlayerDragonBond(
                    player_id=self.player_id,
                    dragon_id=self.dragon_id,
                    familiarity=5,
                    trust=5,
                    fear=0,
                    bond=3,
                    riding_unlocked=False,
                    last_significant_event_id=None,
                )
            )
            session.flush()
            session.add(
                DragonEvent(
                    event_id=f"test_d6_first_{self.token}",
                    event_type="dragon_first_encounter",
                    dragon_id=self.dragon_id,
                    player_id=self.player_id,
                    source_interaction_event_id=None,
                    world_day=1,
                    world_hour=8,
                    location_id="skeld_village",
                    milestone_key="first_encounter",
                    event_payload={},
                )
            )
            session.add(
                DragonEvent(
                    event_id=f"test_d6_tamed_{self.token}",
                    event_type="dragon_tamed",
                    dragon_id=self.dragon_id,
                    player_id=self.player_id,
                    source_interaction_event_id=None,
                    world_day=1,
                    world_hour=8,
                    location_id="skeld_village",
                    milestone_key="tamed",
                    event_payload={},
                )
            )

    def tearDown(self) -> None:
        with self.factory.begin() as session:
            session.execute(
                delete(WorldStateEntry).where(
                    WorldStateEntry.state_id.in_([
                        f"player.{self.player_id}.riding.v1",
                        f"player.{self.other_player_id}.riding.v1",
                    ])
                )
            )
            session.execute(
                delete(PlayerDragonBond).where(
                    PlayerDragonBond.player_id.in_(
                        [self.player_id, self.other_player_id]
                    )
                )
            )
            session.execute(
                delete(DragonEvent).where(DragonEvent.player_id.in_(
                    [self.player_id, self.other_player_id]
                ))
            )
            session.execute(
                delete(InteractionEvent).where(
                    InteractionEvent.player_id.in_(
                        [self.player_id, self.other_player_id]
                    )
                )
            )
            session.execute(
                delete(Dragon).where(Dragon.dragon_id == self.dragon_id)
            )
            session.execute(
                delete(PlayerState).where(PlayerState.player_id == self.player_id)
            )
            session.execute(
                delete(PlayerState).where(PlayerState.player_id == self.other_player_id)
            )
            session.execute(delete(Player).where(Player.player_id == self.player_id))
            session.execute(delete(Player).where(Player.player_id == self.other_player_id))
        self.engine.dispose()

    def _source(
        self, structured: dict[str, object], *, player_id: str | None = None
    ) -> str:
        event_id = f"test_d6_event_{uuid.uuid4().hex}"
        source_player_id = player_id or self.player_id
        with self.factory.begin() as session:
            state = session.get(PlayerState, source_player_id)
            assert state is not None
            session.add(
                InteractionEvent(
                    event_id=event_id,
                    event_type="free_world_action",
                    player_id=source_player_id,
                    npc_id=None,
                    world_day=1,
                    world_hour=8,
                    location_id=state.current_location,
                    player_utterance=str(structured["action"]),
                    npc_response=None,
                    topic=None,
                    player_claims=[],
                    memory_candidate=None,
                    relationship_signal=None,
                    event_payload={
                        "structured_action": copy.deepcopy(structured),
                        "resolution": {},
                        "world_effect": {},
                    },
                )
            )
        return event_id

    def _commit(self, structured: dict[str, object]) -> dict[str, object]:
        result = commit_riding_action(
            player_id=self.player_id,
            source_interaction_event_id=self._source(structured),
            structured_action=structured,
            persistence=self.persistence,
        )
        assert result is not None
        return result

    def _mount(self) -> dict[str, object]:
        return self._commit(
            action(
                "interact",
                f"我骑上 {self.dragon_name}",
                target=self.dragon_name,
            )
        )

    def test_operation_classification(self) -> None:
        self.assertEqual(
            classify_riding_operation(
                action("interact", "我骑上 Testwing", target="Testwing")
            ),
            "mount",
        )
        self.assertEqual(
            classify_riding_operation(
                action(
                    "travel",
                    f"骑着 {self.dragon_name} 去 Stormcliff",
                    target=self.dragon_name,
                    destination="Stormcliff",
                )
            ),
            "mounted_travel",
        )
        self.assertEqual(
            classify_riding_operation(action("interact", "我从龙背上下来")),
            "dismount",
        )
        for family, text in (
            ("rest_wait", "我在雾蚀凹湾停下来休息片刻"),
            ("observe_search", "我观察了一下四周"),
            ("explore", "我沿着海湾探索"),
            ("interact", "我和村民交流"),
            ("travel", "我步行前往 Stormcliff"),
        ):
            with self.subTest(family=family):
                structured = action(family, text)
                if family == "travel":
                    structured["method"] = None
                self.assertIsNone(classify_riding_operation(structured))

    def test_rest_wait_skips_riding_without_changing_dragon_truth(self) -> None:
        structured = action(
            "rest_wait", "在雾蚀凹湾停下来休息片刻"
        )
        with self.factory() as session:
            before_events = session.scalar(
                select(func.count())
                .select_from(DragonEvent)
                .where(DragonEvent.player_id == self.player_id)
            )
        before_bond = self.persistence.get_player_dragon_bond(
            player_id=self.player_id, dragon_id=self.dragon_id
        )
        before_dragon = self.persistence.get_dragon(self.dragon_id)
        before_riding = self.persistence.get_player_riding_state(self.player_id)
        application = create_app(
            action_provider_client=StubProvider(structured),
            persistence_adapter=self.persistence,
            dragon_encounter_roll=0.0,
            image_provider=DisabledSceneImageProvider("test disabled"),
        )
        with (
            patch(
                "api.app.route_grounded_riding_before_d2",
                side_effect=AssertionError("ordinary rest entered D6 route"),
            ),
            patch(
                "api.app.commit_riding_action",
                side_effect=AssertionError("ordinary rest entered D6 commit"),
            ),
        ):
            status, payload = asyncio.run(
                asgi_request(
                    application,
                    "/api/action/execute",
                    method="POST",
                    body={
                        "player_id": self.player_id,
                        "player_input": "我在雾蚀凹湾停下来休息片刻",
                    },
                )
            )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["structured_action"]["action_family"], "rest_wait")
        self.assertEqual(payload["resolution"]["status"], "success")
        self.assertIsNone(payload["dragon_riding"])
        self.assertNotIn("骑乘", payload["player_message"])
        with self.factory() as session:
            after_events = session.scalar(
                select(func.count())
                .select_from(DragonEvent)
                .where(DragonEvent.player_id == self.player_id)
            )
        self.assertEqual(after_events, before_events)
        self.assertEqual(
            self.persistence.get_player_riding_state(self.player_id),
            before_riding,
        )
        self.assertEqual(
            self.persistence.get_player_dragon_bond(
                player_id=self.player_id, dragon_id=self.dragon_id
            ),
            before_bond,
        )
        self.assertEqual(self.persistence.get_dragon(self.dragon_id), before_dragon)

    def test_non_tamed_dragon_is_blocked(self) -> None:
        with self.factory.begin() as session:
            session.execute(
                delete(DragonEvent).where(
                    DragonEvent.player_id == self.player_id,
                    DragonEvent.dragon_id == self.dragon_id,
                    DragonEvent.event_type == "dragon_tamed",
                )
            )
            dragon = session.get(Dragon, self.dragon_id)
            assert dragon is not None
            dragon.taming_state = "bonding"
        result = self._mount()
        self.assertEqual(result["reason_code"], "riding_dragon_not_tamed")
        self.assertFalse(result["riding_unlocked"])

    def test_taming_is_scoped_to_the_player_and_tamed_mount_unlocks(self) -> None:
        self.assertEqual(
            self.persistence.get_player_dragon_taming_state(
                player_id=self.player_id,
                dragon_id=self.dragon_id,
            ),
            "tamed",
        )
        self.assertEqual(
            self.persistence.get_player_dragon_taming_state(
                player_id=self.other_player_id,
                dragon_id=self.dragon_id,
            ),
            "wild",
        )
        world = build_world_summary(
            _load_postgres_world(
                self.persistence,
                player_id_override=self.other_player_id,
            )
        )
        self.assertFalse(any(
            dragon["dragon_id"] == self.dragon_id
            for dragon in world["nearby_dragons"]
        ))
        self.assertEqual(
            self.persistence.list_dragons_at_location(
                "skeld_village", player_id=self.other_player_id
            ),
            [],
        )
        self.assertIsNone(self.persistence.get_dragon(
            self.dragon_id, player_id=self.other_player_id,
        ))
        self.assertIsNotNone(self.persistence.get_dragon(
            self.dragon_id, player_id=self.player_id,
        ))

        mounted = self._mount()
        self.assertEqual(mounted["reason_code"], "riding_mounted")
        self.assertTrue(mounted["riding_unlocked"])

    def test_other_player_cannot_mount_discovered_dragon_by_id(self) -> None:
        source_id = self._source(
            action("interact", f"我骑上 {self.dragon_name}", target=self.dragon_name),
            player_id=self.other_player_id,
        )
        with self.assertRaisesRegex(PersistenceMappingError, "another Player"):
            self.persistence.commit_dragon_riding(
                player_id=self.other_player_id,
                dragon_id=self.dragon_id,
                source_interaction_event_id=source_id,
                operation="mount",
                destination_id=None,
                known_location_ids={"skeld_village"},
                rideable_archetype_ids={"balanced_wild"},
            )
        self.assertIsNone(self.persistence.get_player_riding_state(
            self.other_player_id
        )["mounted_dragon_id"])

    def test_legacy_cross_player_taming_does_not_grant_dragon_access(self) -> None:
        with self.factory.begin() as session:
            session.add(WorldStateEntry(
                state_id=f"player.{self.other_player_id}.riding.v1",
                state_value={
                    "version": 1,
                    "player_id": self.other_player_id,
                    "mounted_dragon_id": self.dragon_id,
                },
                source_event_type=None,
                source_event_id=None,
            ))
            session.add(PlayerDragonBond(
                player_id=self.other_player_id,
                dragon_id=self.dragon_id,
                familiarity=5,
                trust=5,
                fear=0,
                bond=3,
                riding_unlocked=True,
                last_significant_event_id=None,
            ))
            session.add(DragonEvent(
                event_id=f"test_d6_other_tamed_{self.token}",
                event_type="dragon_tamed",
                dragon_id=self.dragon_id,
                player_id=self.other_player_id,
                source_interaction_event_id=None,
                world_day=1,
                world_hour=8,
                location_id="skeld_village",
                milestone_key="tamed",
                event_payload={},
            ))
        self.assertFalse(self.persistence.has_rideable_dragon(
            self.other_player_id
        ))
        self.assertEqual(self.persistence.list_dragons_at_location(
            "skeld_village", player_id=self.other_player_id,
        ), [])
        self.assertIsNone(self.persistence.get_dragon(
            self.dragon_id, player_id=self.other_player_id,
        ))
        self.assertIsNone(self.persistence.get_player_riding_state(
            self.other_player_id
        )["mounted_dragon_id"])
        world = build_world_summary(_load_postgres_world(
            self.persistence, player_id_override=self.other_player_id,
        ))
        self.assertIsNone(world["riding"]["mounted_dragon_id"])
        with self.factory() as session:
            saved = session.get(
                WorldStateEntry, f"player.{self.other_player_id}.riding.v1"
            )
            assert saved is not None
            self.assertEqual(saved.state_value["mounted_dragon_id"], self.dragon_id)

    def test_named_dragon_travel_routes_before_d2_walking(self) -> None:
        structured = action(
            "travel",
            f"骑着 {self.dragon_name} 去 Stormcliff",
            target=self.dragon_name,
            destination="Stormcliff",
        )
        structured["method"] = None
        routed = route_grounded_riding_before_d2(
            player_id=self.player_id,
            structured_action=structured,
            persistence=self.persistence,
        )
        self.assertEqual(routed["method"], "骑龙")
        self.assertIsNone(structured["method"])

        unrelated = action(
            "travel", "骑马去 Stormcliff", destination="Stormcliff"
        )
        unrelated["method"] = None
        self.assertEqual(
            route_grounded_riding_before_d2(
                player_id=self.player_id,
                structured_action=unrelated,
                persistence=self.persistence,
            ),
            unrelated,
        )

    def test_api_mount_travel_visual_dismount_and_world_readback(self) -> None:
        image_provider = StubImageProvider()

        def execute(structured: dict[str, object]) -> dict[str, object]:
            application = create_app(
                action_provider_client=StubProvider(structured),
                persistence_adapter=self.persistence,
                image_provider=image_provider,
            )
            status, payload = asyncio.run(
                asgi_request(
                    application,
                    "/api/action/execute",
                    method="POST",
                    body={
                        "player_id": self.player_id,
                        "player_input": str(structured["action"]),
                    },
                )
            )
            self.assertEqual(status, 200, payload)
            return payload

        mounted = execute(
            action("interact", f"我骑上 {self.dragon_name}", target=self.dragon_name)
        )
        self.assertEqual(mounted["dragon_riding"]["reason_code"], "riding_mounted")
        self.assertEqual(mounted["scene_visual"]["status"], "generated")
        self.assertEqual(mounted["scene_visual"]["camera"], "first_person_dragon_back")

        traveling = action(
            "travel",
            f"骑着 {self.dragon_name} 前往 Stormcliff",
            target=self.dragon_name,
            destination="Stormcliff",
        )
        traveling["method"] = None
        arrived = execute(traveling)
        self.assertEqual(arrived["resolution"]["domain_route"], "dragon")
        self.assertEqual(arrived["dragon_riding"]["reason_code"], "riding_arrived")
        self.assertEqual(arrived["scene_visual"]["trigger"], "mounted_travel_arrival")
        self.assertEqual(self.persistence.get_player_state(self.player_id)["current_location"], "stormcliff")
        self.assertEqual(self.persistence.get_dragon(self.dragon_id)["current_location"], "stormcliff")

        world_payload = build_world_summary(
            _load_postgres_world(
                self.persistence, player_id_override=self.player_id
            )
        )
        self.assertEqual(world_payload["riding"]["mounted_dragon_id"], self.dragon_id)
        self.assertEqual(world_payload["current_location"]["id"], "stormcliff")

        dismounted = execute(
            action("interact", f"我从 {self.dragon_name} 背上下来", target=self.dragon_name)
        )
        self.assertEqual(dismounted["dragon_riding"]["reason_code"], "riding_dismounted")
        self.assertIsNone(dismounted["scene_visual"])
        self.assertEqual(len(image_provider.prompts), 2)

    def test_deferred_mount_always_schedules_dragon_mount_visual(self) -> None:
        image_provider = StubImageProvider()
        structured = action(
            "interact",
            f"我骑上 {self.dragon_name}",
            target=self.dragon_name,
        )
        application = create_app(
            action_provider_client=StubProvider(structured),
            persistence_adapter=self.persistence,
            image_provider=image_provider,
        )
        status, payload = asyncio.run(
            asgi_request(
                application,
                "/api/action/execute",
                method="POST",
                body={
                    "player_id": self.player_id,
                    "player_input": str(structured["action"]),
                    "defer_visual": True,
                },
            )
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["dragon_riding"]["reason_code"], "riding_mounted")
        self.assertEqual(payload["scene_visual"]["status"], "pending")
        self.assertEqual(payload["scene_visual"]["trigger"], "dragon_mount")

        visual_status, visual = asyncio.run(
            asgi_request(
                application,
                f"/api/visual/{payload['source_event_id']}",
            )
        )
        self.assertEqual(visual_status, 200, visual)
        self.assertEqual(visual["status"], "generated")
        self.assertEqual(visual["trigger"], "dragon_mount")
        self.assertEqual(visual["camera"], "first_person_dragon_back")
        self.assertTrue(visual["image_url"])

    def test_observe_in_dynamic_location_after_dismount_survives_new_app(self) -> None:
        dynamic_locations = self.persistence.get_dynamic_location_registry()[
            "locations"
        ]
        dynamic_id = next(
            location_id
            for location_id, location in dynamic_locations.items()
            if location["name"] == "雾蚀凹湾"
        )
        self._mount()
        self._commit(
            action("interact", "我从龙背上下来", target=self.dragon_name)
        )
        with self.factory.begin() as session:
            player_state = session.get(PlayerState, self.player_id)
            dragon = session.get(Dragon, self.dragon_id)
            assert player_state is not None and dragon is not None
            player_state.current_location = dynamic_id
            dragon.current_location = dynamic_id

        observe = action("observe_search", "观察一下四周", target="四周")
        image_provider = DisabledSceneImageProvider("test disabled")
        with self.factory() as session:
            before_count = session.scalar(
                select(func.count())
                .select_from(InteractionEvent)
                .where(InteractionEvent.player_id == self.player_id)
            )
        for _ in range(2):
            application = create_app(
                action_provider_client=StubProvider(observe),
                image_provider=image_provider,
                persistence_adapter=self.persistence,
                dragon_encounter_roll=0.0,
            )
            status, payload = asyncio.run(
                asgi_request(
                    application,
                    "/api/action/execute",
                    method="POST",
                    body={
                        "player_id": self.player_id,
                        "player_input": "我观察了一下四周",
                    },
                )
            )
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["resolution"]["status"], "success")
            if payload["scene_visual"] is not None:
                self.assertEqual(payload["scene_visual"]["status"], "disabled")
            self.assertIsNone(
                self.persistence.get_player_riding_state(self.player_id)[
                    "mounted_dragon_id"
                ]
            )
            self.assertEqual(
                self.persistence.get_player_state(self.player_id)[
                    "current_location"
                ],
                dynamic_id,
            )
        with self.factory() as session:
            after_count = session.scalar(
                select(func.count())
                .select_from(InteractionEvent)
                .where(InteractionEvent.player_id == self.player_id)
            )
        self.assertEqual(after_count, before_count + 2)

    def test_personally_tamed_dragon_does_not_require_a_second_bond_gate(self) -> None:
        with self.factory.begin() as session:
            bond = session.get(PlayerDragonBond, (self.player_id, self.dragon_id))
            assert bond is not None
            bond.bond = 2
        result = self._mount()
        self.assertEqual(result["reason_code"], "riding_mounted")
        self.assertTrue(result["riding_unlocked"])

    def test_mount_unlocks_persists_and_is_idempotent(self) -> None:
        structured = action(
            "interact",
            f"我骑上 {self.dragon_name}",
            target=self.dragon_name,
        )
        source = self._source(structured)
        first = commit_riding_action(
            player_id=self.player_id,
            source_interaction_event_id=source,
            structured_action=structured,
            persistence=self.persistence,
        )
        second = commit_riding_action(
            player_id=self.player_id,
            source_interaction_event_id=source,
            structured_action=structured,
            persistence=PostgresPersistenceAdapter(self.factory),
        )
        assert first is not None and second is not None
        self.assertEqual(first["reason_code"], "riding_mounted")
        self.assertEqual(second["status"], "already_applied")
        self.assertEqual(
            self.persistence.get_player_riding_state(self.player_id)[
                "mounted_dragon_id"
            ],
            self.dragon_id,
        )
        self.assertTrue(
            self.persistence.get_player_dragon_bond(
                player_id=self.player_id,
                dragon_id=self.dragon_id,
            )["riding_unlocked"]
        )
        with self.factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(DragonEvent)
                .where(
                    DragonEvent.player_id == self.player_id,
                    DragonEvent.event_type == "dragon_accepts_mount",
                )
            )
        self.assertEqual(count, 1)

    def test_authored_travel_moves_player_and_dragon_atomically(self) -> None:
        self._mount()
        result = self._commit(
            action(
                "travel",
                f"骑着 {self.dragon_name} 去 Stormcliff",
                target=self.dragon_name,
                destination="Stormcliff",
            )
        )
        self.assertEqual(result["reason_code"], "riding_arrived")
        with self.factory() as session:
            player = session.get(PlayerState, self.player_id)
            dragon = session.get(Dragon, self.dragon_id)
            assert player is not None and dragon is not None
            self.assertEqual(player.current_location, "stormcliff")
            self.assertEqual(dragon.current_location, "stormcliff")

    def test_dynamic_location_travel_uses_d5_registry(self) -> None:
        registry = self.persistence.get_dynamic_location_registry()
        dynamic = next(iter(registry["locations"].values()), None)
        if dynamic is None:
            self.skipTest("No formal D5 Dynamic Location is present.")
        self._mount()
        result = self._commit(
            action(
                "travel",
                f"骑着 {self.dragon_name} 去 {dynamic['name']}",
                target=self.dragon_name,
                destination=dynamic["name"],
            )
        )
        self.assertEqual(result["destination_id"], dynamic["location_id"])
        with self.factory() as session:
            player = session.get(PlayerState, self.player_id)
            dragon = session.get(Dragon, self.dragon_id)
            assert player is not None and dragon is not None
            self.assertEqual(player.current_location, dynamic["location_id"])
            self.assertEqual(dragon.current_location, dynamic["location_id"])

    def test_invalid_destination_rolls_back_both_locations(self) -> None:
        self._mount()
        source = self._source(
            action(
                "travel",
                f"骑着 {self.dragon_name} 去虚空",
                target=self.dragon_name,
                destination="虚空",
            )
        )
        with self.assertRaises(PersistenceMappingError):
            self.persistence.commit_dragon_riding(
                player_id=self.player_id,
                dragon_id=self.dragon_id,
                source_interaction_event_id=source,
                operation="mounted_travel",
                destination_id="not_a_location",
                known_location_ids={"skeld_village", "stormcliff"},
                rideable_archetype_ids={"balanced_wild"},
            )
        with self.factory() as session:
            player = session.get(PlayerState, self.player_id)
            dragon = session.get(Dragon, self.dragon_id)
            assert player is not None and dragon is not None
            self.assertEqual(player.current_location, "skeld_village")
            self.assertEqual(dragon.current_location, "skeld_village")

    def test_dismount_persists_without_revoking_unlock(self) -> None:
        self._mount()
        result = self._commit(
            action("interact", f"我从 {self.dragon_name} 背上下来")
        )
        self.assertEqual(result["reason_code"], "riding_dismounted")
        reloaded = PostgresPersistenceAdapter(self.factory)
        self.assertIsNone(
            reloaded.get_player_riding_state(self.player_id)["mounted_dragon_id"]
        )
        self.assertTrue(
            reloaded.get_player_dragon_bond(
                player_id=self.player_id,
                dragon_id=self.dragon_id,
            )["riding_unlocked"]
        )


if __name__ == "__main__":
    unittest.main()
