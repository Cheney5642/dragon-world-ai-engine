"""FastAPI bridge for the Dragon World core action pipeline."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from api.npc_api import register_npc_routes
from core import action_pipeline
from database.connection import (
    DatabaseConfigurationError,
    create_database_engine,
    create_session_factory,
)
from database.persistence import (
    PersistenceMappingError,
    PostgresPersistenceAdapter,
)
from llm import LLMProviderError
from npc.interaction_runtime import StructuredOutputProvider
from scripts import execute_action
from scripts import interpret_action
from scripts import validate_action


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORLD_SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"


class ActionRequest(BaseModel):
    """Untrusted frontend input; mutations are intentionally not accepted."""

    model_config = ConfigDict(extra="forbid")

    input: str


def build_world_summary(world_state: dict[str, Any]) -> dict[str, Any]:
    """Return only the public fields required by the v0.1 demo UI."""

    player = world_state["player"]
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

    return {
        "player": {
            "id": player.get("id"),
            "name": player.get("name"),
            "species": player.get("species"),
            "occupation": player.get("occupation"),
            "current_location": current_location_id,
            "goals": player.get("goals", []),
            "inventory": player.get("inventory", []),
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
        },
        "nearby_npcs": nearby_npcs,
    }


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
        world_state = interpret_action.load_json_object(
            WORLD_SEED_PATH,
            "Dragon World seed configuration",
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
        if player is None or player_state is None or player.get("species") is None:
            raise interpret_action.NoPlayerError(
                "No player exists in PostgreSQL Runtime State."
            )

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
        return world_state
    except interpret_action.NoPlayerError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "No player exists in the current Dragon World database. "
                "Create and migrate a player first."
            ),
        ) from exc
    except interpret_action.ActionInterpretationError as exc:
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


def create_app(
    save_path: Path | None = None,
    *,
    memory_store_path: Path | None = None,
    relationship_store_path: Path | None = None,
    npc_provider_client: StructuredOutputProvider | None = None,
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
