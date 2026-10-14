"""What the staff keep in mind about a customer, and a booking the customer did not come to.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-14 18:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("staff_note", sa.Text(), nullable=True))
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("no_show", sa.Boolean(), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("no_show")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("staff_note")
