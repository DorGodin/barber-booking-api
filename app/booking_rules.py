"""The rules a booking must satisfy, used by BOTH the availability listing and
the booking itself.

If the two computed their answers separately, the listing would sooner or later
offer a slot that the booking then refuses - the most common defect in any
booking product. Everything that decides "is this bookable" lives here, once.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import DomainError, not_found
from app.models import BarberHours, Booking, Service, TimeOff, User
from app.scheduling import Interval, is_aligned, working_window


def latest_start(config: Settings, now: datetime) -> datetime:
    return now + timedelta(days=config.booking_window_days)


def barber_or_404(session: Session, barber_id: str) -> User:
    barber = session.get(User, barber_id)
    if barber is None or barber.role != "barber":
        raise not_found("barber")
    return barber


def bookable_barber_or_error(session: Session, barber_id: str) -> User:
    """A barber who can be booked: exists, and has not left."""
    barber = barber_or_404(session, barber_id)
    if not barber.active:
        raise DomainError(422, "barber_inactive", "that barber no longer works here")
    return barber


def active_service_or_error(session: Session, service_id: str) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise not_found("service")
    if not service.active:
        raise DomainError(422, "service_inactive", "that service is no longer offered")
    return service


def hours_for(session: Session, barber_id: str) -> dict:
    row = session.get(BarberHours, barber_id)
    return row.hours if row else {}


def is_off(session: Session, barber_id: str, day: date) -> bool:
    return (
        session.scalar(select(TimeOff).where(TimeOff.barber_id == barber_id, TimeOff.day == day.isoformat()))
        is not None
    )


def visible_booking_or_404(session: Session, booking_id: str, user: User) -> Booking:
    """Somebody else's booking is not found, not forbidden. A 403 would confirm
    it exists, and ids travel in links and screenshots."""
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise not_found("booking")
    if user.role == "customer" and booking.customer_id != user.id:
        raise not_found("booking")
    if user.role == "barber" and booking.barber_id != user.id:
        raise not_found("booking")
    return booking


def busy(
    session: Session,
    window: Interval,
    *,
    barber_id: str | None = None,
    customer_id: str | None = None,
    excluding: str | None = None,
) -> list[Interval]:
    """Confirmed bookings near the window - touching it included.

    This is a candidate fetch, not the overlap rule. The rule is
    Interval.overlaps, and every caller decides with it: the listing and the
    booking once decided overlap separately, one in SQL and one in Python, and a
    change to one would have left the other offering what it refused.

    `excluding` is the booking being moved: its own time is not in its way.
    """
    query = select(Booking).where(
        Booking.status == "confirmed", Booking.start_utc <= window.end, Booking.end_utc >= window.start
    )
    if barber_id is not None:
        query = query.where(Booking.barber_id == barber_id)
    if customer_id is not None:
        query = query.where(Booking.customer_id == customer_id)
    if excluding is not None:
        query = query.where(Booking.id != excluding)
    return [Interval(b.start_utc, b.end_utc) for b in session.scalars(query)]


def clashes(wanted: Interval, candidates: list[Interval]) -> bool:
    return any(wanted.overlaps(other) for other in candidates)


def day_window(session: Session, config: Settings, barber_id: str, day: date) -> Interval | None:
    """The barber's working interval that local day, or None when they do not work it."""
    if is_off(session, barber_id, day):
        return None
    return working_window(day, hours_for(session, barber_id), config.shop_tz)


def check_date_in_range(config: Settings, day: date, now: datetime) -> None:
    today = now.astimezone(config.shop_tz).date()
    last = latest_start(config, now).astimezone(config.shop_tz).date()
    if day < today:
        raise DomainError(422, "in_past", f"{day} has already passed")
    if day > last:
        raise DomainError(
            422, "beyond_window", f"bookings open {config.booking_window_days} days ahead, until {last}"
        )


def check_bookable(
    session: Session, config: Settings, barber_id: str, service: Service, start: datetime, now: datetime
) -> Interval:
    """Everything except overlap with other bookings, which needs the write lock."""
    if not is_aligned(start):
        raise DomainError(422, "not_aligned", "bookings start on the quarter hour")
    if start <= now:
        raise DomainError(422, "in_past", "that time has already passed")
    if start > latest_start(config, now):
        raise DomainError(422, "beyond_window", f"bookings open {config.booking_window_days} days ahead")

    wanted = Interval(start, start + timedelta(minutes=service.duration_minutes))
    local_day = start.astimezone(config.shop_tz).date()
    if is_off(session, barber_id, local_day):
        raise DomainError(422, "barber_off", "the barber is not working that day")
    window = working_window(local_day, hours_for(session, barber_id), config.shop_tz)
    if window is None or not window.contains(wanted):
        raise DomainError(422, "outside_hours", "that does not fit inside the barber's working hours")
    return wanted
