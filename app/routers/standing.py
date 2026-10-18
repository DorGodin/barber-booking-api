"""A customer turns a booking into their regular time, and stops it. The next booking is made by
app/standing.py once this one has begun."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.deps import db, require, settings
from app.errors import DomainError, not_found
from app.models import Booking, StandingBooking, User, now_utc
from app.routers.bookings import _view

router = APIRouter(tags=["standing"])


class StandingIn(BaseModel):
    every_weeks: Literal[2, 3, 4]


@router.post("/bookings/{booking_id}/standing", status_code=201)
def make_standing(
    booking_id: str,
    body: StandingIn,
    user: User = Depends(require("customer")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The same barber, service and hour every few weeks, from this booking on. Somebody else's
    booking is not found; one for two people, one that is over or cancelled, cannot stand."""
    with write_lock(session):
        booking = session.get(Booking, booking_id)
        if booking is None or booking.customer_id != user.id:
            raise not_found("booking")
        if booking.status != "confirmed" or booking.start_utc <= now_utc():
            raise DomainError(409, "standing_not_ahead", "only a booking still to come can stand")
        if booking.group_id is not None:
            raise DomainError(409, "standing_group", "a booking for two cannot stand")
        current = session.get(StandingBooking, booking.standing_id) if booking.standing_id else None
        if current is not None and current.stopped_at is None:
            raise DomainError(409, "already_standing", "this booking already stands")
        standing = StandingBooking(
            customer_id=user.id,
            barber_id=booking.barber_id,
            service_id=booking.service_id,
            every_weeks=body.every_weeks,
        )
        session.add(standing)
        session.flush()
        booking.standing_id = standing.id
    return _view(session, booking, config)


@router.post("/standing/{standing_id}/stop", status_code=204)
def stop_standing(standing_id: str, user: User = Depends(require("customer")), session: Session = Depends(db)):
    """No more bookings made for it. The one already made stays, a booking like any other."""
    with write_lock(session):
        standing = session.get(StandingBooking, standing_id)
        if standing is None or standing.customer_id != user.id:
            raise not_found("standing booking")
        if standing.stopped_at is None:
            standing.stopped_at = now_utc()
    return Response(status_code=204)
