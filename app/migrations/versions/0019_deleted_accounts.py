"""A customer who deleted their account: the row stays, emptied, so the bookings that were theirs keep
their place in the shop's diary and counts.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-15 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("deleted_at")
