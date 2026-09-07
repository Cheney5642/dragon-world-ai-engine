"""Read-only Open Identity composition for Dragon World Runtime v0.1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class PlayerIdentityRuntimeError(ValueError):
    """Raised when persisted Player Identity data cannot be read safely."""


def _string_list(
    value: Any,
    field: str,
    *,
    max_items: int,
) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise PlayerIdentityRuntimeError(
            f"{field} must be an array of non-empty strings."
        )
    if len(value) > max_items:
        raise PlayerIdentityRuntimeError(
            f"{field} must contain at most {max_items} items."
        )
    return list(value)


def build_player_identity_read_model(
    player: Mapping[str, Any],
    player_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Compose Player and PlayerState reads without producing any mutation."""

    player_id = player.get("player_id")
    if not isinstance(player_id, str) or not player_id:
        raise PlayerIdentityRuntimeError("Player record has no valid player_id.")
    if player_state.get("player_id") != player_id:
        raise PlayerIdentityRuntimeError(
            "Player and PlayerState identities do not match."
        )

    traits = _string_list(player.get("traits"), "players.traits", max_items=5)
    identity_context = player_state.get("identity_context")
    if identity_context is None:
        return {
            "player_id": player_id,
            "display_name": player.get("name"),
            "core_species": player.get("species"),
            "occupation": player.get("occupation"),
            "background": player.get("background"),
            "traits": traits,
            "identity_initialized": False,
            "self_description": None,
            "accepted_facts": [],
            "unverified_claims": [],
            "capability_hints": [],
            "identity_summary": None,
        }
    if not isinstance(identity_context, Mapping):
        raise PlayerIdentityRuntimeError(
            "player_states.identity_context must be an object or null."
        )

    initialized = identity_context.get("identity_initialized") is True
    if not initialized:
        return {
            "player_id": player_id,
            "display_name": player.get("name"),
            "core_species": player.get("species"),
            "occupation": player.get("occupation"),
            "background": player.get("background"),
            "traits": traits,
            "identity_initialized": False,
            "self_description": None,
            "accepted_facts": [],
            "unverified_claims": [],
            "capability_hints": [],
            "identity_summary": None,
        }

    self_description = identity_context.get("self_description")
    identity_summary = identity_context.get("identity_summary")
    if not isinstance(self_description, str) or not self_description.strip():
        raise PlayerIdentityRuntimeError(
            "Initialized Identity has no valid self_description."
        )
    if not isinstance(identity_summary, str) or not identity_summary.strip():
        raise PlayerIdentityRuntimeError(
            "Initialized Identity has no valid identity_summary."
        )

    return {
        "player_id": player_id,
        "display_name": player.get("name"),
        "core_species": player.get("species"),
        "occupation": player.get("occupation"),
        "background": player.get("background"),
        "traits": traits,
        "identity_initialized": True,
        "self_description": self_description,
        "accepted_facts": _string_list(
            identity_context.get("accepted_facts"),
            "identity_context.accepted_facts",
            max_items=10,
        ),
        "unverified_claims": _string_list(
            identity_context.get("unverified_claims"),
            "identity_context.unverified_claims",
            max_items=10,
        ),
        "capability_hints": _string_list(
            identity_context.get("capability_hints"),
            "identity_context.capability_hints",
            max_items=8,
        ),
        "identity_summary": identity_summary,
    }


def build_legacy_player_identity_read_model(
    player: Mapping[str, Any],
) -> dict[str, Any]:
    """Compose an uninitialized PostgreSQL/fixture-compatible Player view."""

    player_id = player.get("id")
    player_record = {
        "player_id": player_id,
        "name": player.get("name"),
        "species": player.get("species"),
        "occupation": player.get("occupation"),
        "background": player.get("background"),
        "traits": list(player.get("traits", [])),
    }
    return build_player_identity_read_model(
        player_record,
        {"player_id": player_id, "identity_context": None},
    )


def build_npc_player_identity_context(
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose only grounded identity data required by NPC response context."""

    claims = _string_list(
        identity.get("unverified_claims"),
        "identity.unverified_claims",
        max_items=10,
    )
    return {
        "display_name": identity.get("display_name"),
        "identity_initialized": identity.get("identity_initialized") is True,
        "accepted_facts": _string_list(
            identity.get("accepted_facts"),
            "identity.accepted_facts",
            max_items=10,
        ),
        "unverified_claims": [
            f"Player claim (unverified): {claim}" for claim in claims
        ],
        "capability_hints": _string_list(
            identity.get("capability_hints"),
            "identity.capability_hints",
            max_items=8,
        ),
        "identity_summary": identity.get("identity_summary"),
    }
