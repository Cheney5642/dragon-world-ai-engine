"""Small deterministic story director over already committed player actions.

Events create personal field notes and choices, never dragons, rewards, or
unverified achievements. NPC sharing is evaluated by the existing NPC rules.
"""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from core.display_names import npc_aliases

FOCUS = {
    "discovery": ("field_observation", "寻踪者的观察", "你把眼前的环境作为下一次探索的起点"),
    "reputation": ("reputation_opportunity", "用见闻建立声望", "你意识到，亲历的记录可以成为赢得信任的第一步"),
    "care": ("community_observation", "值得带回的见闻", "你开始考虑这些亲历见闻能够怎样帮助当地居民"),
    "freedom": ("independent_path", "自己的道路", "这次抵达成为了你亲自选择道路的一部分"),
}


def initial_story(origin: dict[str, Any], location_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1, "origin": copy.deepcopy(origin),
        "thread": {"direction": origin["narrative_direction"], "branch": "undecided", "chapter": 0},
        "memories": [{"sequence": 1, "kind": "origin", "summary": f"你以自述身份「{origin['identity']}」开始旅程。目标：{origin['goal']}",
                      "location_id": location_id, "source_event_id": None, "world_changes": {}}],
        "events": [], "processed_sources": [], "shared_locations": [], "last_update": None,
    }


def _choice(text: str) -> str | None:
    """Only explicit, affirmative personal decisions. A wish is not an act."""
    text = text.strip().casefold()
    if re.search(r"如果|假如|曾经|已经|想象|据说|也许|能不能|if |would |might |already ", text):
        return None
    if re.search(r"(?:不|别|拒绝|不要|不想|不打算|不愿).*保密|don't.*keep|do not.*keep", text):
        return None
    if re.search(r"(?:暂时|选择|决定|先|继续)?保密|保留.*记录|keep.*(?:private|secret)|(?:不|别|拒绝|不要|不想|不打算|不愿)(?:向[^，。！？;]+)?(?:分享|公开)|(?:don't|do not).*share", text):
        return "keep"
    if re.search(r"分享.*(?:见闻|记录|观察)|(?:见闻|记录|观察).*分享|share.*(?:notes|observations)", text):
        return "share"
    return None


def _entity(npc: dict[str, Any]) -> dict[str, str]:
    return {"id": npc["id"], "name": npc["name"], "type": "npc"}


