"""FastAPI bridge for the Dragon World core action pipeline."""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from api.npc_api import register_npc_routes
from core import action_pipeline
from core.free_action_interpreter import (
    ActionInterpretationError as FreeActionInterpretationError,
    interpret_action as interpret_free_action,
)
from core.free_action_resolution import (
    ActionResolutionError,
    commit_action_resolution,
    load_runtime_world_skeleton,
)
from core.dragon_encounter_decision import (
    EncounterDecisionError,
    decide_current_dragon_encounter,
)
from database.connection import (
    DatabaseConfigurationError,
    create_database_engine,
    create_session_factory,
)
from database.persistence import (
    PersistenceMappingError,
    PostgresPersistenceAdapter,
)
from identity.commit import (
    ControlledIdentityCommitError,
    commit_initial_identity,
)
from identity.grounding import IdentityGroundingError, ground_identity
from identity.interpreter import (
    IdentityInterpretationError,
    interpret_identity,
)
from identity.runtime_context import (
    PlayerIdentityRuntimeError,
    build_legacy_player_identity_read_model,
    build_player_identity_read_model,
)
from dragon.candidate_runtime import (
    DragonCandidateError,
    commit_new_dragon_encounter,
)
from core.location_discovery import (
    LocationDiscoveryError,
    generate_location_candidate,
    ground_location_candidate,
    is_location_discovery_eligible,
)
from llm import LLMProviderClient, LLMProviderError
from npc.interaction_runtime import StructuredOutputProvider
from scripts import execute_action
from scripts import interpret_action
from scripts import validate_action


logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORLD_SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"


class ActionRequest(BaseModel):
    """Untrusted frontend input; mutations are intentionally not accepted."""

    model_config = ConfigDict(extra="forbid")

    input: str


class FreeActionExecuteRequest(BaseModel):
    """Untrusted D2 input; resolved state changes are never accepted."""

    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(max_length=128)
    player_input: str = Field(max_length=4000)


class IdentityInitializeRequest(BaseModel):
    """Free-form identity input; derived identity fields are never accepted."""

    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(max_length=128)
    self_description: str = Field(max_length=4000)


