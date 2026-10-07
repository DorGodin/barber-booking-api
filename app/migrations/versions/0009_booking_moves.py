"""Moves a customer made, kept to count them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07 11:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_moves",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("moved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_moves_customer_id", "booking_moves", ["customer_id"])
    op.create_index("ix_booking_moves_moved_at", "booking_moves", ["moved_at"])


def downgrade() -> None:
    op.drop_index("ix_booking_moves_moved_at", table_name="booking_moves")
    op.drop_index("ix_booking_moves_customer_id", table_name="booking_moves")
    op.drop_table("booking_moves")
