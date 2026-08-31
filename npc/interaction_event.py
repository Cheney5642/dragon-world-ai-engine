"""Deterministic, read-only NPC Interaction Event Builder v0.1."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from npc.context_builder import NpcContextError, load_context_schema
from npc.response_runtime import (
    NpcResponseError,
    load_response_schema,
    validate_npc_response,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "npc_interaction_event.schema.json"


class NpcInteractionEventError(Exception):
    """Raised when a safe, schema-valid Interaction Event cannot be built."""


def load_interaction_event_schema(
    path: Path = EVENT_SCHEMA_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise NpcInteractionEventError(
            f"NPC Interaction Event Schema does not exist: {path}"
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcInteractionEventError(
            f"NPC Interaction Event Schema is not valid JSON: {path}"
        ) from exc
    if not isinstance(schema, dict):
        raise NpcInteractionEventError(
            "NPC Interaction Event Schema must be a JSON object."
        )
    return schema


def validate_interaction_event(
    event: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_interaction_event_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(event)
    except (SchemaError, ValidationError) as exc:
        raise NpcInteractionEventError(
            f"NPC Interaction Event failed JSON Schema validation: {exc.message}"
        ) from exc


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _player_label(npc_context: dict[str, Any]) -> str:
    player = npc_context["player"]
    name = player.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else player["id"]


def _derive_topic(player_utterance: str) -> str:
    text = _normalized_text(player_utterance)

    if "bjorn" in text and any(
        marker in text for marker in ("做什么", "职业", "occupation", "what does", "work")
    ):
        return "bjorn_occupation"
    if "bjorn" in text and any(marker in text for marker in ("国王", "king")):
        return "bjorn_identity_claim"
    if any(marker in text for marker in ("妻子", "丈夫", "wife", "husband", "spouse")):
        return "relationship_declaration"
    if any(marker in text for marker in ("海边", "海岸", "coast")) and any(
        marker in text for marker in ("奇怪", "异常", "不寻常", "strange", "unusual", "odd")
    ):
        return "coastal_strange_activity"
    if "skeld" in text and any(marker in text for marker in ("离开", "leave")):
        return "leaving_skeld"
    if "stormcliff" in text and any(
        marker in text for marker in ("准备", "打算", "计划", "去", "go", "travel", "intend", "plan")
    ):
        return "stormcliff_travel_plan"
    if text.strip("!！。,. ") in {"你好", "嗨", "hello", "hi", "hey"}:
        return "greeting"
    return "general_conversation"


def _is_question_without_assertion(player_utterance: str) -> bool:
    text = _normalized_text(player_utterance)
    assertion_markers = (
        "明明是国王",
        "is clearly the king",
        "is the king, right",
        "就是国王",
    )
    if any(marker in text for marker in assertion_markers):
        return False
    question_markers = (
        "?",
        "？",
        "吗",
        "什么",
        "怎么",
        "哪里",
        "哪儿",
        "是否",
        "how ",
        "what ",
        "where ",
        "who ",
        "why ",
        "is there",
        "do you know",
    )
    return any(marker in text for marker in question_markers)


def _has_planned_action(text: str) -> bool:
    chinese_action_markers = (
        "去",
        "前往",
        "出发",
        "离开",
        "寻找",
        "探索",
        "出海",
        "采集",
        "帮助",
        "拜访",
        "调查",
        "学习",
        "训练",
        "建造",
        "加入",
        "成为",
        "骑",
    )
    return any(marker in text for marker in chinese_action_markers) or (
        re.search(
            r"\b(?:go|travel|leave|depart|find|search|explore|sail|gather|help|"
            r"visit|investigate|learn|train|build|join|become|ride)\b",
            text,
        )
        is not None
    )


def _has_general_player_intention(text: str) -> bool:
    first_person = "我" in text or re.search(r"\b(?:i|i'm|i am)\b", text) is not None
    intention_markers = (
        "想",
        "希望",
        "打算",
        "准备",
        "计划",
        "要",
        "将",
        "i want",
        "i hope",
        "i plan",
        "i intend",
        "i will",
        "i am going to",
        "i'm going to",
    )
    future_time_markers = (
        "明天",
        "今晚",
        "明早",
        "以后",
        "将来",
        "tomorrow",
        "tonight",
        "this evening",
        "next morning",
        "in the future",
    )
    has_future_or_intention = any(
        marker in text for marker in (*intention_markers, *future_time_markers)
    )
    return first_person and has_future_or_intention and _has_planned_action(text)


def _extract_player_claims(
    npc_context: dict[str, Any],
    player_utterance: str,
) -> list[str]:
    """Record explicit claims as attributed speech, never as verified World Truth."""

    text = _normalized_text(player_utterance)
    player = _player_label(npc_context)

    if "bjorn" in text and any(marker in text for marker in ("国王", "king")):
        return [f"{player} claims that Bjorn is a king."]

    if any(marker in text for marker in ("妻子", "wife")) and any(
        marker in text for marker in ("你就是", "你是", "you are", "you're")
    ):
        npc_name = npc_context["npc"]["name"]
        return [f"{player} declares {npc_name} to be his wife."]

    if "stormcliff" in text and any(
        marker in text for marker in ("准备", "打算", "计划", "我要", "go", "travel", "intend", "plan")
    ):
        details = " alone" if any(marker in text for marker in ("一个人", "独自", "alone")) else ""
        timing = " tomorrow" if any(marker in text for marker in ("明天", "tomorrow")) else ""
        return [f"{player} intends to go to Stormcliff{details}{timing}."]

    if "skeld" in text and any(marker in text for marker in ("离开", "leave")):
        return [f"{player} intends to leave Skeld and explore the world beyond it."]

    if "stormcliff" in text and any(marker in text for marker in ("黑龙", "black dragon")) and any(
        marker in text for marker in ("有", "存在", "is at", "there is")
    ):
        return [f"{player} claims that a black dragon is at Stormcliff."]

    if _is_question_without_assertion(player_utterance):
        return []

    intention_markers = ("我想", "我希望", "我打算", "我准备", "我计划", "我要", "i want", "i hope", "i plan", "i intend")
    if any(marker in text for marker in intention_markers) or _has_general_player_intention(text):
        return [f'{player} states an intention: "{player_utterance.strip()}"']

    factual_claim_markers = ("我是", "我有", "我拥有", "其实是", "there is", "i am", "i have", "i own")
    if any(marker in text for marker in factual_claim_markers):
        return [f'{player} claims: "{player_utterance.strip()}"']

    return []


def _is_memory_candidate(
    player_utterance: str,
    player_claims: list[str],
) -> bool:
    text = _normalized_text(player_utterance)

    if _is_question_without_assertion(player_utterance):
        return False

    attributed_intention = any(
        " intends " in claim.casefold()
        or "states an intention" in claim.casefold()
        for claim in player_claims
    )
    explicit_player_intention = attributed_intention and _has_planned_action(text)
    major_commitment_or_conflict = any(
        marker in text
        for marker in (
            "我承诺",
            "我发誓",
            "重大计划",
            "我要杀",
            "我要攻击",
            "i promise",
            "i swear",
            "i will kill",
            "i will attack",
        )
    )
    return (
        explicit_player_intention
        or _has_general_player_intention(text)
        or major_commitment_or_conflict
    )


def _derive_relationship_signal(player_utterance: str) -> str:
    text = _normalized_text(player_utterance)
    negative_markers = (
        "我讨厌你",
        "我要杀了你",
        "我要攻击你",
        "hate you",
        "kill you",
        "attack you",
    )
    if any(marker in text for marker in negative_markers):
        return "potential_negative"

    positive_markers = (
        "谢谢你",
        "我信任你",
        "我愿意帮助你",
        "thank you",
        "i trust you",
        "i will help you",
    )
    if any(marker in text for marker in positive_markers):
        return "potential_positive"
    return "none"


def build_interaction_event(
    npc_context: dict[str, Any],
    player_utterance: str,
    npc_response: dict[str, Any],
    *,
    event_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one Interaction Event without reading or mutating World State."""

    if not isinstance(npc_context, dict):
        raise NpcInteractionEventError("npc_context must be a JSON object.")
    if not isinstance(npc_response, dict):
        raise NpcInteractionEventError("npc_response must be a JSON object.")
    if not isinstance(player_utterance, str) or not player_utterance.strip():
        raise NpcInteractionEventError("player_utterance must not be empty.")

    try:
        context_schema = load_context_schema()
        Draft202012Validator.check_schema(context_schema)
        Draft202012Validator(context_schema).validate(npc_context)
        validate_npc_response(npc_response, load_response_schema(), npc_context)
    except (SchemaError, ValidationError, NpcContextError, NpcResponseError) as exc:
        raise NpcInteractionEventError(
            f"Interaction Event input failed validation: {exc}"
        ) from exc

    if npc_context["shared_context"]["same_location"] is not True:
        raise NpcInteractionEventError(
            "NPC dialogue event requires player and NPC to be co-located."
        )

    player_claims = _extract_player_claims(npc_context, player_utterance)
    event = {
        "event_id": f"npc_event_{uuid.uuid4().hex}",
        "event_type": "npc_dialogue",
        "npc_id": npc_context["npc"]["id"],
        "player_id": npc_context["player"]["id"],
        "world_context": {
            "world_day": npc_context["shared_context"]["world_day"],
            "world_hour": npc_context["shared_context"]["world_hour"],
            "location_id": npc_context["runtime_state"]["current_location"],
        },
        "player_utterance": player_utterance,
        "npc_response": {
            "response_type": npc_response["response_type"],
            "speech": npc_response["speech"],
        },
        "topic": _derive_topic(player_utterance),
        "player_claims": player_claims,
        "memory_candidate": _is_memory_candidate(player_utterance, player_claims),
        "relationship_signal": _derive_relationship_signal(player_utterance),
    }
    validate_interaction_event(event, event_schema)
    return event