class IdentityInitializeResponse(BaseModel):
    """Minimal public result read back from PostgreSQL Runtime Identity."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["initialized", "already_initialized"]
    player_id: str
    display_name: str | None
    identity_initialized: bool
    identity_summary: str


def _identity_error_detail(
    kind: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {"error_type": kind, "code": code, "message": message}


def _identity_business_error(
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_identity_error_detail("business_rejection", code, message),
    )


def _identity_system_error(
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_identity_error_detail("system_error", code, message),
    )


def build_world_summary(world_state: dict[str, Any]) -> dict[str, Any]:
    """Return only the public fields required by the v0.1 demo UI."""

    player = world_state["player"]
    identity = player.get("identity")
    if not isinstance(identity, dict):
        identity = build_legacy_player_identity_read_model(player)
    world = world_state["world"]
    locations = world_state["locations"]
    current_location_id = player.get("current_location")
    current_location = locations.get(current_location_id)
    if not isinstance(current_location, dict):
        raise interpret_action.ActionInterpretationError(
            "Player current_location is not present in the current Save."
        )

    nearby_npcs = []
    for npc in world_state["npcs"].values():
        if not isinstance(npc, dict):
            continue
        if npc.get("current_location") != current_location_id:
            continue
        nearby_npcs.append(
            {
                "id": npc.get("id"),
                "name": npc.get("name"),
                "species": npc.get("species"),
                "occupation": npc.get("occupation"),
            }
        )

    nearby_dragons = []
    for dragon in world_state.get("nearby_dragons", []):
        if not isinstance(dragon, dict):
            continue
        nearby_dragons.append(_public_dragon_summary(dragon))

    return {
        "player": {
            "id": player.get("id"),
            "player_id": player.get("id"),
            "name": player.get("name"),
            "display_name": identity["display_name"],
            "species": player.get("species"),
            "occupation": player.get("occupation"),
            "current_location": current_location_id,
            "goals": player.get("goals", []),
            "inventory": player.get("inventory", []),
            "identity_initialized": identity["identity_initialized"],
            "identity_label": identity["identity_label"],
            "identity_summary": identity["identity_summary"],
        },
        "world": {
            "name": world.get("name"),
            "day": world.get("day"),
            "hour": world.get("hour"),
            "weather": world.get("weather"),
        },
        "current_location": {
            "id": current_location_id,
            "name": current_location.get("name"),
            "type": current_location.get("type"),
            "description": current_location.get("description"),
        },
        "nearby_npcs": nearby_npcs,
        "nearby_dragons": nearby_dragons,
    }


def _public_dragon_summary(dragon: dict[str, Any]) -> dict[str, Any]:
    return {
        "dragon_id": dragon.get("dragon_id"),
        "name": dragon.get("name"),
        "appearance": copy.deepcopy(dragon.get("appearance", {})),
        "personality_traits": list(dragon.get("temperament_traits", [])),
        "behavior_state": dragon.get("behavior_state"),
        "taming_state": dragon.get("taming_state"),
        "location": dragon.get("current_location"),
        "player_relationship": copy.deepcopy(
            dragon.get("player_relationship")
        ),
    }


def _location_discovery_response(commit_result: Mapping[str, Any]) -> dict[str, Any]:
    location = commit_result.get("location")
    if not isinstance(location, Mapping):
        raise LocationDiscoveryError("Committed Location could not be read back.")
    return {
        "status": commit_result["status"],
        "location_id": location["location_id"],
        "name": location["name"],
        "location_type": location["location_type"],
        "short_description": location["short_description"],
        "environment_tags": list(location["environment_tags"]),
        "discovery_reason": location["discovery_reason"],
    }


def _location_discovery_player_message(discovery: Mapping[str, Any]) -> str:
    return (
        f"你发现了新的地点：{discovery['name']}。"
        f"{discovery['short_description']}"
    )


def _load_legacy_fixture_world(save_path: Path) -> dict[str, Any]:
    """Load an explicitly injected JSON fixture; production never calls this."""

    if not save_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No current Dragon World save found.",
        )
    try:
        return interpret_action.load_current_world(save_path)
    except interpret_action.NoPlayerError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "No player exists in the current Dragon World save. "
                "Create and commit a player first."
            ),
        ) from exc


def _load_postgres_world(
    persistence: PostgresPersistenceAdapter,
) -> dict[str, Any]:
    """Compose Runtime World Context from config plus PostgreSQL current state."""

    try:
        world_state = load_runtime_world_skeleton(
            persistence,
            WORLD_SEED_PATH,
        )
        seed_player = world_state.get("player")
        if not isinstance(seed_player, dict):
            raise interpret_action.ActionInterpretationError(
                "World seed contains an invalid player template."
            )
        player_id = seed_player.get("id")
        if not isinstance(player_id, str) or not player_id:
            raise interpret_action.ActionInterpretationError(
                "World seed contains no stable Player id."
            )

        player = persistence.get_player(player_id)
        player_state = persistence.get_player_state(player_id)
        if player is None or player_state is None:
            raise interpret_action.NoPlayerError(
                "No player exists in PostgreSQL Runtime State."
            )

        player_identity = build_player_identity_read_model(player, player_state)

        runtime_player = copy.deepcopy(seed_player)
        runtime_player.update(
            {
                "id": player["player_id"],
                "name": player["name"],
                "species": player["species"],
                "occupation": player["occupation"],
                "background": player["background"],
                "traits": copy.deepcopy(player["traits"]),
                "current_location": player_state["current_location"],
                "inventory": copy.deepcopy(player_state["inventory"]),
                "goals": copy.deepcopy(player_state["goals"]),
                "identity": player_identity,
            }
        )
        world_state["player"] = runtime_player

        seed_npcs = world_state.get("npcs")
        if not isinstance(seed_npcs, dict):
            raise interpret_action.ActionInterpretationError(
                "World seed contains an invalid NPC registry."
            )
        for npc in seed_npcs.values():
            if not isinstance(npc, dict) or not isinstance(npc.get("id"), str):
                raise interpret_action.ActionInterpretationError(
                    "World seed contains an NPC without a stable id."
                )
            runtime_npc = persistence.get_npc(npc["id"])
            if runtime_npc is None:
                raise interpret_action.ActionInterpretationError(
                    f"NPC Runtime State is missing in PostgreSQL: {npc['id']}"
                )
            npc.update(
                {
                    "current_location": runtime_npc["current_location"],
                    "current_activity": runtime_npc["current_activity"],
                    "current_goal": runtime_npc["current_goal"],
                    "mood": runtime_npc["mood"],
                }
            )

        required_sections = interpret_action.REQUIRED_SAVE_SECTIONS
        missing_sections = sorted(required_sections - world_state.keys())
        if missing_sections:
            raise interpret_action.ActionInterpretationError(
                "Runtime World Context is missing required section(s): "
                + ", ".join(missing_sections)
            )
        world = world_state.get("world")
        locations = world_state.get("locations")
        if not isinstance(world, dict) or not isinstance(world.get("rules"), dict):
            raise interpret_action.ActionInterpretationError(
                "Runtime World Context is missing world.rules."
            )
        if (
            not isinstance(locations, dict)
            or runtime_player["current_location"] not in locations
        ):
            raise interpret_action.ActionInterpretationError(
                "PostgreSQL Player location does not resolve to World configuration."
            )
        nearby_dragons = persistence.list_dragons_at_location(
            runtime_player["current_location"]
        )
        for dragon in nearby_dragons:
            dragon["player_relationship"] = persistence.get_player_dragon_bond(
                player_id=player_id,
                dragon_id=dragon["dragon_id"],
            )
        world_state["nearby_dragons"] = nearby_dragons
        return world_state
    except interpret_action.NoPlayerError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "No player exists in the current Dragon World database. "
                "Create and migrate a player first."
            ),
        ) from exc
    except (
        interpret_action.ActionInterpretationError,
        PlayerIdentityRuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail="The PostgreSQL Runtime World State is invalid.",
        ) from exc


def _load_resources() -> action_pipeline.ActionPipelineResources:
    return action_pipeline.load_pipeline_resources(
        interpreter_module=interpret_action,
        validator_module=validate_action,
        executor_module=execute_action,
    )


def _clean_action_input(request: ActionRequest) -> str:
    if not request.input.strip():
        raise HTTPException(
            status_code=400,
            detail="Action input must not be empty.",
        )
    return request.input


def _pipeline_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LLMProviderError):
        return HTTPException(
            status_code=502,
            detail="The configured LLM provider could not produce a valid response.",
        )
    if isinstance(exc, execute_action.ActionExecutionError):
        return HTTPException(
            status_code=409,
            detail=(
                "Action mutation validation failed; "
                "PostgreSQL Player State was not modified."
            ),
        )
    if isinstance(
        exc,
        (DatabaseConfigurationError, PersistenceMappingError, SQLAlchemyError),
    ):
        return HTTPException(
            status_code=500,
            detail="PostgreSQL Runtime State is unavailable.",
        )
    if isinstance(
        exc,
        (
            interpret_action.ActionInterpretationError,
            validate_action.WorldValidationError,
        ),
    ):
        return HTTPException(
            status_code=422,
            detail="The action pipeline could not produce a valid grounded preview.",
        )
    return HTTPException(
        status_code=500,
        detail="An internal Dragon World API error occurred.",
    )


def _free_action_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LLMProviderError):
        return HTTPException(
            status_code=502,
            detail="The configured LLM provider could not interpret the action.",
        )
    if isinstance(exc, FreeActionInterpretationError):
        return HTTPException(
            status_code=422,
            detail="The action interpreter could not produce a valid action.",
        )
    if isinstance(exc, ActionResolutionError):
        return HTTPException(
            status_code=409,
            detail="The action could not be resolved against the current world.",
        )
    if isinstance(exc, (EncounterDecisionError, DragonCandidateError)):
        return HTTPException(
            status_code=500,
            detail="The Dragon encounter could not be grounded.",
        )
    if isinstance(
        exc,
        (DatabaseConfigurationError, PersistenceMappingError, SQLAlchemyError),
    ):
        return HTTPException(
            status_code=500,
            detail="PostgreSQL Runtime State is unavailable.",
        )
    return HTTPException(
        status_code=500,
        detail="An internal Dragon World API error occurred.",
    )


def _free_action_player_message(resolution: dict[str, Any]) -> str:
    reason_code = resolution.get("reason_code")
    messages = {
        "known_travel": "你已抵达目的地。",
        "already_at_destination": "你已经在目的地。",
        "goal_added": "新的目标已经记录。",
        "goal_already_present": "这个目标已经存在。",
        "goal_removed": "目标已经移除。",
        "goal_not_present": "这个目标当前不存在。",
        "open_exploration_recorded": "你开始沿这个方向探索。",
        "dragon_riding_not_grounded": "你目前没有一条已驯服且允许骑乘的龙。",
        "dragon_runtime_required": "这个行动需要由 Dragon Runtime 继续处理。",
        "destination_missing": "这个行动缺少明确目的地。",
        "destination_not_grounded": "这个目的地尚未成为世界中的已知地点。",
        "no_direct_route": "当前位置没有通往该目的地的直接路线。",
        "destination_unreachable": "当前世界中暂时没有可到达该地点的已知路线。",
        "goal_limit_reached": "当前无法记录更多目标。",
        "language_ambiguous": "这个行动还需要更明确的描述。",
        "npc_runtime_required": "这个行动需要由 NPC Runtime 继续处理。",
        "conflict_runtime_unavailable": "这个冲突行动当前只能作为叙事意图记录。",
        "narrative_only": "这个行动已作为当前世界中的叙事行动记录。",
    }
    if isinstance(reason_code, str) and reason_code in messages:
        return messages[reason_code]
    if resolution.get("status") == "blocked":
        return "当前世界条件不允许这个行动成为事实。"
    if resolution.get("status") == "partial":
        return "这个行动已被部分处理。"
    return "行动已经处理。"


def _dragon_encounter_player_message(
    resolution: dict[str, Any],
    encounter: dict[str, Any],
) -> str:
    outcome = encounter["outcome"]
    dragon = encounter.get("dragon")
    dragon_name = dragon.get("name") if isinstance(dragon, dict) else None
    if outcome == "trace":
        return "你发现了龙类活动留下的痕迹。"
    if outcome == "sighting" and isinstance(dragon_name, str):
        return f"你发现了龙：{dragon_name}。"
    if outcome == "direct_encounter" and isinstance(dragon_name, str):
        return f"你与龙 {dragon_name} 正面相遇。"
    return _free_action_player_message(resolution)


_DRAGON_INTERACTION_MARKERS = (
    "观察",
    "注视",
    "看看",
    "靠近",
    "接近",
    "走向",
    "后退",
    "退后",
    "拉开距离",
    "说话",
    "交流",
    "交谈",
    "安抚",
    "喂",
    "食物",
    "触碰",
    "触摸",
    "摸",
    "抱",
    "威胁",
    "恐吓",
    "攻击",
    "杀",
    "骑",
    "observe",
    "watch",
    "approach",
    "retreat",
    "step back",
    "speak",
    "talk",
    "soothe",
    "feed",
    "food",
    "touch",
    "pet",
    "hug",
    "threat",
    "attack",
    "kill",
    "ride",
    "mount",
)
_DRAGON_REFERENCE_MARKERS = ("龙", "dragon")
_GENERIC_DRAGON_TARGETS = {
    "龙",
    "那条龙",
    "这条龙",
    "它",
    "dragon",
    "the dragon",
    "it",
}
_IMPLICIT_UNIQUE_DRAGON_MARKERS = (
    "后退",
    "退后",
    "拉开距离",
    "retreat",
    "step back",
)


def _structured_action_text(structured_action: Mapping[str, Any]) -> str:
    return " ".join(
        str(structured_action.get(field) or "").strip().casefold()
        for field in ("action", "target", "intent", "method")
    )


def _ground_dragon_interaction_target(
    *,
    structured_action: Mapping[str, Any],
    resolution: Mapping[str, Any],
    player_location: str,
    persistence: PostgresPersistenceAdapter,
) -> dict[str, Any] | None:
    """Ground one explicit D4 action to committed Dragon truth, or fail closed."""

    if structured_action.get("explicit_goal") is not None:
        return None
    if resolution.get("domain_route") == "npc":
        return None

    text = _structured_action_text(structured_action)
    if not any(marker in text for marker in _DRAGON_INTERACTION_MARKERS):
        return None
    family = structured_action.get("action_family")
    is_ride = any(marker in text for marker in ("骑", "ride", "mount"))
    if family == "travel" and not is_ride:
        return None

    target = structured_action.get("target")
    target_text = target.strip() if isinstance(target, str) else ""
    target_key = target_text.casefold()
    nearby = persistence.list_dragons_at_location(player_location)

    committed_by_id = (
        persistence.get_dragon(target_text) if target_text else None
    )
    nearby_matches = [
        dragon
        for dragon in nearby
        if target_key
        and target_key
        in {
            str(dragon.get("dragon_id") or "").casefold(),
            str(dragon.get("name") or "").casefold(),
        }
    ]
    if committed_by_id is not None:
        return {"dragon": committed_by_id, "reason_code": None}
    if len(nearby_matches) == 1:
        return {"dragon": nearby_matches[0], "reason_code": None}

    generic_target = target_key in _GENERIC_DRAGON_TARGETS
    references_dragon = any(marker in text for marker in _DRAGON_REFERENCE_MARKERS)
    implicit_unique = not target_text and any(
        marker in text for marker in _IMPLICIT_UNIQUE_DRAGON_MARKERS
    )
    routed_to_dragon = resolution.get("domain_route") == "dragon"
    is_d4_candidate = (
        generic_target
        or references_dragon
        or routed_to_dragon
        or implicit_unique
    )
    if not is_d4_candidate:
        return None
    if (generic_target or implicit_unique) and len(nearby) == 1:
        # D4-C accepts generic grounding only when D2 already routed the action
        # to Dragon Runtime. Other pronouns remain fail-closed at this boundary.
        if routed_to_dragon:
            return {"dragon": nearby[0], "reason_code": None}
        return {"dragon": None, "reason_code": "dragon_target_needs_clarification"}
    if (generic_target or implicit_unique) and len(nearby) > 1:
        return {"dragon": None, "reason_code": "dragon_target_ambiguous"}
    return {"dragon": None, "reason_code": "dragon_target_not_grounded"}


def _dragon_interaction_player_message(
    dragon_name: str | None,
    interaction: Mapping[str, Any],
) -> str:
    name = dragon_name or "这条龙"
    transition = interaction.get("taming_transition")
    if isinstance(transition, Mapping):
        destination = transition.get("to")
        if destination == "tolerant":
            return f"{name} 开始容忍你的靠近。"
        if destination == "bonding":
            return f"{name} 开始真正信任你的存在。"
        if destination == "tamed":
            return f"{name} 已经接受了你。"
    if interaction.get("anti_farming") == "zero":
        return f"{name} 对你重复的举动已经没有新的反应。"

    reason = interaction.get("reason_code")
    messages = {
        "dragon_target_not_grounded": "没有找到这次行动明确指向的正式 Dragon。",
        "dragon_target_ambiguous": "附近有不止一条 Dragon，请明确说出名字。",
        "dragon_target_needs_clarification": "请明确说出你想互动的 Dragon 名字。",
        "dragon_not_in_interaction_range": f"{name} 当前不在你身边。",
        "dragon_observed": f"{name} 仍保持警惕，安静地观察着你。",
        "patient_wait": f"你停下来耐心等待，{name} 仍在观察你。",
        "boundary_respected": f"你主动拉开距离。{name} 的戒备似乎稍稍缓和。",
        "cautious_approach": f"{name} 注意到了你的靠近，没有立即离开，但仍保持戒备。",
        "calm_communication_acknowledged": f"你平静地向 {name} 说话。它没有回应，但开始认真观察你。",
        "grounded_food_offer_accepted": f"{name} 接受了你放下的食物。",
        "offered_food_not_grounded": "你现在没有可供 Dragon 接受的明确食物。",
        "dragon_rejects_food_while_hostile": f"{name} 仍处于敌意中，没有接受食物。",
        "dragon_touch_not_grounded": f"{name} 还没有允许你靠得这么近。",
        "dragon_allows_touch_preview": f"{name} 接受了你的触碰。",
        "dragon_reacts_defensively": f"你的举动让 {name} 明显警觉起来。",
        "reckless_approach_rejected": f"{name} 拒绝了你鲁莽的靠近。",
        "dragon_not_tamed": f"{name} 还没有接受你的骑乘。",
        "dragon_riding_not_unlocked": f"{name} 已接受你，但还没有准备好让你骑乘。",
        "dragon_riding_runtime_required": f"{name} 已允许靠近，但骑乘仍需由 Riding Runtime 处理。",
        "dragon_interaction_needs_clarification": "这次 Dragon 互动还需要更明确的描述。",
        "dragon_interaction_not_resolved": f"{name} 注意到了你的行动，但世界尚不能进一步确定结果。",
    }
    return messages.get(str(reason), f"{name} 对你的行动作出了回应。")


def _no_dragon_encounter_for_interaction() -> dict[str, Any]:
    return {
        "outcome": "none",
        "is_final": True,
        "requires_new_dragon": False,
        "dragon_id": None,
        "reason_code": "dragon_interaction_handled",
        "context_score": 0,
        "roll": 0.0,
        "source": None,
        "dragon": None,
    }


def _blocked_dragon_interaction(reason_code: str) -> dict[str, Any]:
    interaction = {
        "status": "blocked",
        "resolution_status": "blocked",
        "dragon_id": None,
        "dragon_name": None,
        "interaction_type": None,
        "dragon_reaction": None,
        "relationship_effect": "neutral",
        "reason_code": reason_code,
        "positive_category": None,
        "anti_farming": "not_applicable",
        "applied_deltas": {
            "familiarity": 0,
            "trust": 0,
            "fear": 0,
            "bond": 0,
        },
        "bond_state": None,
        "before": None,
        "after": None,
        "taming_state": None,
        "taming_transition": None,
    }
    interaction["player_message"] = _dragon_interaction_player_message(
        None,
        interaction,
    )
    return interaction


def _committed_dragon_interaction_response(
    *,
    dragon: Mapping[str, Any],
    commit_result: Mapping[str, Any],
    formal_result: Mapping[str, Any],
) -> dict[str, Any]:
    formal_status = formal_result.get("status")
    public_status = (
        formal_status
        if formal_status in {"blocked", "needs_clarification"}
        else commit_result.get("status")
    )
    interaction = {
        "status": public_status,
        "resolution_status": formal_status,
        "dragon_id": commit_result.get("dragon_id"),
        "dragon_name": dragon.get("name"),
        "interaction_type": formal_result.get("interaction_type"),
        "dragon_reaction": formal_result.get("dragon_reaction"),
        "relationship_effect": formal_result.get("relationship_effect"),
        "reason_code": formal_result.get("reason_code"),
        "positive_category": formal_result.get("positive_category"),
        "anti_farming": formal_result.get("anti_farming"),
        "applied_deltas": copy.deepcopy(commit_result.get("applied_deltas", {})),
        "bond_state": copy.deepcopy(commit_result.get("bond_state")),
        "before": copy.deepcopy(formal_result.get("before")),
        "after": copy.deepcopy(formal_result.get("after")),
        "taming_state": commit_result.get("taming_state"),
        "taming_transition": copy.deepcopy(commit_result.get("taming_transition")),
    }
    interaction["player_message"] = _dragon_interaction_player_message(
        str(dragon.get("name") or "") or None,
        interaction,
    )
    return interaction


def create_app(
    save_path: Path | None = None,
    *,
    memory_store_path: Path | None = None,
    relationship_store_path: Path | None = None,
    npc_provider_client: StructuredOutputProvider | None = None,
    identity_provider_client: LLMProviderClient | None = None,
    action_provider_client: LLMProviderClient | None = None,
    dragon_provider_client: LLMProviderClient | None = None,
    location_provider_client: LLMProviderClient | None = None,
    dragon_encounter_roll: float | None = None,
    persistence_adapter: PostgresPersistenceAdapter | None = None,
) -> FastAPI:
    # Explicit path injection is retained only for existing isolated tests. The
    # production app passes no paths and has no JSON fallback on DB failure.
    fixture_mode = any(
        path is not None
        for path in (save_path, memory_store_path, relationship_store_path)
    )
    if fixture_mode:
        fixture_save_path = save_path or interpret_action.SAVE_PATH
        fixture_memory_path = memory_store_path
        fixture_relationship_path = relationship_store_path
        if fixture_memory_path is None or fixture_relationship_path is None:
            from npc.memory import MEMORY_STORE_PATH
            from npc.relationship_store import RELATIONSHIP_STORE_PATH

            fixture_memory_path = fixture_memory_path or MEMORY_STORE_PATH
            fixture_relationship_path = (
                fixture_relationship_path or RELATIONSHIP_STORE_PATH
            )
        load_world = lambda: _load_legacy_fixture_world(fixture_save_path)
    else:
        persistence_adapter = persistence_adapter or PostgresPersistenceAdapter(
            create_session_factory(create_database_engine())
        )
        load_world = lambda: _load_postgres_world(persistence_adapter)

    application = FastAPI(
        title="Dragon World API",
        version="0.1",
        description="Web API bridge for the grounded Dragon World core engine.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "dragon-world-api"}

    @application.get("/api/world")
    def get_world() -> dict[str, Any]:
        try:
            return build_world_summary(load_world())
        except HTTPException:
            raise
        except Exception as exc:
            raise _pipeline_http_error(exc) from exc

    @application.post(
        "/api/player/identity/initialize",
        response_model=IdentityInitializeResponse,
    )
    def initialize_player_identity(
        request: IdentityInitializeRequest,
    ) -> dict[str, Any]:
        player_id = request.player_id.strip()
        self_description = request.self_description.strip()
        if not player_id:
            raise _identity_business_error(
                400,
                "player_not_found",
                "player_id must not be empty.",
            )
        if not self_description:
            raise _identity_business_error(
                400,
                "invalid_self_description",
                "self_description must not be empty.",
            )
        if persistence_adapter is None:
            raise _identity_system_error(
                500,
                "persistence_failure",
                "PostgreSQL Identity persistence is unavailable.",
            )

        try:
            player = persistence_adapter.get_player(player_id)
            if player is None:
                raise _identity_business_error(
                    404,
                    "player_not_found",
                    "Player does not exist.",
                )
            player_state = persistence_adapter.get_player_state(player_id)
            if player_state is None:
                raise _identity_business_error(
                    404,
                    "player_state_not_found",
                    "PlayerState does not exist.",
                )

            try:
                interpretation = interpret_identity(
                    self_description,
                    provider_client=identity_provider_client,
                )
            except LLMProviderError as exc:
                logger.exception(
                    "identity_initialization_failed stage=b1_interpreter "
                    "error_code=provider_failure exception_type=%s",
                    exc.__class__.__name__,
                )
                raise _identity_system_error(
                    502,
                    "provider_failure",
                    "The configured LLM provider could not interpret identity.",
                ) from exc
            except IdentityInterpretationError as exc:
                logger.exception(
                    "identity_initialization_failed stage=b1_interpreter "
                    "error_code=invalid_interpreter_output exception_type=%s",
                    exc.__class__.__name__,
                )
                raise _identity_system_error(
                    502,
                    "invalid_interpreter_output",
                    "The Identity Interpreter returned an invalid result.",
                ) from exc
            except Exception as exc:
                logger.exception(
                    "identity_initialization_failed stage=b1_interpreter "
                    "error_code=interpreter_failure exception_type=%s",
                    exc.__class__.__name__,
                )
                raise _identity_system_error(
                    500,
                    "interpreter_failure",
                    "The Identity Interpreter could not process this request.",
                ) from exc

            try:
                grounding = ground_identity(interpretation)
            except IdentityGroundingError as exc:
                raise _identity_system_error(
                    500,
                    "grounding_failure",
                    "Identity Grounding could not validate the interpretation.",
                ) from exc

            try:
                commit_result = commit_initial_identity(
                    persistence=persistence_adapter,
                    player_id=player_id,
                    self_description=self_description,
                    interpretation=interpretation,
                    grounding=grounding,
                )
            except ControlledIdentityCommitError as exc:
                if exc.code == "identity_already_initialized":
                    raise _identity_business_error(
                        409,
                        "identity_already_initialized",
                        "Origin Identity is already initialized.",
                    ) from exc
                raise _identity_system_error(
                    500,
                    "persistence_failure",
                    "Identity could not be committed safely.",
                ) from exc

            persisted_player = persistence_adapter.get_player(player_id)
            persisted_state = persistence_adapter.get_player_state(player_id)
            if persisted_player is None or persisted_state is None:
                raise _identity_system_error(
                    500,
                    "persistence_failure",
                    "Committed Identity could not be read back.",
                )
            identity = build_player_identity_read_model(
                persisted_player,
                persisted_state,
            )
            if identity["identity_initialized"] is not True:
                raise _identity_system_error(
                    500,
                    "persistence_failure",
                    "Committed Identity is not initialized after read-back.",
                )
            return {
                "status": (
                    "already_initialized"
                    if commit_result["status"] == "already_applied"
                    else "initialized"
                ),
                "player_id": identity["player_id"],
                "display_name": identity["display_name"],
                "identity_initialized": identity["identity_initialized"],
                "identity_summary": identity["identity_summary"],
            }
        except HTTPException:
            raise
        except (
            DatabaseConfigurationError,
            PersistenceMappingError,
            PlayerIdentityRuntimeError,
            SQLAlchemyError,
        ) as exc:
            raise _identity_system_error(
                500,
                "persistence_failure",
                "PostgreSQL Identity persistence is invalid or unavailable.",
            ) from exc

    @application.post("/api/action/preview")
    def preview_action(request: ActionRequest) -> dict[str, Any]:
        raw_input = _clean_action_input(request)
        try:
            world_state = load_world()
            resources = _load_resources()
            return action_pipeline.preview_action(
                raw_input,
                world_state,
                resources,
                interpreter_module=interpret_action,
                validator_module=validate_action,
                executor_module=execute_action,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise _pipeline_http_error(exc) from exc

    @application.post("/api/action/execute")
    def execute_free_action(request: FreeActionExecuteRequest) -> dict[str, Any]:
        player_id = request.player_id.strip()
        player_input = request.player_input.strip()
        if not player_id:
            raise HTTPException(status_code=400, detail="player_id must not be empty.")
        if not player_input:
            raise HTTPException(status_code=400, detail="player_input must not be empty.")
        if persistence_adapter is None:
            raise HTTPException(
                status_code=500,
                detail="PostgreSQL Runtime State is unavailable.",
            )

        try:
            structured_action = interpret_free_action(
                player_input,
                provider_client=action_provider_client,
            )
            committed = commit_action_resolution(
                player_id=player_id,
                player_input=player_input,
                structured_action=structured_action,
                persistence=persistence_adapter,
            )
            resolution = committed["resolution"]
            source_event_id = committed["interaction_event"]["event_id"]
            encounter_location_id = committed["player_state"]["current_location"]

            location_discovery: dict[str, Any] | None = None
            if is_location_discovery_eligible(structured_action, resolution):
                runtime_skeleton = load_runtime_world_skeleton(
                    persistence_adapter,
                    WORLD_SEED_PATH,
                )
                locations = runtime_skeleton["locations"]
                candidate = generate_location_candidate(
                    structured_action=structured_action,
                    current_location_id=encounter_location_id,
                    locations=locations,
                    provider_client=location_provider_client,
                )
                grounded_location = ground_location_candidate(
                    candidate=candidate,
                    structured_action=structured_action,
                    resolution=resolution,
                    source_interaction_event_id=source_event_id,
                    current_location_id=encounter_location_id,
                    locations=locations,
                )
                location_commit = persistence_adapter.commit_location_discovery(
                    player_id=player_id,
                    source_interaction_event_id=source_event_id,
                    location=grounded_location,
                )
                location_discovery = _location_discovery_response(location_commit)

            dragon_target = _ground_dragon_interaction_target(
                structured_action=structured_action,
                resolution=resolution,
                player_location=encounter_location_id,
                persistence=persistence_adapter,
            )
            if dragon_target is not None:
                dragon = dragon_target["dragon"]
                if dragon is None:
                    dragon_interaction = _blocked_dragon_interaction(
                        dragon_target["reason_code"]
                    )
                else:
                    commit_result = persistence_adapter.commit_dragon_interaction(
                        player_id=player_id,
                        dragon_id=dragon["dragon_id"],
                        source_interaction_event_id=source_event_id,
                    )
                    persisted_source = persistence_adapter.get_interaction_event(
                        source_event_id
                    )
                    payload = (
                        persisted_source.get("event_payload")
                        if isinstance(persisted_source, Mapping)
                        else None
                    )
                    formal_result = (
                        payload.get("dragon_interaction")
                        if isinstance(payload, Mapping)
                        else None
                    )
                    if not isinstance(formal_result, Mapping):
                        raise PersistenceMappingError(
                            "Committed Dragon interaction could not be read back."
                        )
                    dragon_interaction = _committed_dragon_interaction_response(
                        dragon=dragon,
                        commit_result=commit_result,
                        formal_result=formal_result,
                    )
                return {
                    "structured_action": structured_action,
                    "resolution": resolution,
                    "player_message": dragon_interaction["player_message"],
                    "source_event_id": source_event_id,
                    "dragon_encounter": _no_dragon_encounter_for_interaction(),
                    "dragon_interaction": dragon_interaction,
                    "location_discovery": None,
                }

            decision = decide_current_dragon_encounter(
                player_id=player_id,
                structured_action=structured_action,
                resolution=resolution,
                persistence=persistence_adapter,
                roll=dragon_encounter_roll,
            )
            persistence_adapter.record_dragon_encounter_decision(
                player_id=player_id,
                source_interaction_event_id=source_event_id,
                encounter_location_id=encounter_location_id,
                decision=decision,
            )

            encounter_source: str | None = None
            committed_dragon: dict[str, Any] | None = None
            final_decision = decision
            if decision["requires_new_dragon"]:
                dragon_commit = commit_new_dragon_encounter(
                    player_id=player_id,
                    source_interaction_event_id=source_event_id,
                    provisional_decision=decision,
                    encounter_location_id=encounter_location_id,
                    persistence=persistence_adapter,
                    provider_client=dragon_provider_client,
                )
                final_decision = dragon_commit["encounter"]
                committed_dragon = _public_dragon_summary(
                    dragon_commit["dragon"]
                )
                encounter_source = "generated"
            elif decision["dragon_id"] is not None:
                persisted_dragon = persistence_adapter.get_dragon(
                    decision["dragon_id"]
                )
                if persisted_dragon is None:
                    raise PersistenceMappingError(
                        "Final Dragon encounter references a missing Dragon."
                    )
                committed_dragon = _public_dragon_summary(persisted_dragon)
                encounter_source = "existing"

            dragon_encounter = {
                **final_decision,
                "source": encounter_source,
                "dragon": committed_dragon,
            }
            player_message = _dragon_encounter_player_message(
                resolution,
                dragon_encounter,
            )
            if location_discovery is not None:
                discovery_message = _location_discovery_player_message(
                    location_discovery
                )
                player_message = (
                    discovery_message
                    if dragon_encounter["outcome"] == "none"
                    else f"{discovery_message} {player_message}"
                )
            return {
                "structured_action": structured_action,
                "resolution": resolution,
                "player_message": player_message,
                "source_event_id": source_event_id,
                "dragon_encounter": dragon_encounter,
                "dragon_interaction": None,
                "location_discovery": location_discovery,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise _free_action_http_error(exc) from exc

    @application.post("/api/action/commit")
    def commit_action(request: ActionRequest) -> dict[str, Any]:
        raw_input = _clean_action_input(request)
        try:
            resources = _load_resources()
            if fixture_mode:
                return action_pipeline.rerun_and_commit_action(
                    raw_input,
                    resources,
                    save_path=fixture_save_path,
                    interpreter_module=interpret_action,
                    validator_module=validate_action,
                    executor_module=execute_action,
                )

            # The POST itself is confirmation. Re-read PostgreSQL and rerun the
            # complete frozen pipeline before applying any Player State change.
            world_state = load_world()
            preview = action_pipeline.preview_action(
                raw_input,
                world_state,
                resources,
                interpreter_module=interpret_action,
                validator_module=validate_action,
                executor_module=execute_action,
            )
            result = {**preview, "committed": False, "player": None}
            if preview["pipeline_status"] != "ready":
                return result
            plan = preview["execution_plan"]
            validation = preview["validation"]
            if not isinstance(plan, dict) or not isinstance(validation, dict):
                return result
            if not plan.get("proposed_mutations"):
                result["pipeline_status"] = "no_mutation"
                return result

            updated_world = execute_action.apply_execution_plan_in_memory(
                plan,
                validation,
                world_state,
            )
            updated_player = updated_world["player"]
            persisted_state = persistence_adapter.upsert_player_state(
                player_id=updated_player["id"],
                current_location=updated_player["current_location"],
                inventory=updated_player["inventory"],
                goals=updated_player["goals"],
            )
            committed_player = copy.deepcopy(updated_player)
            committed_player.update(
                {
                    "current_location": persisted_state["current_location"],
                    "inventory": persisted_state["inventory"],
                    "goals": persisted_state["goals"],
                }
            )
            result["player"] = committed_player
            result["committed"] = True
            result["pipeline_status"] = "committed"
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise _pipeline_http_error(exc) from exc

    register_npc_routes(
        application,
        load_world=load_world,
        memory_store_path=fixture_memory_path if fixture_mode else None,
        relationship_store_path=(
            fixture_relationship_path if fixture_mode else None
        ),
        provider_client=npc_provider_client,
        persistence_adapter=None if fixture_mode else persistence_adapter,
    )

    return application


app = create_app()
