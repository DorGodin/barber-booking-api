"""The database's tables follow app/models.py through migrations - on a fresh
database, on one from before migrations, and on one already up to date."""

from __future__ import annotations

import secrets
from pathlib import Path
from pprint import pformat
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.config import Settings
from app.db import Base, make_engine, make_sessionmaker
from app.main import prepare_database
from app.migrate import BASELINE, alembic_config
from app.models import User, new_id, now_utc

HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    for role in ("owner", "barber", "customer"):
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", secrets.token_urlsafe(12))
    engine = make_engine(f"sqlite:///{tmp_path / 'shop.db'}")
    yield engine
    engine.dispose()


def start(engine) -> None:
    """What every worker does when the server starts."""
    config = Settings(
        database_url=str(engine.url),
        secret_key=secrets.token_hex(32),
        shop_tz=ZoneInfo("Asia/Jerusalem"),
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
    )
    prepare_database(engine, make_sessionmaker(engine), config)


def version(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


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
