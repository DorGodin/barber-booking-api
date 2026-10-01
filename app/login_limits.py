"""How many wrong passwords a sign-in may take before it is refused for a while.

Two counts, over the same window: failures for one username from one address -
someone guessing one person's password - and failures from one address - one
password tried across many usernames. Either one over its limit refuses the
sign-in, with the right password too: a lock that still says yes to the right
password keeps the guessing going, it only slows it.

The account count is per address, not per username alone. Counted per username,
five wrong guesses from anywhere would lock the real owner out of their own shop
- a lock anyone can set is a way to shut the shop, not to protect it.

A username that does not exist is counted like any other, so a refusal never
says whether an account is there.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.models import LoginFailure


def seconds_locked(session: Session, config: Settings, username: str, ip: str, now: datetime) -> int:
    """0 when a sign-in may be tried; otherwise how long until it may."""
    window = timedelta(minutes=config.login_lock_minutes)
    since = now - window
    waits = []
    for match, limit in (
        ((LoginFailure.username == username, LoginFailure.ip == ip), config.login_max_failures),
        ((LoginFailure.ip == ip,), config.login_max_failures_per_ip),
    ):
        times = session.scalars(
            select(LoginFailure.at).where(*match, LoginFailure.at > since).order_by(LoginFailure.at)
        ).all()
        if len(times) >= limit:
            # Locked until enough of these failures have aged out of the window.
            frees_at = times[len(times) - limit] + window
            waits.append(math.ceil((frees_at - now).total_seconds()))
    return max(waits, default=0)


# Under the write lock, taken at BEGIN, like every other write here: a sign-in
# reads first, and two workers that both read and then try to write deadlock in
# SQLite - one of them answered "database is locked", a 500. Two sign-ins at once
# were enough.
def record_failure(session: Session, config: Settings, username: str, ip: str, now: datetime) -> None:
    with write_lock(session):
        session.execute(
            delete(LoginFailure).where(LoginFailure.at <= now - timedelta(minutes=config.login_lock_minutes))
        )
        session.add(LoginFailure(username=username, ip=ip, at=now))


def forget_failures(session: Session, username: str, ip: str) -> None:
    with write_lock(session):
        session.execute(delete(LoginFailure).where(LoginFailure.username == username, LoginFailure.ip == ip))
