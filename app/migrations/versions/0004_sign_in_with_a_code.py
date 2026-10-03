"""Sign in with a code: every user may have a mobile, and codes sent by SMS.

The phone is unique - it is who the person is when they sign in. A code is kept
only as its HMAC, with when it expires, how many wrong tries it has had, and
when it was used or replaced.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 15:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone", sa.String(length=10), nullable=False),
        sa.Column("full_name", sa.String(length=80), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("otp_codes") as batch_op:
        batch_op.create_index("ix_otp_codes_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_otp_codes_ip", ["ip"], unique=False)
        batch_op.create_index("ix_otp_codes_phone", ["phone"], unique=False)
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String(length=10), nullable=True))
        batch_op.create_unique_constraint("uq_users_phone", ["phone"])


def downgrade() -> None:
    # Someone who signed up with a code has no password: without the phone they
    # could never sign in again. It refuses instead.
    phones = op.get_bind().execute(sa.text("SELECT count(*) FROM users WHERE phone IS NOT NULL")).scalar()
    if phones:
        raise RuntimeError(
            f"{phones} user(s) sign in by phone and would be locked out; decide about them first"
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_phone", type_="unique")
        batch_op.drop_column("phone")
    op.drop_table("otp_codes")
