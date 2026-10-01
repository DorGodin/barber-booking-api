"""First-run data: an owner, four barbers on alternating days, two customers,
the menu, and a scattering of bookings so the grid is not an empty week.

Passwords come from the environment and are never defaulted - an account whose
password is in the repository is an account anyone can use. Every seeded barber
signs in with SEED_BARBER_PASSWORD and both customers with SEED_CUSTOMER_PASSWORD.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.models import BarberHours, Booking, Service, User
from app.routers.barbers import SHOP_CLOSE, SHOP_OPEN
from app.scheduling import WEEKDAYS, local_instant, parse_hhmm
from app.security import hash_password

OWNER = ("owner", "בעל המספרה")
CUSTOMERS = (("customer", "דנה"), ("yael", "יעל"))
MENU = (("תספורת", 30, 8000), ("סידור זקן", 15, 4000), ("תספורת וזקן", 45, 11000))

# Who works which days. Avi is in every day the shop is open; the others take
# turns, so each day has a different line-up.
BARBERS = (
    ("barber", "אבי", ("sun", "mon", "tue", "wed", "thu")),
    ("barber.yossi", "יוסי", ("sun", "tue", "thu")),
    ("barber.moran", "מורן", ("mon", "wed")),
    ("barber.ron", "רון", ("sun", "mon", "tue")),
)

# Yael already has a haircut booked every two hours with each barber for the
# next working days, each barber half an hour after the one before - so the
# grid shows free and taken times alternating, and Yael is never in two chairs.
SEEDED_DAYS = 5
EVERY = timedelta(hours=2)


def _password(variable: str) -> str:
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError(f"the database is empty and cannot be seeded: set {variable}. See .env.example.")
    return value


def _account(session: Session, username: str, name: str, role: str, password: str) -> User:
    user = User(username=username, password_hash=hash_password(password), role=role, display_name=name)
    session.add(user)
    session.flush()
    return user


def _seed_bookings(
    session: Session, config: Settings, barbers: list[tuple[User, tuple]], customer: User, service: Service
) -> int:
    today = datetime.now(UTC).astimezone(config.shop_tz).date()
    opening, closing = parse_hhmm(SHOP_OPEN), parse_hhmm(SHOP_CLOSE)
    made = 0
    for index, (barber, days) in enumerate(barbers):
        worked, day = 0, today
        while worked < SEEDED_DAYS:
            day += timedelta(days=1)
            if WEEKDAYS[day.weekday()] not in days:
                continue
            worked += 1
            start = local_instant(day, opening, config.shop_tz) + timedelta(minutes=30 * index)
            end_of_day = local_instant(day, closing, config.shop_tz)
            while start + timedelta(minutes=service.duration_minutes) <= end_of_day:
                session.add(
                    Booking(
                        customer_id=customer.id,
                        barber_id=barber.id,
                        service_id=service.id,
                        start_utc=start,
                        end_utc=start + timedelta(minutes=service.duration_minutes),
                        price_minor=service.price_minor,
                        currency=service.currency,
                    )
                )
                made += 1
                start += EVERY
    return made


def seed_if_empty(session: Session, config: Settings) -> bool:
    """Seed the shop if it is empty, under the write lock: the emptiness check
    and the inserts are one step, so two workers can never both see an empty
    database and both seed it."""
    with write_lock(session):
        if session.scalar(select(func.count()).select_from(User)):
            return False
        _seed(session, config)
    return True


def _seed(session: Session, config: Settings) -> None:
    owner_password = _password("SEED_OWNER_PASSWORD")
    barber_password = _password("SEED_BARBER_PASSWORD")
    customer_password = _password("SEED_CUSTOMER_PASSWORD")

    _account(session, *OWNER, "owner", owner_password)
    customers = [
        _account(session, username, name, "customer", customer_password) for username, name in CUSTOMERS
    ]
    barbers = []
    for username, name, days in BARBERS:
        barber = _account(session, username, name, "barber", barber_password)
        hours = {day: ([SHOP_OPEN, SHOP_CLOSE] if day in days else None) for day in WEEKDAYS}
        session.add(BarberHours(barber_id=barber.id, hours_json=json.dumps(hours)))
        barbers.append((barber, days))
    services = [
        Service(name=name, duration_minutes=minutes, price_minor=price) for name, minutes, price in MENU
    ]
    session.add_all(services)
    session.flush()

    _seed_bookings(session, config, barbers, customers[1], services[0])
