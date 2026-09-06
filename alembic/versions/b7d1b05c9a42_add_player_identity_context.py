"""add player identity context

Revision ID: b7d1b05c9a42
Revises: 09b71ab45512
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b7d1b05c9a42"
down_revision: Union[str, Sequence[str], None] = "09b71ab45512"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable Open Identity Runtime Context."""

    op.add_column(
        "player_states",
        sa.Column(
            "identity_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_player_states_identity_context_json_object",
        "player_states",
        "identity_context IS NULL OR jsonb_typeof(identity_context) = 'object'",
    )


def downgrade() -> None:
    """Remove only the Open Identity Runtime Context."""

    op.drop_constraint(
        "ck_player_states_identity_context_json_object",
        "player_states",
        type_="check",
    )
    op.drop_column("player_states", "identity_context")
