"""Bring the database's tables to the shape app/models.py describes.

The tables used to be made by create_all, which creates a missing table and
never touches one that exists: a column added to a model reached a fresh
database and no running shop, whose server then failed on the first query that
named it. Every change to a model now comes with a migration in
app/migrations/versions, and the server applies the ones a database has not
had yet when it starts.

A database from before migrations has the tables and no record of which
migration it is at. Its tables are exactly the first migration's, so it is
marked as being there and continues from it - with its data.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect

MIGRATIONS = Path(__file__).parent / "migrations"
BASELINE = "0001"


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["connection"] = connection
    return config


def migrate(connection: Connection, before_changes: Callable[[str], None] | None = None) -> None:
    """Apply every migration the database has not had, inside the caller's
    transaction - so several workers starting at once take turns, and the one
    that waits finds the work done.

    `before_changes(target)` runs first when a database that has data is about
    to be changed - the server backs it up there. If it raises, nothing is
    changed."""
    tables = inspect(connection).get_table_names()
    config = alembic_config(connection)
    head = ScriptDirectory.from_config(config).get_current_head()
    if "users" in tables:
        current = MigrationContext.configure(connection).get_current_revision() or BASELINE
        if current != head and before_changes is not None:
            before_changes(head)
    if "alembic_version" not in tables and "users" in tables:
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")
    # SQLite changes a column by copying the table, with foreign keys off for
    # the copy - see prepare_database. Nothing may be left pointing at a row
    # that is gone when they come back on.
    if connection.dialect.name == "sqlite":
        broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"a migration left references to rows that do not exist: {broken[:5]}")
