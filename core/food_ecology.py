"""Small, grounded food ecology for hunting, village purchases, and dragons."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from typing import Any

from llm import LLMProviderClient, create_llm_client


FOODS: dict[str, tuple[str, tuple[str, ...]]] = {
    "fish": ("鲜鱼", ("鱼", "鲜鱼", "海鱼", "fish")),
    "mutton": ("羊肉", ("羊肉", "mutton", "sheep")),
    "goat": ("山羊肉", ("山羊", "山羊肉", "goat")),
    "venison": ("鹿肉", ("鹿", "鹿肉", "venison", "deer")),
    "rabbit": ("兔肉", ("兔", "兔肉", "rabbit")),
    "boar": ("野猪肉", ("野猪", "野猪肉", "boar")),
    "seabird": ("海鸟肉", ("海鸟", "海鸟肉", "seabird")),
}

HABITAT_FOOD: dict[str, tuple[str, ...]] = {
    "coast": ("fish", "seabird"),
    "cliff": ("goat", "mutton", "seabird"),
    "forest": ("venison", "rabbit", "boar"),
    "ruins": ("rabbit", "boar"),
    "wild": ("rabbit", "goat", "fish"),
}

FOOD_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["food_kind"],
    "properties": {"food_kind": {"type": "string", "enum": list(FOODS)}},
}


def food_action_kind(action: Mapping[str, Any]) -> str | None:
    text = " ".join(
        str(action.get(field) or "").casefold()
        for field in ("action", "target", "intent", "method")
    )
    if any(word in text for word in ("打猎", "狩猎", "捕猎", "猎取", "猎捕", "钓鱼", "捕鱼", "打鱼", "打渔", "hunt", "fish for")):
        return "hunt"
    if "打到" in text and mentioned_food_kind(text) is not None:
        return "hunt"
    if any(word in text for word in ("购买", "买", "购入", "buy", "purchase")):
        target = str(action.get("target") or "").strip().casefold()
        food_words = ("食物", "肉", "鱼", "猎物", "food", "meat", "fish")
        if target and not any(word in target for word in food_words):
            return None
        return "buy" if any(word in text for word in food_words) else None
    return None


def habitat_for_location(location_id: str, location: Mapping[str, Any] | None = None) -> str:
    if location_id == "skeld_village":
        return "coast"
    if location_id == "stormcliff":
        return "cliff"
    if location_id == "whispering_woods":
        return "forest"
    if location_id == "old_ruins":
        return "ruins"
    text = " ".join(
        str(value or "")
        for value in (
            (location or {}).get("name"),
            (location or {}).get("type"),
            (location or {}).get("description"),
            *((location or {}).get("environment_tags") or []),
        )
    ).casefold()
    if any(word in text for word in ("森林", "林地", "forest", "woods")):
        return "forest"
    if any(word in text for word in ("海", "湾", "岸", "coast", "bay")):
        return "coast"
    if any(word in text for word in ("崖", "山", "cliff", "mountain")):
        return "cliff"
    if any(word in text for word in ("遗迹", "废墟", "ruins")):
        return "ruins"
    return "wild"


def available_food(action_kind: str, location_id: str, location: Mapping[str, Any]) -> tuple[str, ...]:
    habitat = habitat_for_location(location_id, location)
    if action_kind == "hunt":
        return () if location.get("type") == "village" else HABITAT_FOOD[habitat]
    if action_kind == "buy" and location.get("type") == "village":
        return ("fish", "mutton", "rabbit")
    return ()


def mentioned_food_kind(text: str) -> str | None:
    lowered = text.casefold()
    matches = {
        kind
        for kind, (_, aliases) in FOODS.items()
        if any(alias.casefold() in lowered for alias in aliases)
    }
    # A specific animal wins over a generic ingredient (山羊肉 contains 羊肉).
    if "goat" in matches and "mutton" in matches:
        matches.remove("mutton")
    if "seabird" in matches and "fish" in matches and "海鱼" not in lowered:
        matches.remove("fish")
    return next(iter(matches)) if len(matches) == 1 else None


def explicit_food_candidate(
    action: Mapping[str, Any],
    *,
    location_id: str,
    location: Mapping[str, Any],
) -> dict[str, str] | None:
    """Ground named food without a model call or random selection."""

    kind = food_action_kind(action)
    if kind is None:
        return None
    allowed = available_food(kind, location_id, location)
    text = " ".join(str(action.get(field) or "") for field in ("action", "target", "intent", "method"))
    target = action.get("target")
    if isinstance(target, str) and any(word in target for word in ("皮", "角", "骨", "毛")):
        return None
    requested = mentioned_food_kind(text)
    if requested not in allowed:
        return None
    return {"food_kind": requested, "name": FOODS[requested][0]}


def choose_food_candidate(
    action: Mapping[str, Any],
    *,
    location_id: str,
    location: Mapping[str, Any],
    provider_client: LLMProviderClient | None = None,
) -> dict[str, str] | None:
    """Let the model select a local candidate; only the habitat allowlist is truth."""

    kind = food_action_kind(action)
    if kind is None:
        return None
    allowed = available_food(kind, location_id, location)
    if not allowed:
        return None
    text = " ".join(str(action.get(field) or "") for field in ("action", "target", "intent", "method"))
    target = action.get("target")
    if isinstance(target, str) and any(word in target for word in ("皮", "角", "骨", "毛")):
        return None
    requested = mentioned_food_kind(text)
    if requested is not None:
        return explicit_food_candidate(action, location_id=location_id, location=location)
    if isinstance(target, str) and target.strip() and target.strip() not in {
        "食物", "肉", "肉食", "猎物", "野味", "动物", "一份食物", "一份肉食",
    }:
        return None
    if any(word in text.casefold() for word in ("人肉", "人类", "村民", "human", "person")):
        return None
    if any(alias in text.casefold() for _, aliases in FOODS.values() for alias in aliases):
        return None  # Ambiguous or unavailable named prey never turns into random food.
    selected: str | None = None
    try:
        client = provider_client or create_llm_client()
        candidate = json.loads(client.create_structured_output(
                system_prompt=(
                    "Select one plausible food_kind from allowed_food for this location. "
                    "Return only JSON. Do not decide whether hunting or purchase succeeds."
                ),
                user_message=json.dumps({
                    "action": kind,
                    "location": location.get("name"),
                    "habitat": habitat_for_location(location_id, location),
                    "allowed_food": list(allowed),
                }, ensure_ascii=False),
                schema=FOOD_CANDIDATE_SCHEMA,
                schema_name="food_candidate",
        ))
        if isinstance(candidate, dict) and candidate.get("food_kind") in allowed:
            selected = candidate["food_kind"]
    except Exception:
        # A provider outage cannot invent food or block this bounded PoC action.
        pass
    selected = selected or random.SystemRandom().choice(allowed)
    return {"food_kind": selected, "name": FOODS[selected][0]}


def favorite_food_kind(dragon: Mapping[str, Any]) -> str:
    """Stable individual preference, anchored to habitat and Dragon identity."""

    habitat = habitat_for_location(
        str(dragon.get("habitat_location") or dragon.get("current_location") or "")
    )
    choices = HABITAT_FOOD[habitat]
    identity = str(dragon.get("dragon_id") or dragon.get("name") or "dragon")
    roll = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16)
    # A rare large dragon near ruins may prefer human prey, but the player
    # cannot obtain or trade people through this food system.
    if habitat == "ruins" and dragon.get("archetype_id") == "powerful_wild" and roll % 5 == 0:
        return "human"
    return choices[roll % len(choices)]


_NON_FOOD_ITEM_MARKERS = ("骨", "皮", "毛", "角", "竿", "钩", "饵", "油", "模型", "标本", "画像", "玩具", "雕像")


def _inventory_food_kind(item: Mapping[str, Any]) -> str | None:
    category = item.get("category", item.get("type"))
    if category not in {None, "food"}:
        return None
    kind = item.get("food_kind")
    if category == "food" and isinstance(kind, str) and kind in FOODS:
        return kind
    name = item.get("name")
    if not isinstance(name, str):
        return "generic" if category == "food" else None
    if any(marker in name for marker in _NON_FOOD_ITEM_MARKERS):
        return None
    # Older portable-item actions stored edible catches without food metadata.
    # Accept only a uniquely recognizable meat/fish name, never a bare claim.
    return mentioned_food_kind(name) or ("generic" if category == "food" else None)


def select_food_item(inventory: Sequence[Any], action: Mapping[str, Any]) -> Mapping[str, Any] | None:
    foods = [
        item for item in inventory
        if isinstance(item, Mapping)
        and _inventory_food_kind(item) is not None
        and isinstance(item.get("quantity", 1), int)
        and not isinstance(item.get("quantity", 1), bool)
        and item.get("quantity", 1) > 0
    ]
    text = " ".join(str(action.get(field) or "") for field in ("action", "intent", "method"))
    wanted = mentioned_food_kind(text)
    if wanted is not None:
        foods = [item for item in foods if _inventory_food_kind(item) == wanted]
    return foods[0] if len(foods) == 1 else None
