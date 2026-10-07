from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.booking_rules import (
    active_service_or_error,
    barber_or_404,
    bookable_barber_or_error,
    busy,
    check_date_in_range,
    day_window,
    hours_for,
    latest_start,
    visible_booking_or_404,
)
from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, require, settings
from app.errors import DomainError
from app.models import BarberHours, Service, TimeOff, User
from app.scheduling import available_starts
from app.schemas import AccountIn, BarberPatch, HoursIn, TimeOffIn
from app.security import hash_password
from app.views import barber_view, iso_utc, page

router = APIRouter(tags=["barbers"])

# The shop is open Sunday to Thursday, ten to seven, and Friday ten to two. A
# new barber starts on those hours; the owner changes them per barber.
SHOP_DAYS = ("sun", "mon", "tue", "wed", "thu")
SHOP_OPEN, SHOP_CLOSE = "10:00", "19:00"
FRIDAY_CLOSE = "14:00"


def shop_hours(day: str) -> list[str] | None:
    if day in SHOP_DAYS:
        return [SHOP_OPEN, SHOP_CLOSE]
    return [SHOP_OPEN, FRIDAY_CLOSE] if day == "fri" else None


DEFAULT_HOURS = {day: shop_hours(day) for day in ("sun", "mon", "tue", "wed", "thu", "fri", "sat")}


@router.get("/barbers")
def list_barbers(user: User = Depends(current_user), session: Session = Depends(db)):
    """The owner sees every barber, those who left included, to manage them and
    their bookings. Everyone else sees the ones who can be booked."""
    query = select(User).where(User.role == "barber").order_by(User.display_name)
    if user.role != "owner":
        query = query.where(User.active.is_(True))
    rows = session.scalars(query).all()
    return page(len(rows), [barber_view(b) for b in rows])


