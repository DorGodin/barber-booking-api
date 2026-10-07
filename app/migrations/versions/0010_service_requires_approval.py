"""A service whose every booking waits for the barber's answer.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(
            sa.Column("requires_approval", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )


def downgrade() -> None:
    # Going back would let an emergency haircut be booked without the barber's yes.
    held = (
        op.get_bind().execute(sa.text("SELECT count(*) FROM services WHERE requires_approval = 1")).scalar()
    )
    if held:
        raise RuntimeError(f"{held} service(s) require the barber's approval; change them first")
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("requires_approval")
