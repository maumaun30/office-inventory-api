"""audit trail

Adds stock_movements (append-only quantity log) and records which admin
assigned/returned each assignment. Existing rows get NULL actors.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

movement_kind = sa.Enum("initial", "adjust", "edit", name="movementkind")


def upgrade() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", movement_kind, nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stock_movements_item_id", "stock_movements", ["item_id"])

    with op.batch_alter_table("assignments") as batch:
        batch.add_column(sa.Column("assigned_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("returned_by_user_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.drop_column("returned_by_user_id")
        batch.drop_column("assigned_by_user_id")

    op.drop_index("ix_stock_movements_item_id", table_name="stock_movements")
    op.drop_table("stock_movements")
    movement_kind.drop(op.get_bind(), checkfirst=True)
