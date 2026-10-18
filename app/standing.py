"""A customer's regular time: the same barber, service and hour every few weeks. Only the next booking is
ever held - the one after it is made once that one has begun - so a standing booking takes one place
toward the limit and never fills a diary months ahead.

Made by the loop every worker runs (as the reminders are), under the write lock: the check that no
booking of it is ahead is inside the lock, so two workers looking at once make it once. A time that
cannot be kept - taken, the barber off, the customer at the limit - is skipped and the customer told,
once; the next is looked for from there."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import write_lock
from app.errors import DomainError
from app.models import Booking, StandingBooking, User, now_utc
from app.push import PushHub
from app.reminders import when_words
from app.scheduling import local_instant


@dataclass
class Told:
    user_ids: list[str]
    notice: tuple[str, str]


def next_start(standing: StandingBooking, anchor: datetime, now: datetime, config: Settings) -> datetime:
    """The first time after now that is a whole number of the standing's weeks after the anchor, at the
    anchor's hour on the shop's clock - across a change of clock too."""
    local = anchor.astimezone(config.shop_tz)
    minute = local.hour * 60 + local.minute
    weeks = standing.every_weeks
    while True:
        local_day = local.date() + timedelta(weeks=weeks)
        start = local_instant(local_day, minute, config.shop_tz)
        if start > now:
            return start
        weeks += standing.every_weeks


def renew_due(session: Session, config: Settings, now: datetime) -> list[Told]:
    from app.routers.bookings import place_booking  # the page's own booking, refused for the same reasons

    told: list[Told] = []
    with write_lock(session):
        owners = session.scalars(select(User.id).where(User.role == "owner", User.active.is_(True))).all()
        for standing in session.scalars(select(StandingBooking).where(StandingBooking.stopped_at.is_(None))):
            made = session.scalars(
                select(Booking).where(Booking.standing_id == standing.id).order_by(Booking.start_utc.desc())
            ).all()
            if not made:
                continue
            latest = made[0]
            ahead = any(b.status == "confirmed" and b.start_utc > now for b in made)
            anchor = max(latest.start_utc, standing.skipped_until or latest.start_utc)
            if ahead or anchor > now:
                continue
            start = next_start(standing, anchor, now, config)
            # Every refusal is raised before anything is added, so a refused time leaves nothing behind.
            try:
                booking = place_booking(
                    session,
                    config,
                    standing.customer_id,
                    standing.barber_id,
                    standing.service_id,
                    start,
                    now,
                    standing_id=standing.id,
                )
            except DomainError:
                standing.skipped_until = start
                told.append(
                    Told(
                        [standing.customer_id],
                        (
                            "לא הצלחנו לשמור את התור הקבוע",
                            f"{when_words(start, now, config)} לא פנוי · אפשר לבחור שעה אחרת",
                        ),
                    )
                )
                continue
            when = when_words(booking.start_utc, now, config)
            told.append(Told([standing.customer_id], ("התור הקבוע הבא נקבע", when)))
            told.append(Told(list(dict.fromkeys([booking.barber_id, *owners])), ("תור קבוע ביומן", when)))
    return told


def renew(maker: sessionmaker[Session], hub: PushHub, config: Settings, now: datetime | None = None) -> int:
    """Make the next booking of every standing booking that is due. Made first, told after."""
    with maker() as session:
        told = renew_due(session, config, now or now_utc())
    for each in told:
        hub.tell(each.user_ids, each.notice)
    return len(told)


async def standing(maker: sessionmaker[Session], hub: PushHub, config: Settings) -> None:
    while True:
        await asyncio.sleep(config.reminder_check_seconds)
        try:
            await asyncio.to_thread(renew, maker, hub, config)
        except Exception:  # noqa: BLE001 - the loop must outlive one bad turn
            continue