@router.patch("/barbers/{barber_id}")
def update_barber(
    barber_id: str, body: BarberPatch, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    """A barber who leaves is made inactive, not deleted: their bookings stay,
    for the owner to move or cancel one by one. A customer is not cancelled by
    the system without anyone deciding to."""
    with write_lock(session):
        barber = barber_or_404(session, barber_id)
        barber.active = body.active
    return barber_view(barber)


@router.post("/barbers", status_code=201)
def create_barber(body: AccountIn, _: User = Depends(require("owner")), session: Session = Depends(db)):
    # The hash is slow on purpose; it is made before the lock, not while holding it.
    password_hash = hash_password(body.password)
    with write_lock(session):
        if session.scalar(select(User).where(User.username == body.username)):
            raise DomainError(409, "username_taken", "that username is taken")
        barber = User(
            username=body.username, password_hash=password_hash, role="barber", display_name=body.display_name
        )
        session.add(barber)
        session.flush()
        session.add(BarberHours(barber_id=barber.id, hours_json=json.dumps(DEFAULT_HOURS)))
    return barber_view(barber)


@router.get("/barbers/{barber_id}/hours")
def get_hours(barber_id: str, _: User = Depends(current_user), session: Session = Depends(db)):
    barber_or_404(session, barber_id)
    return {"barber_id": barber_id, "hours": hours_for(session, barber_id)}


@router.put("/barbers/{barber_id}/hours")
def set_hours(
    barber_id: str, body: HoursIn, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    with write_lock(session):
        barber_or_404(session, barber_id)
        row = session.get(BarberHours, barber_id)
        if row is None:
            session.add(BarberHours(barber_id=barber_id, hours_json=json.dumps(body.hours)))
        else:
            row.hours_json = json.dumps(body.hours)
    return {"barber_id": barber_id, "hours": body.hours}


@router.post("/barbers/{barber_id}/time-off", status_code=201)
def add_time_off(
    barber_id: str, body: TimeOffIn, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    try:
        with write_lock(session):
            barber_or_404(session, barber_id)
            session.add(TimeOff(barber_id=barber_id, day=body.date.isoformat()))
    except IntegrityError:
        raise DomainError(409, "already_off", f"already off on {body.date}") from None
    return {"barber_id": barber_id, "date": body.date.isoformat()}


@router.get("/barbers/{barber_id}/time-off")
def list_time_off(barber_id: str, _: User = Depends(require("owner")), session: Session = Depends(db)):
    """The days a barber is off, so the owner can see them - adding and removing
    a day off was possible before; seeing which days were off was not."""
    barber_or_404(session, barber_id)
    days = session.scalars(
        select(TimeOff.day).where(TimeOff.barber_id == barber_id).order_by(TimeOff.day)
    ).all()
    return {"barber_id": barber_id, "days": list(days)}


@router.delete("/barbers/{barber_id}/time-off/{day}", status_code=204)
def remove_time_off(
    barber_id: str, day: date, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    with write_lock(session):
        barber_or_404(session, barber_id)
        session.execute(delete(TimeOff).where(TimeOff.barber_id == barber_id, TimeOff.day == day.isoformat()))


def free_starts(
    session: Session,
    config: Settings,
    user: User,
    barber_id: str,
    service: Service,
    day: date,
    now: datetime,
    moving: str | None,
    also: list[Service] | None = None,
) -> tuple[bool, list[datetime]]:
    """Whether the barber works that day, and the starts still free on it. One
    rule for the day's times and the month's counts: a day the calendar calls
    free always has a time to offer."""
    # For two people, back to back: the times where both fit one after the other, and at any
    # time only when every service works at any time.
    together = [service, *(also or [])]
    window = day_window(session, config, barber_id, day, any_time=all(s.any_time for s in together))
    if window is None:
        return False, []
    taken = busy(session, window, barber_id=barber_id, excluding=moving)
    # A customer is never offered a slot that clashes with their own booking
    # at another barber - the booking would refuse it.
    if user.role == "customer":
        taken += busy(session, window, customer_id=user.id, excluding=moving)
    duration = timedelta(minutes=sum(s.duration_minutes for s in together))
    return True, available_starts(window, duration, taken, now, latest_start(config, now))


@router.get("/barbers/{barber_id}/availability")
def availability(
    barber_id: str,
    day: date = Query(alias="date"),
    service_id: str = Query(),
    also: list[str] = Query(default=[], description="services for people booked back to back with the first"),
    moving: str | None = Query(
        default=None, description="a booking being moved: its own time counts as free"
    ),
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    bookable_barber_or_error(session, barber_id)
    service = active_service_or_error(session, service_id)
    now = datetime.now(UTC)
    check_date_in_range(config, day, now)
    if moving is not None:
        visible_booking_or_404(session, moving, user)

    _, starts = free_starts(
        session,
        config,
        user,
        barber_id,
        service,
        day,
        now,
        moving,
        [active_service_or_error(session, s) for s in also],
    )
    return {
        "barber_id": barber_id,
        "service_id": service_id,
        "date": day.isoformat(),
        "slots": [
            {"start": iso_utc(s), "start_local": s.astimezone(config.shop_tz).isoformat()} for s in starts
        ],
    }


@router.get("/barbers/{barber_id}/days")
def days_of_month(
    barber_id: str,
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, on the shop's calendar"),
    service_id: str = Query(),
    also: list[str] = Query(default=[], description="services for people booked back to back with the first"),
    moving: str | None = Query(
        default=None, description="a booking being moved: its own time counts as free"
    ),
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """For the month's calendar: each bookable day of the month - from today to
    the end of the booking window - whether the barber works it, and how many
    times are free."""
    bookable_barber_or_error(session, barber_id)
    service = active_service_or_error(session, service_id)
    now = datetime.now(UTC)
    if moving is not None:
        visible_booking_or_404(session, moving, user)

    others = [active_service_or_error(session, s) for s in also]
    year, number = map(int, month.split("-"))
    first = date(year, number, 1)
    after = date(year + number // 12, number % 12 + 1, 1)
    today = now.astimezone(config.shop_tz).date()
    last = latest_start(config, now).astimezone(config.shop_tz).date()
    if after <= today:
        raise DomainError(422, "in_past", f"{month} has already passed")
    if first > last:
        raise DomainError(
            422, "beyond_window", f"bookings open {config.booking_window_days} days ahead, until {last}"
        )

    days = []
    day = max(first, today)
    while day < after and day <= last:
        works, starts = free_starts(session, config, user, barber_id, service, day, now, moving, others)
        days.append({"date": day.isoformat(), "works": works, "free": len(starts)})
        day += timedelta(days=1)
    return {"barber_id": barber_id, "service_id": service_id, "month": month, "days": days}
