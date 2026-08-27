"""Deterministic, read-only Top-K retrieval for Persistent NPC Memory v0.1."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from npc.memory import MEMORY_STORE_PATH, load_memory_store, validate_memory_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECALL_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "npc_memory_recall_context.schema.json"
)
MAX_RETRIEVAL_LIMIT = 3
MIN_RELEVANCE_SCORE = 1.5


class NpcMemoryRetrievalError(Exception):
    """Raised when a safe, schema-valid Recall Context cannot be produced."""


def load_memory_recall_schema(
    path: Path = RECALL_SCHEMA_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise NpcMemoryRetrievalError(
            f"NPC Memory Recall Context Schema does not exist: {path}"
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcMemoryRetrievalError(
            f"NPC Memory Recall Context Schema is not valid JSON: {path}"
        ) from exc
    if not isinstance(schema, dict):
        raise NpcMemoryRetrievalError(
            "NPC Memory Recall Context Schema must be a JSON object."
        )
    return schema


def validate_memory_recall_context(
    recall_context: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_memory_recall_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(recall_context)
    except (SchemaError, ValidationError) as exc:
        raise NpcMemoryRetrievalError(
            f"NPC Memory Recall Context failed JSON Schema validation: {exc.message}"
        ) from exc


_ENGLISH_CANONICAL = {
    "intends": "plan",
    "intend": "plan",
    "intention": "plan",
    "plans": "plan",
    "planned": "plan",
    "planning": "plan",
    "wants": "plan",
    "want": "plan",
    "leaving": "leave",
    "left": "leave",
    "exploring": "explore",
    "explores": "explore",
    "travels": "travel",
    "travelled": "travel",
    "going": "travel",
    "goes": "travel",
    "went": "visited",
    "visited": "visited",
    "remembered": "recall",
    "remember": "recall",
    "said": "recall",
    "told": "recall",
    "claims": "claim",
    "claimed": "claim",
    "king": "king",
    "blacksmith": "blacksmith",
}

_PHRASE_CONCEPTS = (
    (("stormcliff",), "stormcliff"),
    (("skeld",), "skeld"),
    (("bjorn",), "bjorn"),
    (("离开",), "leave"),
    (("探索", "外面的世界", "外面世界"), "explore"),
    (("准备", "打算", "计划", "想要", "我想"), "plan"),
    (("一个人", "独自"), "alone"),
    (("明天",), "tomorrow"),
    (("去过", "已经去", "曾经去"), "visited"),
    (("去哪里", "去哪", "哪儿", "哪里"), "location_query"),
    (("去", "前往"), "travel"),
    (("记得", "之前说过", "以前说过"), "recall"),
    (("国王",), "king"),
    (("铁匠",), "blacksmith"),
    (("做什么", "职业"), "occupation"),
    (("声称", "说自己", "说过"), "claim"),
    (("龙",), "dragon"),
)

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "beyond",
    "did",
    "do",
    "eirik",
    "he",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "player",
    "said",
    "that",
    "the",
    "to",
    "was",
    "what",
    "you",
}


def _canonical_terms(text: str) -> set[str]:
    normalized = re.sub(r"[_\-]+", " ", text.casefold())
    terms: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", normalized):
        canonical = _ENGLISH_CANONICAL.get(word, word)
        if canonical not in _STOP_WORDS and len(canonical) > 1:
            terms.add(canonical)
    for phrases, concept in _PHRASE_CONCEPTS:
        if any(phrase in normalized for phrase in phrases):
            terms.add(concept)
    return terms


def _memory_location_terms(memory: dict[str, Any]) -> set[str]:
    terms = _canonical_terms(memory["content"])
    terms.update(_canonical_terms(memory["created_from_topic"]))
    terms.update(_canonical_terms(memory["world_context"]["location_id"]))
    return terms.intersection({"stormcliff", "skeld"})


def _recency_bonus(
    memory: dict[str, Any],
    current_world_context: dict[str, Any],
    source_index: int,
) -> float:
    current_day = current_world_context["world_day"]
    current_hour = current_world_context["world_hour"]
    memory_day = memory["world_context"]["world_day"]
    memory_hour = memory["world_context"]["world_hour"]
    age_hours = max(0, (current_day - memory_day) * 24 + current_hour - memory_hour)
    time_bonus = max(0.0, 0.5 - min(age_hours, 120) / 240)
    order_bonus = min(source_index, 999) / 1_000_000
    return time_bonus + order_bonus


def _score_memory(
    memory: dict[str, Any],
    utterance_terms: set[str],
    current_world_context: dict[str, Any],
    source_index: int,
) -> float:
    memory_terms = _canonical_terms(memory["content"])
    topic_terms = _canonical_terms(memory["created_from_topic"])
    all_memory_terms = memory_terms | topic_terms
    overlap = utterance_terms & all_memory_terms

    high_value_terms = {
        "bjorn",
        "blacksmith",
        "dragon",
        "king",
        "leave",
        "skeld",
        "stormcliff",
    }
    score = sum(3.0 if term in high_value_terms else 1.5 for term in overlap)
    score += 0.75 * len(utterance_terms & topic_terms)

    if "location_query" in utterance_terms and memory["memory_type"] == "player_intention":
        if _memory_location_terms(memory):
            score += 1.0
    if "visited" in utterance_terms and memory["memory_type"] == "player_intention":
        score += 1.0
    if "claim" in utterance_terms and memory["memory_type"] == "player_claim":
        score += 0.75
    if score > 0:
        score += _recency_bonus(memory, current_world_context, source_index)
    return round(score, 6)


def _validate_request(
    npc_id: str,
    player_id: str,
    player_utterance: str,
    current_world_context: dict[str, Any],
    limit: int,
) -> None:
    if not isinstance(npc_id, str) or not npc_id.startswith("npc_"):
        raise NpcMemoryRetrievalError("npc_id must be a valid NPC Entity ID.")
    if not isinstance(player_id, str) or not player_id:
        raise NpcMemoryRetrievalError("player_id must be a non-empty string.")
    if not isinstance(player_utterance, str) or not player_utterance.strip():
        raise NpcMemoryRetrievalError("player_utterance must not be empty.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3:
        raise NpcMemoryRetrievalError("limit must be an integer from 1 to 3.")
    if not isinstance(current_world_context, dict):
        raise NpcMemoryRetrievalError("current_world_context must be an object.")
    required = {"world_day", "world_hour", "location_id"}
    if not required.issubset(current_world_context):
        raise NpcMemoryRetrievalError(
            "current_world_context requires world_day, world_hour, and location_id."
        )
    day = current_world_context["world_day"]
    hour = current_world_context["world_hour"]
    location_id = current_world_context["location_id"]
    if not isinstance(day, int) or isinstance(day, bool) or day < 1:
        raise NpcMemoryRetrievalError("current world_day must be a positive integer.")
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        raise NpcMemoryRetrievalError("current world_hour must be from 0 to 23.")
    if not isinstance(location_id, str) or not location_id:
        raise NpcMemoryRetrievalError("current location_id must be non-empty.")


def retrieve_relevant_memories(
    npc_id: str,
    player_id: str,
    player_utterance: str,
    current_world_context: dict[str, Any],
    limit: int = MAX_RETRIEVAL_LIMIT,
    *,
    store_path: Path = MEMORY_STORE_PATH,
    store_document: dict[str, Any] | None = None,
    recall_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a schema-valid 0..3 Memory Recall Context without mutating inputs."""

    _validate_request(
        npc_id,
        player_id,
        player_utterance,
        current_world_context,
        limit,
    )
    if store_document is None:
        store = load_memory_store(store_path)
    else:
        store = copy.deepcopy(store_document)
        validate_memory_store(store)

    utterance_terms = _canonical_terms(player_utterance)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for source_index, memory in enumerate(store["memories"]):
        if memory["npc_id"] != npc_id or memory["player_id"] != player_id:
            continue
        score = _score_memory(
            memory,
            utterance_terms,
            current_world_context,
            source_index,
        )
        if score >= MIN_RELEVANCE_SCORE:
            scored.append((score, source_index, memory))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]["memory_id"]))
    retrieved = []
    for score, _, memory in scored[:limit]:
        retrieved.append(
            {
                "memory_id": memory["memory_id"],
                "memory_type": memory["memory_type"],
                "content": memory["content"],
                "epistemic_status": memory["epistemic_status"],
                "world_context": copy.deepcopy(memory["world_context"]),
                "created_from_topic": memory["created_from_topic"],
                "relevance_score": score,
            }
        )

    recall_context = {
        "npc_id": npc_id,
        "player_id": player_id,
        "retrieved_memories": retrieved,
    }
    validate_memory_recall_context(recall_context, recall_schema)
    return recall_context
