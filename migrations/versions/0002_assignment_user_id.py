"""add assignments.user_id

Links assignments to users in the Laravel API. Rows created before this
migration had no user, so they are backfilled with 0 ("unknown user").

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_assignments_user_id", ["user_id"])
    # Default only existed to backfill legacy rows; the app always supplies user_id.
    with op.batch_alter_table("assignments") as batch:
        batch.alter_column("user_id", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.drop_index("ix_assignments_user_id")
        batch.drop_column("user_id")
