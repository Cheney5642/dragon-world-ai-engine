"""Deterministic, read-only Identity Grounding v0.1.

The LLM-backed B1 Interpreter explains what the player expressed. This module
is the smaller World Truth boundary: it accepts ordinary self-identity
candidates and preserves authority, relationship, Dragon, and historical
claims as unverified. It never calls an LLM or mutates state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROUNDING_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "identity_grounding.schema.json"
)


class IdentityGroundingError(Exception):
    """Raised when a valid deterministic Grounding Result cannot be produced."""


_EXTERNAL_FACT_PATTERNS = (
    # High authority, divinity, bloodline, and major status.
    "国王",
    "王子",
    "皇帝",
    "神明",
    "神祇",
    "神性",
    "天选",
    "统治者",
    "龙王",
    "世界闻名",
    "传奇英雄",
    "屠龙者",
    "特殊血统",
    "king",
    "prince",
    "emperor",
    "god",
    "divine",
    "chosen ruler",
    "ruler of skeld",
    "owner of a kingdom",
    "dragon king",
    "world-famous hero",
    "legendary hero",
    "dragon slayer",
    "special bloodline",
    # Existing external relationships and history.
    "深爱我",
    "爱着我",
    "我的妻子",
    "我的丈夫",
    "我的父亲",
    "我的母亲",
    "从小一起长大",
    "长期挚友",
    "世代仇敌",
    "共同经历过",
    "longtime friend",
    "has always loved",
    "my wife",
    "my husband",
    "my father",
    "my mother",
    # Dragon ownership, taming, Bond, riding, and submission.
    "臣服于我",
    "属于我",
    "被我驯服",
    "与我建立羁绊",
    "接受我骑乘",
    "骑过这条龙",
    "obey me",
    "belongs to me",
    "tamed by me",
    "bonded with me",
    "accepted me as rider",
    "all dragons obey",
    # World ownership and major historical outcome.
    "拥有这座",
    "建立了这座",
    "摧毁了遗迹",
    "赢得了战争",
    "改变了世界",
    "owns this",
    "founded this",
    "destroyed the ruins",
    "won the war",
    "changed the world",
    # Explicit collisions with the frozen pre-industrial World Rules.
    "ak47",
    "现代枪械",
    "突击步枪",
    "手机",
    "汽车",
    "天生会飞",
    "modern firearm",
    "assault rifle",
    "mobile phone",
    "smartphone",
    "a car",
    "cars",
    "fly naturally",
    "world-destroying power",
    "毁灭世界的力量",
)

_UNSUPPORTED_TRAIT_PATTERNS = (
    "全能",
    "无敌",
    "神级",
    "世界最强",
    "omnipotent",
    "invincible",
    "godlike",
    "world's strongest",
)

_UNSUPPORTED_CAPABILITY_PATTERNS = (
    "master",
    "elite",
    "expert",
    "legendary",
    "world_destroying",
    "world-destroying",
    "godlike",
    "superpower",
    "天生飞行",
    "毁灭世界",
    "大师",
    "宗师",
    "无敌",
    "超能力",
)


def load_identity_grounding_schema(
    path: Path = GROUNDING_SCHEMA_PATH,
) -> dict[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityGroundingError(
            f"Identity Grounding Schema is not valid readable JSON: {path}"
        ) from exc
    if not isinstance(schema, dict):
        raise IdentityGroundingError(
            "Identity Grounding Schema must contain a JSON object."
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise IdentityGroundingError(
            f"Identity Grounding Schema is invalid: {exc.message}"
        ) from exc
    return schema


def validate_identity_grounding(
    result: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    schema = schema or load_identity_grounding_schema()
    try:
        Draft202012Validator(schema).validate(result)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise IdentityGroundingError(
            f"Identity Grounding failed Schema validation at "
            f"'{location}': {exc.message}"
        ) from exc


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("_", " ")).strip()


def _contains_any(value: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalized(value)
    return any(_normalized(pattern) in normalized for pattern in patterns)


def _unique_strings(values: Any, field: str) -> list[str]:
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise IdentityGroundingError(f"{field} must be an array of non-empty strings.")
    return list(dict.fromkeys(value.strip() for value in values))


def ground_identity(
    interpretation: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ground one frozen B1 interpretation without LLM or state access."""

    if not isinstance(interpretation, dict):
        raise IdentityGroundingError("Identity Interpretation must be an object.")

    facts = _unique_strings(interpretation.get("candidate_facts"), "candidate_facts")
    claims = _unique_strings(
        interpretation.get("candidate_claims"),
        "candidate_claims",
    )
    traits = _unique_strings(interpretation.get("traits"), "traits")
    hints = _unique_strings(
        interpretation.get("capability_hints"),
        "capability_hints",
    )

    accepted_facts: list[str] = []
    unverified_claims: list[str] = list(claims)
    accepted_traits: list[str] = []
    accepted_hints: list[str] = []
    notes: list[str] = []

    for fact in facts:
        if _contains_any(fact, _EXTERNAL_FACT_PATTERNS):
            unverified_claims.append(fact)
            notes.append(
                f"Candidate fact requires external World Evidence and remains "
                f"unverified: {fact}"
            )
        else:
            accepted_facts.append(fact)

    for trait in traits:
        if _contains_any(trait, _UNSUPPORTED_TRAIT_PATTERNS):
            unverified_claims.append(f"Claimed extraordinary trait: {trait}")
            notes.append(f"Extraordinary trait was not accepted: {trait}")
        else:
            accepted_traits.append(trait)

    for hint in hints:
        if _contains_any(hint, _UNSUPPORTED_CAPABILITY_PATTERNS):
            unverified_claims.append(f"Claimed capability requires evidence: {hint}")
            notes.append(f"Extraordinary capability hint was not accepted: {hint}")
        else:
            accepted_hints.append(hint)

    accepted_facts = list(dict.fromkeys(accepted_facts))
    unverified_claims = list(dict.fromkeys(unverified_claims))
    accepted_traits = list(dict.fromkeys(accepted_traits))
    accepted_hints = list(dict.fromkeys(accepted_hints))

    if accepted_facts:
        notes.insert(
            0,
            f"Accepted {len(accepted_facts)} ordinary self-identity candidate "
            "fact(s).",
        )
    if unverified_claims:
        notes.append(
            f"Preserved {len(unverified_claims)} claim(s) as unverified pending "
            "Grounded World Evidence."
        )
    if not accepted_facts and not unverified_claims:
        notes.append("No candidate facts or claims required classification.")

    result = {
        "accepted_facts": accepted_facts,
        "unverified_claims": unverified_claims,
        "accepted_traits": accepted_traits,
        "accepted_capability_hints": accepted_hints,
        "grounding_notes": notes,
    }
    validate_identity_grounding(result, schema)
    return result
