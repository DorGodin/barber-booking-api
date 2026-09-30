"""Engine, sessions, and the one lock that makes double booking impossible.

SQLite only serialises writers that ask for it. A booking is check-then-insert:
two requests can both check, both see a free slot, and both insert. The check
and the insert must therefore run inside a transaction that takes the write
lock at BEGIN, not at the first INSERT - that is BEGIN IMMEDIATE. The second
request then waits, and its check sees the first request's booking.

A lock in Python memory would not do: it protects one process, and the server
runs several.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

IMMEDIATE = "sqlite_begin_immediate"


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection, _record):
            # Take transaction control away from the driver, which would
            # otherwise issue its own deferred BEGIN and ignore ours.
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _on_begin(connection):
            immediate = connection.get_execution_options().get(IMMEDIATE, False)
            connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


def make_sessionmaker(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def write_lock(session: Session) -> Iterator[Session]:
    """Run the block holding the database write lock from its first statement.

    The request has usually read already - authentication loads the user - so
    the session holds an ordinary transaction by the time it gets here, and
    SQLAlchemy ignores execution options on a connection that is already
    established. It says so only in a warning. Ending that read first makes the
    next connection begin with BEGIN IMMEDIATE, for real. pytest.ini turns the
    warning into an error so this cannot silently come back.
    """
    if session.in_transaction():
        session.commit()
    session.connection(execution_options={IMMEDIATE: True})
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
