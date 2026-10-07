"""A reminder to a customer before their booking: by push, a set time ahead. The shop has no job
that runs by itself, so each worker looks once in a while; every booking is claimed in one write
step, so with several workers it is still reminded once."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.booking_rules import approval_state
from app.config import Settings
from app.db import write_lock
from app.models import Booking, Service, User, now_utc
from app.push import PushHub


def when_words(start: datetime, now: datetime, config: Settings) -> str:
    local, today = start.astimezone(config.shop_tz), now.astimezone(config.shop_tz).date()
    clock = local.strftime("%H:%M")
    if local.date() == today:
        return f"היום ב־{clock}"
    if local.date() == today + timedelta(days=1):
        return f"מחר ב־{clock}"
    return f"ב־{local.strftime('%d.%m')} בשעה {clock}"


def claim_due(session: Session, config: Settings, now: datetime) -> list[list[Booking]]:
    """The bookings that are due a reminder, marked as reminded in the same step - grouped, so two
    made together are reminded of in one. A booking that waits for the barber, was cancelled or declined,
    or was made inside the reminder's own window is not due: a reminder right after booking says nothing."""
    window = timedelta(minutes=config.reminder_minutes)
    with write_lock(session):
        candidates = session.scalars(
            select(Booking)
            .where(
                Booking.status == "confirmed",
                Booking.customer_id.is_not(None),
                Booking.reminded_at.is_(None),
                Booking.start_utc > now,
                Booking.start_utc <= now + window,
            )
            .order_by(Booking.start_utc)
        ).all()
        due = [
            b
            for b in candidates
            if b.created_at <= b.start_utc - window and approval_state(b, now) in (None, "approved")
        ]
        # Made together, reminded together: the one due brings the one right after it, which the
        # window may not have reached yet.
        for group_id in {b.group_id for b in due if b.group_id}:
            mates = session.scalars(
                select(Booking).where(
                    Booking.group_id == group_id,
                    Booking.status == "confirmed",
                    Booking.reminded_at.is_(None),
                    Booking.start_utc > now,
                )
            ).all()
            due += [m for m in mates if m not in due and approval_state(m, now) in (None, "approved")]
        due.sort(key=lambda b: b.start_utc)
        groups: dict[str, list[Booking]] = defaultdict(list)
        for booking in due:
            booking.reminded_at = now
            groups[booking.group_id or booking.id].append(booking)
        return list(groups.values())


def words(session: Session, group: list[Booking], now: datetime, config: Settings) -> tuple[str, str]:
    first = group[0]
    barber = session.get(User, first.barber_id).display_name
    names = []
    for booking in group:
        service = session.get(Service, booking.service_id).name
        names.append(f"{service} ({booking.for_name})" if booking.for_name else service)
    return "תזכורת לתור", f"{when_words(first.start_utc, now, config)} · {' + '.join(names)} אצל {barber}"


def send_due(
    maker: sessionmaker[Session], hub: PushHub, config: Settings, now: datetime | None = None
) -> int:
    """Remind whoever is due. Claimed first, sent after: a push that fails is not tried again,
    which is better than telling a customer twice."""
    now = now or now_utc()
    with maker() as session:
        groups = claim_due(session, config, now)
        told = [(g[0].customer_id, words(session, g, now, config)) for g in groups]
    for customer_id, notice in told:
        hub.tell([customer_id], notice)
    return len(told)


async def reminders(maker: sessionmaker[Session], hub: PushHub, config: Settings) -> None:
    while True:
        await asyncio.sleep(config.reminder_check_seconds)
        try:
            await asyncio.to_thread(send_due, maker, hub, config)
        except Exception:  # noqa: BLE001 - the loop must outlive one bad turn
            continue
