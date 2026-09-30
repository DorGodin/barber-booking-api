from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.booking_rules import active_service_or_error, barber_or_404, busy, check_bookable
from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, require, settings
from app.errors import DomainError, not_found
from app.models import Booking, IdempotencyKey, Service, User
from app.schemas import BookingIn
from app.views import booking_view, page

router = APIRouter(tags=["bookings"])


def _view(session: Session, booking: Booking, config: Settings) -> dict:
    return booking_view(booking, session.get(Service, booking.service_id).name, config.shop_tz)


def _visible_or_404(session: Session, booking_id: str, user: User) -> Booking:
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


@router.post("/bookings", status_code=201)
def create_booking(
    body: BookingIn,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(require("customer")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
        raise DomainError(422, "bad_idempotency_key", "Idempotency-Key must be 1 to 128 characters")
    request_hash = hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    start = body.start.astimezone(UTC)
    now = datetime.now(UTC)

    # Check and insert under one write lock, taken at BEGIN. Two requests for
    # the same slot then run one after the other, and the second one's check
    # sees the first one's booking.
    with write_lock(session):
        if idempotency_key is not None:
            seen = session.get(IdempotencyKey, (idempotency_key, user.id))
            if seen is not None:
                if seen.request_hash != request_hash:
                    raise DomainError(
                        409, "idempotency_mismatch", "that Idempotency-Key was used for a different booking"
                    )
                response.headers["Idempotent-Replayed"] = "true"
                return _view(session, session.get(Booking, seen.booking_id), config)

        barber_or_404(session, body.barber_id)
        service = active_service_or_error(session, body.service_id)
        wanted = check_bookable(session, config, body.barber_id, service, start, now)

        if busy(session, wanted, barber_id=body.barber_id):
            raise DomainError(409, "slot_taken", "that time is no longer available")
        if busy(session, wanted, customer_id=user.id):
            raise DomainError(409, "customer_overlap", "you already have a booking at that time")

        booking = Booking(
            customer_id=user.id,
            barber_id=body.barber_id,
            service_id=service.id,
            start_utc=wanted.start,
            end_utc=wanted.end,
            price_minor=service.price_minor,
            currency=service.currency,
        )
        session.add(booking)
        session.flush()
        if idempotency_key is not None:
            session.add(
                IdempotencyKey(
                    key=idempotency_key, customer_id=user.id, request_hash=request_hash, booking_id=booking.id
                )
            )
        return _view(session, booking, config)


@router.get("/bookings")
def list_bookings(
    status: str | None = Query(default=None, pattern="^(confirmed|cancelled)$"),
    barber_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    query = select(Booking)
    if user.role == "customer":
        query = query.where(Booking.customer_id == user.id)
    elif user.role == "barber":
        query = query.where(Booking.barber_id == user.id)
    elif barber_id is not None:
        query = query.where(Booking.barber_id == barber_id)
    if status is not None:
        query = query.where(Booking.status == status)

    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Booking.start_utc, Booking.id).limit(limit).offset(offset)).all()
    return page(total, [_view(session, b, config) for b in rows])


@router.get("/bookings/{booking_id}")
def get_booking(
    booking_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    return _view(session, _visible_or_404(session, booking_id, user), config)


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    now = datetime.now(UTC)
    with write_lock(session):
        booking = _visible_or_404(session, booking_id, user)
        if user.role == "barber":
            raise DomainError(403, "forbidden", "barbers cannot cancel bookings; ask the owner")
        if booking.status == "cancelled":
            raise DomainError(409, "already_cancelled", "that booking is already cancelled")
        if booking.start_utc <= now:
            raise DomainError(409, "already_started", "that booking has already started")
        if user.role == "customer" and booking.start_utc - now < timedelta(hours=config.cancel_cutoff_hours):
            raise DomainError(
                409,
                "late_cancellation",
                f"bookings can be cancelled up to {config.cancel_cutoff_hours} hours ahead",
            )
        booking.status = "cancelled"
        booking.cancelled_at = now
        booking.cancelled_by = user.id
        return _view(session, booking, config)
