"""The shop's app on a phone: the device's token from Firebase, so the server can notify it.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-15 08:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("platform IN ('ios', 'android')", name="ck_push_devices_platform"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_push_devices_user_id", "push_devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_devices_user_id", table_name="push_devices")
    op.drop_table("push_devices")
