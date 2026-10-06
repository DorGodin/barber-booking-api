"""Settings the owner changes from the page: when a booking waits for its barber.

One table of named JSON values. No row means the server's own settings apply,
so every shop that exists keeps the rule it had.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shop_settings",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("shop_settings")
