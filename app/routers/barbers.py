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
    busy,
    check_date_in_range,
    day_window,
    hours_for,
    latest_start,
)
from app.config import Settings
from app.deps import current_user, db, require, settings
from app.errors import DomainError
from app.models import BarberHours, TimeOff, User
from app.scheduling import available_starts
from app.schemas import AccountIn, HoursIn, TimeOffIn
from app.security import hash_password
from app.views import barber_view, iso_utc, page

router = APIRouter(tags=["barbers"])

# The shop is open Sunday to Thursday, ten to seven. A new barber starts on
# those hours; the owner changes them per barber.
SHOP_DAYS = ("sun", "mon", "tue", "wed", "thu")
SHOP_OPEN, SHOP_CLOSE = "10:00", "19:00"
DEFAULT_HOURS = {
    day: ([SHOP_OPEN, SHOP_CLOSE] if day in SHOP_DAYS else None)
    for day in ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
}


@router.get("/barbers")
def list_barbers(_: User = Depends(current_user), session: Session = Depends(db)):
    rows = session.scalars(select(User).where(User.role == "barber").order_by(User.display_name)).all()
    return page(len(rows), [barber_view(b) for b in rows])


@router.post("/barbers", status_code=201)
def create_barber(body: AccountIn, _: User = Depends(require("owner")), session: Session = Depends(db)):
    if session.scalar(select(User).where(User.username == body.username)):
        raise DomainError(409, "username_taken", "that username is taken")
    barber = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="barber",
        display_name=body.display_name,
    )
    session.add(barber)
    session.flush()
    session.add(BarberHours(barber_id=barber.id, hours_json=json.dumps(DEFAULT_HOURS)))
    session.commit()
    return barber_view(barber)


@router.get("/barbers/{barber_id}/hours")
def get_hours(barber_id: str, _: User = Depends(current_user), session: Session = Depends(db)):
    barber_or_404(session, barber_id)
    return {"barber_id": barber_id, "hours": hours_for(session, barber_id)}


@router.put("/barbers/{barber_id}/hours")
def set_hours(
    barber_id: str, body: HoursIn, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    barber_or_404(session, barber_id)
    row = session.get(BarberHours, barber_id)
    if row is None:
        session.add(BarberHours(barber_id=barber_id, hours_json=json.dumps(body.hours)))
    else:
        row.hours_json = json.dumps(body.hours)
    session.commit()
    return {"barber_id": barber_id, "hours": body.hours}


@router.post("/barbers/{barber_id}/time-off", status_code=201)
def add_time_off(
    barber_id: str, body: TimeOffIn, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    barber_or_404(session, barber_id)
    session.add(TimeOff(barber_id=barber_id, day=body.date.isoformat()))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainError(409, "already_off", f"already off on {body.date}") from None
    return {"barber_id": barber_id, "date": body.date.isoformat()}


@router.delete("/barbers/{barber_id}/time-off/{day}", status_code=204)
def remove_time_off(
    barber_id: str, day: date, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    barber_or_404(session, barber_id)
    session.execute(delete(TimeOff).where(TimeOff.barber_id == barber_id, TimeOff.day == day.isoformat()))
    session.commit()


@router.get("/barbers/{barber_id}/availability")
def availability(
    barber_id: str,
    day: date = Query(alias="date"),
    service_id: str = Query(),
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    barber_or_404(session, barber_id)
    service = active_service_or_error(session, service_id)
    now = datetime.now(UTC)
    check_date_in_range(config, day, now)

    window = day_window(session, config, barber_id, day)
    taken = []
    if window is not None:
        taken = busy(session, window, barber_id=barber_id)
        # A customer is never offered a slot that clashes with their own
        # booking at another barber - the booking would refuse it.
        if user.role == "customer":
            taken += busy(session, window, customer_id=user.id)

    starts = available_starts(
        window, timedelta(minutes=service.duration_minutes), taken, now, latest_start(config, now)
    )
    return {
        "barber_id": barber_id,
        "service_id": service_id,
        "date": day.isoformat(),
        "slots": [
            {"start": iso_utc(s), "start_local": s.astimezone(config.shop_tz).isoformat()} for s in starts
        ],
    }
