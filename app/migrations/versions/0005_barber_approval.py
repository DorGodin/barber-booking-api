"""A booking in some hours waits for its barber's yes.

Three nullable columns: whether it needs approval (and where it stands), when
the wait ends, and who answered. Every booking that exists needs nothing.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06 09:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("approval", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("decide_by", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("decided_by", sa.String(length=32), nullable=True))


def downgrade() -> None:
    # Going back would forget which bookings still wait for a barber's answer.
    waiting = (
        op.get_bind().execute(sa.text("SELECT count(*) FROM bookings WHERE approval = 'pending'")).scalar()
    )
    if waiting:
        raise RuntimeError(f"{waiting} booking(s) still wait for a barber's answer; settle them first")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("decided_by")
        batch_op.drop_column("decide_by")
        batch_op.drop_column("approval")
