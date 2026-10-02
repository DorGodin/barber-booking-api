"""The database's tables follow app/models.py through migrations - on a fresh
database, on one from before migrations, and on one already up to date."""

from __future__ import annotations

from pprint import pformat

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import Base, make_sessionmaker
from app.migrate import BASELINE, alembic_config
from app.models import User, new_id, now_utc
from tests.conftest import start, version

HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


def a_database_from_before_migrations(engine) -> None:
    """The tables as create_all made them until migrations came - the
    baseline's, not today's models', which go on changing - with no record of
    a migration, and a customer who already signed up."""
    with engine.connect() as connection, connection.begin():
        command.upgrade(alembic_config(connection), BASELINE)
        connection.exec_driver_sql("DROP TABLE alembic_version")
    with make_sessionmaker(engine)() as session:
        session.add(
            User(
                id=new_id("usr"),
                username="early.customer",
                password_hash="x",
                role="customer",
                display_name="לקוח ותיק",
                created_at=now_utc(),
            )
        )
        session.commit()


def usernames(engine) -> list[str]:
    with make_sessionmaker(engine)() as session:
        return sorted(session.scalars(User.__table__.select().with_only_columns(User.username)))


def test_the_migrations_build_exactly_what_the_models_describe(engine):
    start(engine)

    with engine.connect() as connection:
        drift = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
        )

    assert drift == [], (
        'app/models.py changed without a migration - run: make migration m="what changed"\n' + pformat(drift)
    )
    assert version(engine) == HEAD


def test_the_migrations_are_one_line_with_no_branches():
    # Two migrations written in parallel on one parent give two heads, and
    # the server would refuse to start: "multiple heads".
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_a_database_from_before_migrations_is_marked_and_keeps_its_customers(engine):
    a_database_from_before_migrations(engine)

    start(engine)

    assert version(engine) == HEAD
    # Still the one customer, and nobody seeded over them.
    assert usernames(engine) == ["early.customer"]


def test_starting_again_on_an_up_to_date_database_changes_nothing(engine):
    start(engine)
    before = usernames(engine)

    start(engine)

    assert version(engine) == HEAD
    assert usernames(engine) == before


def test_foreign_keys_are_on_again_when_the_connection_serves_requests(engine):
    start(engine)

    # The connection the migration used goes back to the pool and serves the
    # next request. Off, a booking for a barber who does not exist would save.
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_a_migration_that_would_leave_a_broken_reference_is_not_committed(engine):
    a_database_from_before_migrations(engine)
    with engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql(
            "INSERT INTO barber_hours (barber_id, hours_json) VALUES ('usr_gone', '{}')"
        )
        connection.commit()
        connection.connection.driver_connection.execute("PRAGMA foreign_keys=ON")

    with pytest.raises(RuntimeError, match="references to rows that do not exist"):
        start(engine)

    assert version(engine) is None


def test_the_migrations_go_down_and_up_again(engine):
    with engine.connect() as connection, connection.begin():
        config = alembic_config(connection)
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")

    assert version(engine) == HEAD


def test_a_booking_from_before_guest_bookings_keeps_its_customer_and_gains_the_check(engine):
    with engine.connect() as connection, connection.begin():
        command.upgrade(alembic_config(connection), "0001")
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at) VALUES "
            "('usr_c', 'early.customer', 'x', 'customer', 'C', '2026-10-01 10:00:00'), "
            "('usr_b', 'early.barber', 'x', 'barber', 'B', '2026-10-01 10:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO services (id, name, duration_minutes, price_minor, currency, active) "
            "VALUES ('svc_1', 'תספורת', 30, 8000, 'ILS', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO bookings (id, customer_id, barber_id, service_id, start_utc, end_utc, status, "
            "price_minor, currency, created_at) VALUES ('bkg_old', 'usr_c', 'usr_b', 'svc_1', "
            "'2026-12-01 08:00:00', '2026-12-01 08:30:00', 'confirmed', 8000, 'ILS', '2026-10-01 10:00:00')"
        )

    start(engine)

    assert version(engine) == HEAD
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT customer_id, guest_name FROM bookings WHERE id = 'bkg_old'"
        ).one() == ("usr_c", None)
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE bookings SET customer_id = NULL WHERE id = 'bkg_old'")
