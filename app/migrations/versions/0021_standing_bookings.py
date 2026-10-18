"""A customer's regular time - the same barber, service and hour every few weeks - and the bookings made for it.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-18 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "standing_bookings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("barber_id", sa.String(length=32), nullable=False),
        sa.Column("service_id", sa.String(length=32), nullable=False),
        sa.Column("every_weeks", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("skipped_until", sa.DateTime(), nullable=True),
        sa.CheckConstraint("every_weeks IN (2, 3, 4)", name="ck_standing_every_weeks"),
        sa.ForeignKeyConstraint(["barber_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_standing_bookings_customer_id", "standing_bookings", ["customer_id"])
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("standing_id", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_bookings_standing_id", ["standing_id"])


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_index("ix_bookings_standing_id")
        batch_op.drop_column("standing_id")
    op.drop_index("ix_standing_bookings_customer_id", table_name="standing_bookings")
    op.drop_table("standing_bookings")
