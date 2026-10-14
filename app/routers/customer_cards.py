"""A customer as the staff know them: how often they came, cancelled or did not come, and the note
the staff keep about them. The owner sees every customer; a barber, the ones who booked with them."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import write_lock
from app.deps import db, require
from app.errors import not_found
from app.models import Booking, BookingMove, User
from app.schemas import NoteIn
from app.views import iso_utc

router = APIRouter(tags=["customers"])


def _customer_or_404(session: Session, customer_id: str, viewer: User) -> User:
    """Somebody the viewer may not know of is not found, not forbidden - as a booking is."""
    customer = session.get(User, customer_id)
    if customer is None or customer.role != "customer":
        raise not_found("customer")
    if viewer.role == "barber" and not session.scalar(
        select(Booking.id).where(Booking.customer_id == customer.id, Booking.barber_id == viewer.id).limit(1)
    ):
        raise not_found("customer")
    return customer


def _count(session: Session, *conditions) -> int:
    return session.scalar(select(func.count()).select_from(Booking).where(*conditions)) or 0


def _card(session: Session, customer: User, viewer: User) -> dict:
    now = datetime.now(UTC)
    mine = Booking.customer_id == customer.id
    came = (mine, Booking.status == "confirmed", Booking.no_show.is_(False), Booking.end_utc <= now)
    last = session.scalar(select(func.max(Booking.start_utc)).where(*came))
    return {
        "id": customer.id,
        "name": customer.display_name,
        # The owner may call them; a barber has no need of the number.
        "phone": customer.phone if viewer.role == "owner" else None,
        "since": iso_utc(customer.created_at),
        "visits": _count(session, *came),
        "last_visit": iso_utc(last),
        "upcoming": _count(session, mine, Booking.status == "confirmed", Booking.start_utc > now),
        "cancellations": _count(
            session, mine, Booking.status == "cancelled", Booking.cancelled_by == customer.id
        ),
        "no_shows": _count(session, mine, Booking.no_show.is_(True)),
        "moves": session.scalar(
            select(func.count()).select_from(BookingMove).where(BookingMove.customer_id == customer.id)
        )
        or 0,
        "note": customer.staff_note or "",
    }


@router.get("/customers/{customer_id}/card")
def customer_card(
    customer_id: str, viewer: User = Depends(require("barber", "owner")), session: Session = Depends(db)
):
    return _card(session, _customer_or_404(session, customer_id, viewer), viewer)


@router.put("/customers/{customer_id}/note")
def keep_note(
    customer_id: str,
    body: NoteIn,
    viewer: User = Depends(require("barber", "owner")),
    session: Session = Depends(db),
):
    """The note is the staff's, shared between the owner and the barbers; empty, it is gone."""
    with write_lock(session):
        customer = _customer_or_404(session, customer_id, viewer)
        customer.staff_note = body.text or None
        return _card(session, customer, viewer)
