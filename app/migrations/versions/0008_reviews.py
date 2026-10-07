"""Reviews: a customer rates a booking once it is over.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07 09:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("booking_id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("barber_id", sa.String(length=32), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("stars BETWEEN 1 AND 5", name="ck_reviews_stars"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["barber_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_reviews_booking"),
    )


def downgrade() -> None:
    # Going back would lose what customers wrote.
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM reviews")).scalar()
    if held:
        raise RuntimeError(f"{held} review(s) would be lost; export them first")
    op.drop_table("reviews")
