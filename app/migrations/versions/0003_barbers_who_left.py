"""Barbers who left: a user can be inactive.

Everyone who exists when the column arrives is active - the server default
fills it. An inactive barber keeps every booking they had and is offered to
no one.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02 13:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False))


def downgrade() -> None:
    # Going back would make every barber who left bookable again, silently.
    # It refuses instead; whoever runs it decides about them first.
    gone = op.get_bind().execute(sa.text("SELECT count(*) FROM users WHERE active = 0")).scalar()
    if gone:
        raise RuntimeError(f"{gone} inactive user(s) would become active again; decide about them first")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("active")
