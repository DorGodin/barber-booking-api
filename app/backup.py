"""Copies of the shop's database, and putting one back.

Everything the shop has - customers, bookings, hours - is one SQLite file. A
copy is made with SQLite's own backup, never by copying the file: in WAL mode
the latest writes may still be in barber.db-wal, and a file copied while the
server writes can come out torn. The backup reads a consistent snapshot, so it
is safe while the server runs. Every copy is checked before it counts.

    python -m app.backup create            # what `make backup` runs
    python -m app.backup list
    python -m app.backup restore <file>    # what `make restore` runs, server stopped
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

PREFIX = "barber-"


def database_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"backups are for a SQLite file, not {database_url}")
    return Path(database_url.removeprefix("sqlite:///"))


def backup_dir(database: Path, configured: str = "") -> Path:
    """Next to the database unless set: in the container that is the /data
    volume, which outlives the container."""
    return Path(configured) if configured else database.parent / "backups"


def check(path: Path) -> None:
    """A copy that is not a whole, readable database is not a backup."""
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"{path} is not a readable database: {exc}") from exc
    if result != "ok":
        raise RuntimeError(f"{path} failed the integrity check: {result}")


def create(database: Path, directory: Path, kept: int, label: str = "manual") -> Path:
    if not database.exists():
        raise FileNotFoundError(f"no database at {database}")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"{PREFIX}{stamp}-{label}.db"
    source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    check(target)
    prune(directory, kept)
    return target


def backups(directory: Path) -> list[Path]:
    """Oldest first: the name starts with the time it was made."""
    return sorted(directory.glob(f"{PREFIX}*.db")) if directory.exists() else []


def prune(directory: Path, kept: int) -> None:
    for old in backups(directory)[:-kept] if kept > 0 else []:
        old.unlink()


def restore(copy: Path, database: Path, directory: Path, kept: int) -> Path | None:
    """Put a backup in place of the database. The server must be stopped:
    `make restore` refuses while it runs. What is replaced is backed up first,
    so a restore from the wrong file can itself be undone."""
    check(copy)
    replaced = create(database, directory, kept + 1, "before-restore") if database.exists() else None
    source = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    live = sqlite3.connect(database)
    try:
        source.backup(live)
    finally:
        live.close()
        source.close()
    check(database)
    return replaced


def main(argv: list[str]) -> int:
    database = database_path(os.environ.get("DATABASE_URL", "sqlite:///./barber.db"))
    directory = backup_dir(database, os.environ.get("BACKUP_DIR", ""))
    kept = int(os.environ.get("BACKUPS_KEPT", "10"))
    match argv:
        case ["create"]:
            print(f"backed up to {create(database, directory, kept)}")
        case ["list"]:
            for path in backups(directory):
                print(path)
        case ["restore", name]:
            copy = Path(name) if Path(name).exists() else directory / name
            replaced = restore(copy, database, directory, kept)
            print(f"restored {database} from {copy}")
            if replaced:
                print(f"what it replaced is in {replaced}")
        case _:
            print(__doc__.split("\n\n")[-1])
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, RuntimeError, ValueError) as exc:
        sys.exit(f"stopped: {exc}")
