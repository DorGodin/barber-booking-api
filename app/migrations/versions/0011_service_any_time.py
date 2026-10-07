"""A service that is offered at any day and hour, past the barber's hours.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07 18:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(sa.Column("any_time", sa.Boolean(), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    # Going back would leave bookings made outside any barber's hours with no rule
    # that allows them.
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM services WHERE any_time = 1")).scalar()
    if held:
        raise RuntimeError(f"{held} service(s) work at any time; change them first")
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("any_time")
