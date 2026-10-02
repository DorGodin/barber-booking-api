"""Guest bookings: the owner books someone who phoned or walked in, by name.

A booking is a customer's, with an account, or a guest's, by name - one or the
other. customer_id may now be empty, and a check holds the either-or in the
database itself, so no route can store a booking that belongs to nobody.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02 12:46:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EITHER_OR = "(customer_id IS NULL) != (guest_name IS NULL)"


def upgrade() -> None:
    # SQLite cannot change a column in place: batch copies the table, with
    # foreign keys off around it (app/main.py prepare_database).
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("guest_name", sa.String(length=80), nullable=True))
        batch_op.alter_column("customer_id", existing_type=sa.String(length=32), nullable=True)
        batch_op.create_check_constraint("ck_bookings_customer_or_guest", EITHER_OR)


def downgrade() -> None:
    # Going back would have to delete every guest booking - a real person's
    # appointment. It refuses instead; whoever runs it decides about them first.
    guests = (
        op.get_bind().execute(sa.text("SELECT count(*) FROM bookings WHERE guest_name IS NOT NULL")).scalar()
    )
    if guests:
        raise RuntimeError(f"{guests} guest booking(s) would be lost; cancel or reassign them first")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint("ck_bookings_customer_or_guest", type_="check")
        batch_op.alter_column("customer_id", existing_type=sa.String(length=32), nullable=False)
        batch_op.drop_column("guest_name")
