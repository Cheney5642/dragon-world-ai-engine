"""Controlled, one-time Open Identity commit service v0.2.

This module does not interpret or Ground identity data. It validates the
Frozen B1 and B2 contracts, maps only Grounded fields, and delegates one
atomic PostgreSQL transaction to the thin persistence adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from database.persistence import (
    IdentityAlreadyInitializedError,
    PersistenceMappingError,
    PostgresPersistenceAdapter,
)
from identity.grounding import (
    IdentityGroundingError,
    validate_identity_grounding,
)
from identity.interpreter import (
    IdentityInterpretationError,
    validate_identity_interpretation,
)


class ControlledIdentityCommitError(Exception):
    """A safe, caller-readable Controlled Identity Commit failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _build_grounding_safe_summary(
    interpretation: Mapping[str, Any],
    grounding: Mapping[str, Any],
) -> str:
    """Prevent unverified claims from being persisted as objective facts."""

    unverified_claims = list(grounding["unverified_claims"])
    if not unverified_claims:
        return interpretation["identity_summary"]

    display_name = interpretation["display_name"]
    subject = (
        display_name.strip()
        if isinstance(display_name, str) and display_name.strip()
        else "The player"
    )
    parts: list[str] = []
    accepted_facts = list(grounding["accepted_facts"])
    if accepted_facts:
        parts.append(
            f"{subject}'s accepted identity facts: "
            f"{'; '.join(accepted_facts)}."
        )
    parts.append(
        f"{subject} claims: {'; '.join(unverified_claims)}. "
        "These claims are unverified and are not established as World Truth."
    )
    return " ".join(parts)


def build_identity_context(
    *,
    self_description: str,
    interpretation: Mapping[str, Any],
    grounding: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact persisted context from validated B1/B2 outputs."""

    if not isinstance(self_description, str) or not self_description.strip():
        raise ControlledIdentityCommitError(
            "invalid_identity_commit",
            "self_description must be a non-empty string.",
        )
    if not isinstance(interpretation, dict):
        raise ControlledIdentityCommitError(
            "invalid_identity_commit",
            "IdentityInterpretation must be an object.",
        )
    if not isinstance(grounding, dict):
        raise ControlledIdentityCommitError(
            "invalid_identity_commit",
            "IdentityGroundingResult must be an object.",
        )

    try:
        validate_identity_interpretation(interpretation)
        validate_identity_grounding(grounding)
    except (IdentityInterpretationError, IdentityGroundingError) as exc:
        raise ControlledIdentityCommitError(
            "invalid_identity_commit",
            str(exc),
        ) from exc

    return {
        "identity_initialized": True,
        "self_description": self_description.strip(),
        "accepted_facts": list(grounding["accepted_facts"]),
        "unverified_claims": list(grounding["unverified_claims"]),
        "capability_hints": list(grounding["accepted_capability_hints"]),
        "identity_facets": {
            "narrative_species": grounding["accepted_identity_facets"][
                "narrative_species"
            ],
            "occupations": list(
                grounding["accepted_identity_facets"]["occupations"]
            ),
        },
        "identity_summary": _build_grounding_safe_summary(
            interpretation,
            grounding,
        ),
    }


def commit_initial_identity(
    *,
    persistence: PostgresPersistenceAdapter,
    player_id: str,
    self_description: str,
    interpretation: Mapping[str, Any],
    grounding: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and atomically commit an existing Player's Origin Identity."""

    if not isinstance(player_id, str) or not player_id.strip():
        raise ControlledIdentityCommitError(
            "invalid_identity_commit",
            "player_id must be a non-empty string.",
        )

    identity_context = build_identity_context(
        self_description=self_description,
        interpretation=interpretation,
        grounding=grounding,
    )
    display_name = interpretation["display_name"]
    if isinstance(display_name, str):
        display_name = display_name.strip() or None

    try:
        return persistence.commit_initial_identity(
            player_id=player_id.strip(),
            display_name=display_name,
            traits=list(grounding["accepted_traits"]),
            identity_context=identity_context,
        )
    except IdentityAlreadyInitializedError as exc:
        raise ControlledIdentityCommitError(
            "identity_already_initialized",
            "Origin Identity is already initialized and cannot be overwritten.",
        ) from exc
    except PersistenceMappingError as exc:
        raise ControlledIdentityCommitError(
            "identity_commit_failed",
            str(exc),
        ) from exc
