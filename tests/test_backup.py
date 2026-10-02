"""Backups of the shop's database: made safely while it is in use, taken before
a migration changes it, and - the part that matters - put back with the data."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from app import backup, migrate
from app.db import make_sessionmaker
from app.models import User
from tests.conftest import start, version

KEPT = 10
HEAD = ScriptDirectory.from_config(migrate.alembic_config()).get_current_head()

# After whatever the newest migration is, so a real new one never collides with it.
NEXT = "9999"
A_LATER_MIGRATION = '''"""A note on every service - a migration from after this test was written."""

import sqlalchemy as sa
from alembic import op

revision = "{revision}"
down_revision = "{parent}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(sa.Column("note", sa.String(80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("note")
'''


def database(engine) -> Path:
    return Path(engine.url.database)


def usernames(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        return sorted(row[0] for row in connection.execute("SELECT username FROM users"))


def add_customer(engine, username: str) -> None:
    with make_sessionmaker(engine)() as session:
        session.add(User(username=username, password_hash="x", role="customer", display_name="לקוח"))
        session.commit()


@pytest.fixture
def deploy_a_new_release(tmp_path: Path, monkeypatch):
    """Deploy the next version of the server: today's migrations and one more."""

    def deploy() -> None:
        migrations = tmp_path / "migrations"
        shutil.copytree(migrate.MIGRATIONS, migrations, ignore=shutil.ignore_patterns("__pycache__"))
        head = ScriptDirectory.from_config(migrate.alembic_config()).get_current_head()
        (migrations / "versions" / f"{NEXT}_note.py").write_text(
            A_LATER_MIGRATION.format(revision=NEXT, parent=head)
        )
        monkeypatch.setattr(migrate, "MIGRATIONS", migrations)

    return deploy


def test_a_backup_comes_back_with_the_data_it_was_taken_with(engine, tmp_path):
    start(engine)
    add_customer(engine, "before.backup")
    taken = backup.create(database(engine), tmp_path / "backups", KEPT)

    add_customer(engine, "after.backup")
    engine.dispose()
    backup.restore(taken, database(engine), tmp_path / "backups", KEPT)

    assert "before.backup" in usernames(database(engine))
    assert "after.backup" not in usernames(database(engine))


def test_a_restore_keeps_what_it_replaced(engine, tmp_path):
    start(engine)
    taken = backup.create(database(engine), tmp_path / "backups", KEPT)
    add_customer(engine, "only.in.the.replaced.one")
    engine.dispose()

    replaced = backup.restore(taken, database(engine), tmp_path / "backups", KEPT)

    # Restoring the wrong file is not the end: what it replaced is a backup too.
    assert "only.in.the.replaced.one" in usernames(replaced)


def test_a_backup_taken_while_a_write_is_under_way_is_whole(engine, tmp_path):
    start(engine)
    with engine.connect() as writing:
        writing.exec_driver_sql("INSERT INTO signups (ip, at) VALUES ('203.0.113.9', '2026-10-02 10:00:00')")
        # The write is not committed: the copy is of the database without it,
        # and is a healthy database, not half of one.
        taken = backup.create(database(engine), tmp_path / "backups", KEPT)
        writing.rollback()

    backup.check(taken)
    with sqlite3.connect(taken) as connection:
        assert connection.execute("SELECT count(*) FROM signups").fetchone()[0] == 0


def test_a_new_release_backs_the_database_up_before_it_migrates_it(engine, tmp_path, deploy_a_new_release):
    start(engine, backup_dir=str(tmp_path / "backups"))
    add_customer(engine, "a.customer")

    deploy_a_new_release()
    start(engine, backup_dir=str(tmp_path / "backups"))

    assert version(engine) == NEXT
    [before] = backup.backups(tmp_path / "backups")
    assert before.name.endswith(f"-before-{NEXT}.db")
    # The copy is the database as it was: the old version, with the customer.
    with sqlite3.connect(before) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
    assert "a.customer" in usernames(before)


def test_no_backup_when_there_is_nothing_to_migrate(engine, tmp_path):
    start(engine, backup_dir=str(tmp_path / "backups"))
    start(engine, backup_dir=str(tmp_path / "backups"))

    assert backup.backups(tmp_path / "backups") == []


def test_a_backup_that_cannot_be_made_stops_the_migration(engine, tmp_path, deploy_a_new_release):
    start(engine)
    deploy_a_new_release()
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the backups folder should be")

    with pytest.raises(OSError):
        start(engine, backup_dir=str(blocked))

    assert version(engine) == HEAD


def test_a_file_that_is_not_a_database_is_never_restored(engine, tmp_path):
    start(engine)
    before = usernames(database(engine))
    junk = tmp_path / "barber-junk.db"
    junk.write_text("not a database")
    engine.dispose()

    with pytest.raises(RuntimeError, match="not a readable database"):
        backup.restore(junk, database(engine), tmp_path / "backups", KEPT)

    assert usernames(database(engine)) == before


def test_only_the_newest_backups_are_kept(engine, tmp_path):
    start(engine)
    made = [backup.create(database(engine), tmp_path / "backups", 3) for _ in range(5)]

    assert backup.backups(tmp_path / "backups") == made[-3:]


def test_a_backup_is_one_file_that_stands_on_its_own(engine, tmp_path):
    start(engine)
    made = backup.create(database(engine), tmp_path / "backups", KEPT)

    # The shop's database is in WAL mode - three files. Its backup must not be:
    # copied off the machine alone, the .db would miss what is in the others.
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == [made.name]
    with sqlite3.connect(made) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_pruning_leaves_nothing_behind_from_older_backups(engine, tmp_path):
    start(engine)
    directory = tmp_path / "backups"
    old = backup.create(database(engine), directory, KEPT)
    for leftover in ("-wal", "-shm"):
        old.with_name(old.name + leftover).write_bytes(b"")

    newest = [backup.create(database(engine), directory, 2) for _ in range(2)]

    assert sorted(p.name for p in directory.iterdir()) == sorted(p.name for p in newest)
