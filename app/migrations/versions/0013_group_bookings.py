"""Bookings made for more than one person in one go.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("for_name", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("group_id", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_bookings_group_id", ["group_id"])


def downgrade() -> None:
    # Going back would forget who a booking was made for, and that two were made together.
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM bookings WHERE group_id IS NOT NULL")).scalar()
    if held:
        raise RuntimeError(f"{held} booking(s) were made for a group; decide about them first")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_index("ix_bookings_group_id")
        batch_op.drop_column("group_id")
        batch_op.drop_column("for_name")
