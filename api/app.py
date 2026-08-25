"""FastAPI bridge for the Dragon World core action pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from core import action_pipeline
from llm import LLMProviderError
from scripts import execute_action
from scripts import interpret_action
from scripts import validate_action


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


def _load_world(save_path: Path) -> dict[str, Any]:
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
    except interpret_action.ActionInterpretationError as exc:
        raise HTTPException(
            status_code=500,
            detail="The current Dragon World save is invalid.",
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
            detail="Action mutation validation failed; the Save was not modified.",
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
    save_path: Path = interpret_action.SAVE_PATH,
) -> FastAPI:
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
            return build_world_summary(_load_world(save_path))
        except HTTPException:
            raise
        except Exception as exc:
            raise _pipeline_http_error(exc) from exc

    @application.post("/api/action/preview")
    def preview_action(request: ActionRequest) -> dict[str, Any]:
        raw_input = _clean_action_input(request)
        world_state = _load_world(save_path)
        try:
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
        _load_world(save_path)
        try:
            resources = _load_resources()
            return action_pipeline.rerun_and_commit_action(
                raw_input,
                resources,
                save_path=save_path,
                interpreter_module=interpret_action,
                validator_module=validate_action,
                executor_module=execute_action,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise _pipeline_http_error(exc) from exc

    return application


app = create_app()
