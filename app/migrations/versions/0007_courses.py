"""Courses the shop gives: a card each, with a picture the owner uploads.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06 18:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("subtitle", sa.String(length=120), nullable=False),
        sa.Column("starts_on", sa.String(length=10), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("image", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Going back would lose the shop's courses, pictures included.
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM courses")).scalar()
    if held:
        raise RuntimeError(f"{held} course(s) would be lost; export or remove them first")
    op.drop_table("courses")
