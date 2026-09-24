"""D7 first-person scene renderer built only from committed World Truth."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from openai import OpenAI

from database.connection import ENV_PATH


logger = logging.getLogger(__name__)


class SceneImageProvider(Protocol):
    name: str
    enabled: bool

    def generate(self, prompt: str) -> str:
        """Return one remote HTTPS image reference."""


@dataclass(frozen=True)
class DisabledSceneImageProvider:
    reason: str
    name: str = "disabled"
    enabled: bool = False

    def generate(self, prompt: str) -> str:
        raise RuntimeError(self.reason)


@dataclass(frozen=True)
class DoubaoSceneImageProvider:
    model: str
    size: str
    timeout: float
    base_url: str
    _client: OpenAI
    name: str = "doubao"
    enabled: bool = True

    def generate(self, prompt: str) -> str:
        response = self._client.images.generate(
            model=self.model,
            prompt=prompt,
            size=self.size,
            response_format="url",
        )
        data = getattr(response, "data", None)
        image_url = getattr(data[0], "url", None) if data else None
        if not isinstance(image_url, str) or not image_url.startswith(
            ("https://", "http://")
        ):
            raise RuntimeError("Image Provider returned no remote image URL.")
        return image_url


def create_scene_image_provider() -> SceneImageProvider:
    """Create the one configured renderer, or an explicit disabled provider."""

    load_dotenv(ENV_PATH)
    provider = os.getenv("IMAGE_PROVIDER", "doubao").strip().lower()
    if provider != "doubao":
        return DisabledSceneImageProvider("Unsupported image provider.")
    api_key = os.getenv("ARK_API_KEY", "").strip()
    model = os.getenv("ARK_IMAGE_MODEL", "").strip()
    if not api_key or not model:
        return DisabledSceneImageProvider(
            "ARK_API_KEY or ARK_IMAGE_MODEL is not configured."
        )
    base_url = os.getenv(
        "ARK_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3",
    ).strip()
    size = os.getenv("ARK_IMAGE_SIZE", "1024x1024").strip() or "1024x1024"
    timeout = float(os.getenv("ARK_IMAGE_TIMEOUT", "120").strip() or "120")
    return DoubaoSceneImageProvider(
        model=model,
        size=size,
        timeout=timeout,
        base_url=base_url,
        _client=OpenAI(api_key=api_key, base_url=base_url, timeout=timeout),
    )


def _provider_error_diagnostics(exc: Exception) -> dict[str, Any]:
    """Extract safe Ark error metadata without credentials or request content."""

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    body = getattr(exc, "body", None)
    error_body = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error_body, dict):
        error_body = body if isinstance(body, dict) else {}

    def header(name: str) -> str | None:
        if headers is None or not hasattr(headers, "get"):
            return None
        value = headers.get(name)
        return str(value) if value else None

    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(response, "status_code", None)
    return {
        "exception_type": type(exc).__name__,
        "status_code": status_code,
        "provider_code": error_body.get("code") or getattr(exc, "code", None),
        "provider_message": error_body.get("message")
        or getattr(exc, "message", None),
        "request_id": getattr(exc, "request_id", None)
        or error_body.get("request_id")
        or header("x-request-id")
        or header("x-tt-logid"),
    }


def _safe_base_url(value: Any) -> str | None:
    """Keep endpoint identity while dropping credentials, query, and fragment."""

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "<invalid>"


def visual_trigger(action_result: Mapping[str, Any]) -> str | None:
    """Select grounded moments worth illustrating."""

    riding = action_result.get("dragon_riding")
    if isinstance(riding, Mapping) and riding.get("status") in {
        "success",
        "already_applied",
    }:
        if riding.get("reason_code") == "riding_arrived":
            return "mounted_travel_arrival"
        if riding.get("reason_code") == "riding_mounted":
            return "dragon_mount"
    discovery = action_result.get("location_discovery")
    if isinstance(discovery, Mapping):
        return "dynamic_location_discovery"
    encounter = action_result.get("dragon_encounter")
    if isinstance(encounter, Mapping) and encounter.get("outcome") in {
        "sighting",
        "direct_encounter",
    }:
        return "dragon_encounter"
    interaction = action_result.get("dragon_interaction")
    if (
        isinstance(interaction, Mapping)
        and interaction.get("status") in {"applied", "already_applied"}
        and interaction.get("interaction_type") == "observe"
        and isinstance(interaction.get("dragon_id"), str)
    ):
        return "dragon_observation"
    update = action_result.get("story_update")
    if isinstance(update, Mapping) and update.get("status") == "recorded" and update.get("event"):
        return "personal_story_event"
    return None


def build_visual_context(
    *,
    trigger: str,
    world: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a renderer-only snapshot from the formal /api/world read model."""

    location = world.get("current_location")
    world_info = world.get("world")
    riding = world.get("riding")
    dragons = world.get("nearby_dragons")
    if not isinstance(location, Mapping) or not isinstance(world_info, Mapping):
        raise ValueError("Visual Context requires formal World and Location truth.")
    if not isinstance(riding, Mapping):
        riding = {}
    if not isinstance(dragons, list):
        dragons = []
    is_mounted = riding.get("is_mounted") is True
    camera = "first_person_dragon_back" if is_mounted else "first_person"
    return {
        "camera": camera,
        "event_type": trigger,
        "player_location": {
            "location_id": location.get("id"),
            "name": location.get("name"),
            "location_type": location.get("type"),
            "description": location.get("description"),
        },
        "weather": world_info.get("weather"),
        "world_day": world_info.get("day"),
        "world_hour": world_info.get("hour"),
        "dragon_presence": [
            {
                "dragon_id": dragon.get("dragon_id"),
                "name": dragon.get("name"),
                "appearance": dragon.get("appearance", {}),
                "behavior_state": dragon.get("behavior_state"),
                "taming_state": dragon.get("taming_state"),
            }
            for dragon in dragons
            if isinstance(dragon, Mapping)
        ],
        "mounted_state": {
            "is_mounted": is_mounted,
            "mounted_dragon_id": riding.get("mounted_dragon_id"),
            "mounted_dragon_name": riding.get("mounted_dragon_name"),
        },
    }


