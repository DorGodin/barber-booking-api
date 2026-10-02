"""Baseline: the tables exactly as create_all made them before migrations.

A database from before migrations is stamped at this revision, not run
through it - see app/migrate.py. Times are plain DateTime here: a migration
never imports app.models, which keeps changing after it is written.

Revision ID: 0001
Revises: -
Create Date: 2026-10-02 08:57:23.927792
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("login_failures", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_login_failures_at"), ["at"], unique=False)
        batch_op.create_index(batch_op.f("ix_login_failures_ip"), ["ip"], unique=False)
        batch_op.create_index(batch_op.f("ix_login_failures_username"), ["username"], unique=False)

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    with op.batch_alter_table("revoked_tokens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_revoked_tokens_expires_at"), ["expires_at"], unique=False)

    op.create_table(
        "services",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "signups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("signups", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_signups_at"), ["at"], unique=False)
        batch_op.create_index(batch_op.f("ix_signups_ip"), ["ip"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "barber_hours",
        sa.Column("barber_id", sa.String(length=32), nullable=False),
        sa.Column("hours_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["barber_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("barber_id"),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("barber_id", sa.String(length=32), nullable=False),
        sa.Column("service_id", sa.String(length=32), nullable=False),
        sa.Column("start_utc", sa.DateTime(), nullable=False),
        sa.Column("end_utc", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["barber_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.create_index("ix_bookings_barber_start", ["barber_id", "start_utc"], unique=False)
        batch_op.create_index("ix_bookings_customer_start", ["customer_id", "start_utc"], unique=False)

    op.create_table(
        "time_off",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("barber_id", sa.String(length=32), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(
            ["barber_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barber_id", "day"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("booking_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
        ),
        sa.PrimaryKeyConstraint("key", "customer_id"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("time_off")
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.drop_index("ix_bookings_customer_start")
        batch_op.drop_index("ix_bookings_barber_start")

    op.drop_table("bookings")
    op.drop_table("barber_hours")
    op.drop_table("users")
    with op.batch_alter_table("signups", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_signups_ip"))
        batch_op.drop_index(batch_op.f("ix_signups_at"))

    op.drop_table("signups")
    op.drop_table("services")
    with op.batch_alter_table("revoked_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_revoked_tokens_expires_at"))

    op.drop_table("revoked_tokens")
    with op.batch_alter_table("login_failures", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_login_failures_username"))
        batch_op.drop_index(batch_op.f("ix_login_failures_ip"))
        batch_op.drop_index(batch_op.f("ix_login_failures_at"))

    op.drop_table("login_failures")
