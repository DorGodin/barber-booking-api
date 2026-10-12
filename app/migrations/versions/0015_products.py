"""The shop's products, and the ones kept for a booking.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-12 22:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("line", sa.String(length=120), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("image", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("in_stock", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("price_minor >= 0", name="ck_products_price"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "booking_products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.String(length=32), nullable=False),
        sa.Column("product_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", "product_id", name="uq_booking_products"),
    )
    op.create_index("ix_booking_products_booking_id", "booking_products", ["booking_id"])


def downgrade() -> None:
    # Going back would lose the shop's products and what customers asked to be kept.
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM products")).scalar()
    if held:
        raise RuntimeError(f"{held} product(s) would be lost; export or remove them first")
    op.drop_index("ix_booking_products_booking_id", table_name="booking_products")
    op.drop_table("booking_products")
    op.drop_table("products")