def build_visual_prompt(context: Mapping[str, Any]) -> str:
    """Translate grounded context into a first-person cinematic prompt."""

    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if context.get("event_type") == "dragon_observation":
        return (
            "Dragon World first-person dragon observation portrait. Show only "
            "the one grounded dragon in dragon_presence, matching its exact "
            "appearance. Keep the background neutral and unobtrusive so this "
            "dragon's likeness can be reused at another location. No invented "
            "people, dragons, text, HUD, captions, or logos. "
            f"Grounded visual context: {context_json}"
        )
    return (
        "Dragon World v0.1 cinematic game scene. Render only the supplied "
        "grounded context. Do not invent people, dragons, buildings, ownership, "
        "quests, or events. No text, HUD, captions, logos, or third-person rider. "
        "Respect the exact camera field; first_person_dragon_back may show the "
        "dragon's neck, scales, wings, and the rider's hands, but never the "
        f"rider's face. Grounded visual context: {context_json}"
    )


def render_scene_visual(
    *,
    action_result: Mapping[str, Any],
    world: Mapping[str, Any],
    provider: SceneImageProvider,
    image_cache: MutableMapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Render a presentation result; all failures remain non-gameplay failures."""

    trigger = visual_trigger(action_result)
    if trigger is None:
        return None
    context = build_visual_context(trigger=trigger, world=world)
    if trigger == "dragon_observation":
        interaction = action_result["dragon_interaction"]
        dragon_id = interaction["dragon_id"]
        observed = [
            dragon for dragon in context["dragon_presence"]
            if dragon["dragon_id"] == dragon_id
        ]
        if len(observed) != 1:
            raise ValueError("Observed Dragon is absent from the formal World snapshot.")
        context = {
            "camera": "first_person",
            "event_type": trigger,
            "dragon_presence": [{
                "dragon_id": observed[0]["dragon_id"],
                "name": observed[0]["name"],
                "appearance": observed[0]["appearance"],
            }],
        }
    story_event = (action_result.get("story_update") or {}).get("event")
    if story_event and trigger != "dragon_observation":
        # Semantic wishes/claims are deliberately not sent to the image model.
        context["event"] = {
            "event_id": story_event["event_id"], "event_type": story_event["event_type"],
            "location_id": story_event["location"]["id"],
            "visible_npcs": [entity for entity in story_event["involved_entities"]
                             if entity["id"] in {npc["id"] for npc in world.get("nearby_npcs", [])}],
        }
    prompt = build_visual_prompt(context)
    context_hash = hashlib.sha256(
        json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    base = {
        "trigger": trigger,
        "provider": provider.name,
        "context_hash": context_hash,
        "camera": context["camera"],
        "image_url": None,
        "scene_description": context,
        "image_prompt": prompt,
    }
    if trigger == "dragon_observation" and image_cache is not None:
        cached_url = image_cache.get(context_hash)
        if cached_url:
            return {**base, "status": "generated", "image_url": cached_url, "reused": True}
    if not provider.enabled:
        return {**base, "status": "disabled"}
    try:
        image_url = provider.generate(prompt)
    except Exception as exc:
        diagnostics = _provider_error_diagnostics(exc)
        logger.error(
            "scene_image_provider_failed exception_type=%s http_status=%s "
            "ark_error_code=%s ark_error_message=%r request_id=%s model=%s "
            "size=%s timeout=%s base_url=%s",
            diagnostics["exception_type"],
            diagnostics["status_code"],
            diagnostics["provider_code"],
            diagnostics["provider_message"],
            diagnostics["request_id"],
            getattr(provider, "model", None),
            getattr(provider, "size", None),
            getattr(provider, "timeout", None),
            _safe_base_url(getattr(provider, "base_url", None)),
        )
        return {**base, "status": "failed"}
    if trigger == "dragon_observation" and image_cache is not None:
        image_cache[context_hash] = image_url
        while len(image_cache) > 64:
            image_cache.pop(next(iter(image_cache)))
    return {**base, "status": "generated", "image_url": image_url, "reused": False}
