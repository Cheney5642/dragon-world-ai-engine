"""PoC acceptance cases against PostgreSQL; providers are controlled test doubles."""

from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import delete, func, select

from api.app import _load_postgres_world, build_world_summary, create_app
from database import create_database_engine, create_session_factory
from database.models import (DragonEvent, InteractionEvent, NpcMemory, NpcRelationship,
                             Player, PlayerDragonBond, PlayerState, WorldStateEntry)
from database.persistence import PostgresPersistenceAdapter
from multimodal.scene_renderer import DisabledSceneImageProvider
from tests.test_free_action_resolution import action
from tests.test_scene_renderer import StubImageProvider
from tests.test_web_api import asgi_request


class StoryProvider:
    def __init__(self, focus="discovery"):
        self.focus = focus
        self.action = action("observe_search", "观察周围")

    def create_structured_output(self, *, schema_name, **kwargs):
        if schema_name == "free_action_interpretation":
            return json.dumps(self.action, ensure_ascii=False)
        if schema_name == "identity_interpretation":
            return json.dumps({
                "display_name": None, "candidate_identity_facets": {"narrative_species": "human", "occupations": ["旅人"]},
                "candidate_facts": ["北境旅人"], "candidate_claims": [], "traits": ["好奇"],
                "capability_hints": [], "identity_summary": "一位寻找自己道路的北境旅人。",
            }, ensure_ascii=False)
        if schema_name == "character_origin":
            return json.dumps({"identity": "北境旅人", "background": "自述来自北境",
                "personality": ["好奇"], "goal": "寻找龙" if self.focus == "discovery" else "恢复声望",
                "narrative_direction": "寻龙探索" if self.focus == "discovery" else "通过行动赢得信任",
                "focus": self.focus}, ensure_ascii=False)
        raise AssertionError(f"Unexpected provider call: {schema_name}")


class PersonalStoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_database_engine()
        self.factory = create_session_factory(self.engine)
        self.persistence = PostgresPersistenceAdapter(self.factory)
        self.players = []
        self.provider = StoryProvider()
        self.app = self.application()

    def application(self, image_provider=None):
        return create_app(persistence_adapter=self.persistence, identity_provider_client=self.provider,
            action_provider_client=self.provider, dragon_encounter_roll=0,
            image_provider=image_provider or DisabledSceneImageProvider("test"))

    def tearDown(self):
        # Exact IDs created by this test only; no global reset or Demo mutation.
        with self.factory.begin() as session:
            for player_id in self.players:
                for model in (NpcMemory, NpcRelationship, PlayerDragonBond, DragonEvent):
                    session.execute(delete(model).where(model.player_id == player_id))
                session.execute(delete(WorldStateEntry).where(WorldStateEntry.state_id.in_([
                    f"player.{player_id}.story.v1", f"player.{player_id}.riding.v1"])))
                session.execute(delete(InteractionEvent).where(InteractionEvent.player_id == player_id))
                session.execute(delete(PlayerState).where(PlayerState.player_id == player_id))
                session.execute(delete(Player).where(Player.player_id == player_id))
        self.engine.dispose()

    def request(self, path, body=None, application=None):
        return asyncio.run(asgi_request(path, method="POST" if body is not None else "GET",
            body=body, application=application or self.app))

    def create(self, focus="discovery"):
        self.provider.focus = focus
        request_id = uuid.uuid4()
        player_id = f"player_poc_{request_id.hex}"
        self.players.append(player_id)
        status, result = self.request("/api/player/create", {
            "request_id": str(request_id), "self_description": f"我是北境旅人，我的方向是{focus}。"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["world"]["player"]["player_id"], player_id)
        return player_id

    def execute(self, player_id, text, family="observe_search", *, target=None, destination=None, application=None):
        self.provider.action = action(family, text, target=target, destination=destination)
        status, result = self.request("/api/action/execute", {
            "player_id": player_id, "player_input": text}, application=application)
        self.assertEqual(status, 200, result)
        self.assertNotEqual((result.get("story_update") or {}).get("status"), "failed", result)
        return result

    def story(self, player_id):
        status, story = self.request(f"/api/story/{player_id}")
        self.assertEqual(status, 200)
        return story

    def test_case_1_different_origins_have_different_directions(self):
        a, b = self.create(), self.create("reputation")
        self.assertNotEqual(self.story(a)["thread"]["direction"], self.story(b)["thread"]["direction"])
        self.assertEqual(self.story(a)["origin"]["epistemic_status"], "self_description_and_aspiration")

    def test_case_2_same_location_different_identity_events(self):
        a, b = self.create(), self.create("reputation")
        ea = self.execute(a, "我观察周围")["story_update"]["event"]
        eb = self.execute(b, "我观察周围")["story_update"]["event"]
        self.assertEqual(ea["location"], eb["location"])
        self.assertNotEqual(ea["event_type"], eb["event_type"])
        self.assertIn(ea["source_event_id"], ea["evidence_refs"])

    def test_case_3_choice_changes_future_event_and_survives_restart(self):
        player_id = self.create()
        self.execute(player_id, "我观察周围")
        self.execute(player_id, "我决定暂时保密，保留自己的记录", "other")
        next_event = self.execute(player_id, "我前往 Old Ruins", "travel", destination="Old Ruins")["story_update"]["event"]
        self.assertIn("你上次选择保留记录", next_event["narrative"])
        status, restarted = self.request(f"/api/story/{player_id}", application=self.application())
        self.assertEqual(status, 200)
        self.assertEqual(restarted["thread"]["branch"], "independent_path")
        self.assertEqual(restarted, self.story(player_id))

    def test_case_4_sharing_changes_npc_relationship_and_future_context(self):
        player_id = self.create()
        self.execute(player_id, "我观察周围")
        shared = self.execute(player_id, "我向 Astrid 分享这次观察记录", "interact", target="Astrid")
        self.assertEqual(shared["story_update"]["event"]["event_type"], "knowledge_shared")
        relationship = self.persistence.get_npc_relationship(player_id, "npc_astrid")
        self.assertEqual(relationship["trust"], 1)
        self.assertEqual(relationship["attitude"], "warm")
        self.assertEqual(len(self.persistence.list_npc_memories("npc_astrid", player_id)), 1)
        later = self.execute(player_id, "我前往 Old Ruins", "travel", destination="Old Ruins")
        self.assertIn("正向信任", later["story_update"]["event"]["narrative"])
        self.assertIn("npc_relationship", self.story(player_id)["world_changes"][0]["world_changes"])

    def test_case_5_image_failure_keeps_event_and_action_success(self):
        player_id = self.create()
        result = self.execute(player_id, "我观察周围", application=self.application(StubImageProvider(fail=True)))
        self.assertEqual(result["resolution"]["status"], "success")
        self.assertEqual(result["scene_visual"]["status"], "failed")
        self.assertIn("Grounded visual context", result["scene_visual"]["image_prompt"])
        self.assertEqual(len(self.story(player_id)["recent_events"]), 1)

    def test_deferred_visual_returns_action_before_polling_result(self):
        player_id = self.create()
        image_provider = StubImageProvider()
        application = self.application(image_provider)
        status, result = self.request(
            "/api/action/execute",
            {
                "player_id": player_id,
                "player_input": "我观察周围",
                "defer_visual": True,
            },
            application=application,
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["scene_visual"]["status"], "pending")
        visual_status, visual = self.request(
            f"/api/visual/{result['source_event_id']}",
            application=application,
        )
        self.assertEqual(visual_status, 200)
        self.assertEqual(visual["status"], "generated")
        self.assertTrue(visual["image_url"])

    def test_disabled_image_and_rest_have_no_riding_side_effect(self):
        player_id = self.create()
        result = self.execute(player_id, "我观察周围")
        self.assertEqual(result["scene_visual"]["status"], "disabled")
        before = self.persistence.get_player_riding_state(player_id)
        rested = self.execute(player_id, "我停下来休息片刻", "rest_wait")
        self.assertIsNone(rested["dragon_riding"])
        self.assertIsNone(rested["story_update"])
        self.assertEqual(before, self.persistence.get_player_riding_state(player_id))
        self.assertEqual(len(self.story(player_id)["memories"]), 2)

    def test_same_source_is_idempotent(self):
        player_id = self.create()
        result = self.execute(player_id, "我观察周围")
        world = build_world_summary(_load_postgres_world(self.persistence, player_id_override=player_id))
        before = self.story(player_id)
        retry = self.persistence.commit_personal_story(player_id=player_id,
            source_event_id=result["source_event_id"], world=world, result=result)
        self.assertEqual(retry["status"], "already_applied")
        self.assertEqual(self.story(player_id), before)

    def test_failure_during_sharing_rolls_back_story_memory_and_relationship(self):
        player_id = self.create()
        self.execute(player_id, "我观察周围")
        before = self.story(player_id)
        self.provider.action = action("interact", "分享观察记录", target="Astrid")
        with patch("npc.memory.build_memory_preview", side_effect=RuntimeError("test rollback")):
            status, result = self.request("/api/action/execute", {
                "player_id": player_id, "player_input": "我向 Astrid 分享这次观察记录"})
        self.assertEqual(status, 200)
        self.assertEqual(result["story_update"]["status"], "failed")
        self.assertEqual(self.story(player_id), before)
        self.assertIsNone(self.persistence.get_npc_relationship(player_id, "npc_astrid"))
        self.assertEqual(self.persistence.list_npc_memories("npc_astrid", player_id), [])
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(InteractionEvent).where(
                InteractionEvent.player_id == player_id, InteractionEvent.event_type == "npc_dialogue")), 0)

    def test_unreachable_destination_creates_no_story(self):
        player_id = self.create()
        result = self.execute(player_id, "我前往月球", "travel", destination="月球")
        self.assertEqual(result["resolution"]["status"], "blocked")
        self.assertIsNone(result["story_update"])
        self.assertEqual(len(self.story(player_id)["memories"]), 1)

    def test_negated_sharing_does_not_change_npc_trust(self):
        player_id = self.create()
        self.execute(player_id, "我观察周围")
        self.execute(player_id, "我不向 Astrid 分享这次观察记录", "other")
        self.assertIsNone(self.persistence.get_npc_relationship(player_id, "npc_astrid"))
        self.assertEqual(self.story(player_id)["thread"]["branch"], "independent_path")

    def test_create_retry_is_idempotent_and_cannot_overwrite_identity(self):
        player_id = self.create()
        request_id = str(uuid.UUID(player_id.removeprefix("player_poc_")))
        status, _ = self.request("/api/player/create", {"request_id": request_id,
            "self_description": "我是北境旅人，我的方向是discovery。"})
        self.assertEqual(status, 200)
        status, _ = self.request("/api/player/create", {"request_id": request_id, "self_description": "我改了身份"})
        self.assertEqual(status, 409)

    def test_invalid_origin_output_creates_no_player(self):
        request_id = uuid.uuid4()
        player_id = f"player_poc_{request_id.hex}"
        self.players.append(player_id)
        with patch("api.app.interpret_origin", side_effect=ValueError("invalid model output")):
            status, _ = self.request("/api/player/create", {"request_id": str(request_id), "self_description": "旅人"})
        self.assertEqual(status, 502)
        self.assertIsNone(self.persistence.get_player(player_id))

    def test_sharing_requires_colocation_and_never_farms_same_location(self):
        player_id = self.create()
        self.execute(player_id, "我观察周围")
        self.execute(player_id, "我向 Astrid 分享这次观察记录", "interact", target="Astrid")
        self.execute(player_id, "我观察周围")
        repeated = self.execute(player_id, "我向 Astrid 分享这次观察记录", "interact", target="Astrid")
        self.assertEqual(repeated["story_update"]["status"], "no_change")
        self.assertEqual(self.persistence.get_npc_relationship(player_id, "npc_astrid")["trust"], 1)
        self.execute(player_id, "我前往 Old Ruins", "travel", destination="Old Ruins")
        away = self.execute(player_id, "我向 Astrid 分享这次观察记录", "interact", target="Astrid")
        self.assertEqual(away["story_update"]["status"], "needs_clarification")
        self.assertEqual(self.persistence.get_npc_relationship(player_id, "npc_astrid")["trust"], 1)

    def test_other_players_source_is_rejected(self):
        a, b = self.create(), self.create()
        result = self.execute(a, "我观察周围")
        world = build_world_summary(_load_postgres_world(self.persistence, player_id_override=b))
        with self.assertRaisesRegex(ValueError, "another Player"):
            self.persistence.commit_personal_story(player_id=b, source_event_id=result["source_event_id"],
                                                  world=world, result=result)
        self.assertEqual(len(self.story(b)["memories"]), 1)

    def test_regular_npc_runtime_supports_new_players_and_records_relationship_history(self):
        from pathlib import Path
        from tests.test_npc_api import MockProvider, RUNTIME_CASES_PATH
        case = json.loads(Path(RUNTIME_CASES_PATH).read_text(encoding="utf-8"))["cases"][0]
        player_id = self.create()
        provider = MockProvider(case["mock_response"])
        app = create_app(persistence_adapter=self.persistence, npc_provider_client=provider,
                         image_provider=DisabledSceneImageProvider("test"))
        status, reply = self.request("/api/npc/interact", {"player_id": player_id,
            "npc_id": case["npc_id"], "utterance": case["player_utterance"]}, application=app)
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["interaction_event"]["player_id"], player_id)
        self.assertTrue(reply["interaction_available"])
        # A grounded change through the existing evaluator/adapter is projected
        # into life history; repeating that persisted result cannot duplicate it.
        from npc.relationship import create_initial_relationship, evaluate_relationship_change
        event = dict(reply["interaction_event"])
        event.update(event_id=f"npc_event_{uuid.uuid4().hex}", topic="direct_insult",
                     memory_candidate=True, relationship_signal="potential_negative",
                     player_claims=[], npc_response={"response_type": "refusal", "speech": "请尊重我。"})
        self.persistence.insert_interaction_event(event)
        preview = evaluate_relationship_change(create_initial_relationship(case["npc_id"], player_id), event)
        relationship = {**preview["proposed_relationship"], "applied_event_ids": [event["event_id"]],
                        "last_source_event_id": event["event_id"]}
        self.persistence.upsert_npc_relationship(relationship)
        self.persistence.upsert_npc_relationship(relationship)
        memories = [m for m in self.story(player_id)["memories"] if m["kind"] == "npc_relationship"]
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["world_changes"]["npc_relationship"]["after"]["trust"], -1)

    def test_updated_goals_are_read_by_future_events(self):
        player_id = self.create()
        self.provider.action = action("other", "增加目标", explicit_goal={"operation": "add", "goal": "研究古代遗迹"})
        status, _ = self.request("/api/action/execute", {"player_id": player_id, "player_input": "我的目标是研究古代遗迹"})
        self.assertEqual(status, 200)
        event = self.execute(player_id, "我观察周围")["story_update"]["event"]
        self.assertIn("研究古代遗迹", event["identity_evidence"]["goal"])

    def test_bjorn_knows_original_player_without_treating_new_player_as_apprentice(self):
        from npc.context_builder import build_npc_context
        from tests.test_npc_api import MockProvider
        player_id = self.create()
        world = _load_postgres_world(self.persistence, player_id_override=player_id)
        context = build_npc_context("npc_bjorn", world, player_id)
        self.assertEqual(context["player"]["id"], player_id)
        known = context["knowledge"]["known_entities"]
        self.assertIn("player_001", [entity["id"] for entity in known])
        self.assertNotIn(player_id, [entity["id"] for entity in known])
        provider = MockProvider({"npc_id": "npc_bjorn", "response_type": "answer",
            "speech": "我是这里的铁匠。", "knowledge_status": "known",
            "referenced_knowledge": {"entity_ids": [], "location_ids": [], "facts": ["metalworking"]},
            "requires_followup": False})
        app = create_app(persistence_adapter=self.persistence, npc_provider_client=provider,
                         image_provider=DisabledSceneImageProvider("test"))
        status, reply = self.request("/api/npc/interact", {"player_id": player_id,
            "npc_id": "npc_bjorn", "utterance": "你好，你是做什么的？"}, application=app)
        self.assertEqual(status, 200, reply)
        self.assertTrue(reply["interaction_available"])
        self.assertIsNone(self.persistence.get_npc_relationship(player_id, "npc_bjorn"))

    def test_free_exploration_can_continue_without_selecting_a_suggested_choice(self):
        player_id = self.create()
        self.execute(player_id, "我观察周围")
        event = self.execute(player_id, "我前往 Old Ruins", "travel", destination="Old Ruins")["story_update"]["event"]
        self.assertEqual(event["location"]["id"], "old_ruins")
        story = self.story(player_id)
        self.assertEqual(story["recent_events"][0]["status"], "deferred")
        self.assertEqual(story["thread"]["branch"], "undecided")


if __name__ == "__main__":
    unittest.main()
