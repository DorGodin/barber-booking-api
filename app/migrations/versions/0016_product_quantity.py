"""How many of a product are kept for a booking.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13 00:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("booking_products") as batch_op:
        batch_op.add_column(sa.Column("quantity", sa.Integer(), server_default="1", nullable=False))
        batch_op.create_check_constraint("ck_booking_products_quantity", "quantity BETWEEN 1 AND 9")


def downgrade() -> None:
    with op.batch_alter_table("booking_products") as batch_op:
        batch_op.drop_constraint("ck_booking_products_quantity", type_="check")
        batch_op.drop_column("quantity")