def advance_story(
    story: dict[str, Any], *, source: dict[str, Any], world: dict[str, Any],
    result: dict[str, Any], relationships: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Pure decision. Return new story + an optional grounded NPC sharing plan."""
    state = copy.deepcopy(story)
    source_id = source["event_id"]
    if source_id in state["processed_sources"]:
        return state, None
    state["processed_sources"].append(source_id)
    state["last_update"] = None
    resolution = result["resolution"]
    action = result["structured_action"]
    if resolution["status"] in {"blocked", "needs_clarification"} or action["needs_clarification"]:
        return state, None
    if (result.get("dragon_riding") or {}).get("status") == "blocked":
        return state, None

    location = world["current_location"]
    origin = state["origin"]
    current_goals = world.get("player", {}).get("goals", [])
    current_goal = "；".join(current_goals) if current_goals else "自由探索，寻找新的目标"
    active = next((event for event in reversed(state["events"]) if event["status"] == "open"), None)
    decision = _choice(source["player_utterance"])
    npc_plan = None
    event = None
    changes: dict[str, Any] = copy.deepcopy(resolution.get("state_changes", {}))
    reason_prefix = f"你的自述身份是「{origin['identity']}」，当前目标是「{current_goal}」。"

    if active and decision:
        if decision == "share":
            # Bind a named NPC, or the sole nearby NPC; never silently pick one.
            npcs = world.get("nearby_npcs", [])
            text = source["player_utterance"].casefold()
            matches = [
                npc
                for npc in npcs
                if any(
                    alias.casefold() in text
                    for alias in npc_aliases(npc["id"], npc["name"])
                )
            ]
            npc = matches[0] if len(matches) == 1 else (npcs[0] if len(npcs) == 1 else None)
            if npc is None:
                state["last_update"] = {"status": "needs_clarification", "event": None,
                    "message": "分享需要一位同地点的明确 NPC。请回到村庄，说明你要向谁分享亲历记录。"}
                return state, None
            if active["location"]["id"] in state["shared_locations"]:
                state["last_update"] = {"status": "no_change", "event": None,
                    "message": "这处地点的记录已经分享过，不会重复增加信任。"}
                return state, None
            relationship = next((r for r in relationships if r["npc_id"] == npc["id"]), None)
            wary = relationship is not None and relationship["trust"] < 0
            reply = ("我听到了你亲历的记录，但我们之间的信任仍需慢慢修复。" if wary
                     else "谢谢你把亲历的地点记录带回来。这是我们可以核实、继续交流的起点。")
            npc_plan = {"npc": npc, "speech": reply, "evidence_event_id": active["source_event_id"],
                        "observed_location": active["location"]["id"]}
            branch = "shared_path"
            summary = f"你向 {npc['name']} 分享了在 {active['location']['name']} 的亲历记录。{reply}"
            event_type = "knowledge_shared"
            involved = [_entity(npc)]
            state["shared_locations"].append(active["location"]["id"])
        else:
            branch = "independent_path"
            summary = f"你决定暂不公开 {active['location']['name']} 的记录，保留独自探索的空间。"
            event_type = "knowledge_kept"
            involved = []
        active["status"] = "resolved"
        active["selected_choice"] = decision
        state["thread"]["branch"] = branch
        changes["narrative_branch"] = branch
        event = {
            "event_type": event_type, "title": "你的选择留下了后果", "narrative": summary,
            "reason": f"{reason_prefix}你对第 {active['chapter']} 段亲历记录作出了明确选择。",
            "involved_entities": involved, "choices": [], "status": "resolved",
            "evidence_refs": [source_id, active["source_event_id"]],
        }
    elif action["action_family"] in {"travel", "explore", "observe_search"} and resolution["status"] == "success":
        # Existing domain errors must not become story successes.
        if active and (active["location"]["id"] == location["id"] or world.get("nearby_npcs")):
            event = None
        else:
            branch = state["thread"]["branch"]
            dedupe = f"{location['id']}:{branch}"
            if any(item.get("opportunity_key") == dedupe for item in state["events"]):
                return state, None
            if active:
                active["status"] = "deferred"
            event_type, title, line = FOCUS.get(origin.get("focus"), FOCUS["discovery"])
            previous = state["memories"][-1]
            continuity = ""
            if branch == "shared_path":
                continuity = "你上次选择分享见闻；这次你留意哪些信息适合带回交流。"
            elif branch == "independent_path":
                continuity = "你上次选择保留记录；这次继续按自己的节奏观察。"
            trusted = [r for r in relationships if r["trust"] > 0]
            if trusted:
                continuity += f"你与 {trusted[0]['npc_name']} 已有正向信任，但这不保证任何请求成功。"
            npcs = world.get("nearby_npcs", [])
            recipient = npcs[0]["name"] if npcs else "阿斯特丽德"
            event = {
                "event_type": event_type, "title": title,
                "narrative": f"{location['name']}：{location.get('description', '')}。{line}。{continuity}",
                "reason": f"{reason_prefix}你实际完成了在 {location['name']} 的行动；上一段经历是：{previous['summary']}",
                "involved_entities": [_entity(npc) for npc in npcs],
                "choices": [
                    {"id": "share", "label": "与当地人分享", "input": f"我向 {recipient} 分享这次观察记录",
                     "consequence": "同地点分享可核实的亲历记录，按 NPC 规则评估信任；同一地点只计一次。"},
                    {"id": "keep", "label": "暂时保留记录", "input": "我决定暂时保密，保留自己的记录",
                     "consequence": "故事转向独立探索，不改变 NPC 信任。"},
                ],
                "status": "open", "opportunity_key": dedupe,
                "evidence_refs": [source_id, *([previous["source_event_id"]] if previous["source_event_id"] else [])],
            }

    # Domain milestones are facts only when their formal resolver committed them.
    dragon = result.get("dragon_interaction")
    if dragon and dragon.get("status") == "applied":
        changes["dragon_interaction"] = {key: dragon.get(key) for key in ("dragon_id", "applied_deltas", "taming_transition")}
    riding = result.get("dragon_riding")
    if riding and riding.get("status") == "success":
        changes["riding"] = {key: riding.get(key) for key in ("operation", "dragon_id", "destination_id")}
    discovery = result.get("location_discovery")
    if discovery and discovery.get("status") == "committed":
        changes["discovered_location"] = discovery["location_id"]

    if event:
        state["thread"]["chapter"] += 1
        event.update({
            "event_id": f"story_{uuid.uuid5(uuid.NAMESPACE_URL, source_id).hex}",
            "source_event_id": source_id, "location": copy.deepcopy(location),
            "chapter": state["thread"]["chapter"], "consequences": changes,
            "identity_evidence": {"focus": origin["focus"], "goal": current_goal},
            "relationship_evidence": copy.deepcopy(relationships),
        })
        state["events"].append(event)
    if event or changes:
        memory = {
            "sequence": len(state["memories"]) + 1, "kind": event["event_type"] if event else "world_change",
            "summary": event["narrative"] if event else result["player_message"],
            "location_id": location["id"], "source_event_id": source_id,
            "world_changes": changes,
        }
        state["memories"].append(memory)
        state["last_update"] = {"status": "recorded", "event": event, "message": memory["summary"]}
    return state, npc_plan
