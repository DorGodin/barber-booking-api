"""Reminders before a booking: when a customer was reminded, and the words a browser is to be told.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08 13:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("reminded_at", sa.DateTime(), nullable=True))
    op.create_table(
        "push_notices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["subscription_id"], ["push_subscriptions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_push_notices_subscription_id", "push_notices", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_push_notices_subscription_id", table_name="push_notices")
    op.drop_table("push_notices")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("reminded_at")
