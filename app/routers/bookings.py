from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.booking_rules import (
    active_service_or_error,
    approval_state,
    bookable_barber_or_error,
    busy,
    check_bookable,
    clashes,
    decide_by,
    is_flagged,
    needs_approval,
    visible_booking_or_404,
)
from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, require, settings
from app.errors import DomainError
from app.models import Booking, BookingMove, IdempotencyKey, Review, Service, User
from app.scheduling import Interval
from app.schemas import BookingIn, BookingMoveIn, GuestBookingIn, ReviewIn, ReviewTextIn
from app.views import booking_view, page

router = APIRouter(tags=["bookings"])


def _view(session: Session, booking: Booking, config: Settings) -> dict:
    return booking_view(
        booking,
        session.get(Service, booking.service_id).name,
        session.get(User, booking.barber_id).display_name,
        config.shop_tz,
        review=session.scalar(select(Review).where(Review.booking_id == booking.id)),
    )


def _refuse_clashes(
    session: Session, wanted: Interval, barber_id: str, customer_id: str | None, excluding: str | None = None
) -> None:
    """The barber's chair is free, and so is the customer - who cannot be in two
    chairs at once. A guest has no account to hold other bookings, so only the
    chair is checked; asked about "no customer", busy() would answer with every
    booking in the shop."""
    if clashes(wanted, busy(session, wanted, barber_id=barber_id, excluding=excluding)):
        raise DomainError(409, "slot_taken", "that time is no longer available")
    if customer_id is not None and clashes(
        wanted, busy(session, wanted, customer_id=customer_id, excluding=excluding)
    ):
        raise DomainError(409, "customer_overlap", "you already have a booking at that time")


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

        bookable_barber_or_error(session, body.barber_id)
        service = active_service_or_error(session, body.service_id)
        wanted = check_bookable(session, config, body.barber_id, service, start, now)

        # One customer may hold only so many times ahead, or one account - or
        # a script - could take every free time in the shop. Counted under the
        # lock, so two bookings sent at once cannot both pass it. Before the
        # slot checks: a customer at the limit is told that, not that a time
        # is taken.
        ahead = session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(Booking.customer_id == user.id, Booking.status == "confirmed", Booking.start_utc > now)
        )
        if ahead >= config.max_future_bookings:
            raise DomainError(
                409,
                "too_many_bookings",
                f"at most {config.max_future_bookings} bookings ahead; cancel one to book another",
                extra={"limit": config.max_future_bookings},
            )

        _refuse_clashes(session, wanted, body.barber_id, user.id)

        booking = Booking(
            customer_id=user.id,
            barber_id=body.barber_id,
            service_id=service.id,
            start_utc=wanted.start,
            end_utc=wanted.end,
            price_minor=service.price_minor,
            currency=service.currency,
        )
        # A customer who has cancelled or moved too often waits for the barber on
        # every booking, whatever the hour, and silence is never a yes. They are
        # not told why: it looks like any request.
        if service.requires_approval or is_flagged(session, config, user.id, now):
            booking.approval = "pending"
        elif needs_approval(session, config, wanted.start):
            booking.approval = "pending"
            booking.decide_by = decide_by(config, now, wanted.start)
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
    return _view(session, visible_booking_or_404(session, booking_id, user), config)


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    now = datetime.now(UTC)
    with write_lock(session):
        booking = visible_booking_or_404(session, booking_id, user)
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


def _waiting_booking(session: Session, booking_id: str, user: User, now: datetime) -> Booking:
    booking = visible_booking_or_404(session, booking_id, user)
    if booking.status == "cancelled" and booking.approval != "declined":
        raise DomainError(409, "already_cancelled", "that booking is cancelled")
    if approval_state(booking, now) is None:
        raise DomainError(409, "nothing_to_approve", "that booking does not wait for anyone's answer")
    return booking


@router.post("/bookings/{booking_id}/approve")
def approve_booking(
    booking_id: str,
    user: User = Depends(require("barber", "owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The barber says yes. The owner may too, for any barber; a barber only
    for their own - somebody else's is not found. Saying it again, or after the
    wait ran out and it stood by itself, changes nothing."""
    now = datetime.now(UTC)
    with write_lock(session):
        booking = _waiting_booking(session, booking_id, user, now)
        state = approval_state(booking, now)
        if state == "declined":
            raise DomainError(409, "already_declined", "that booking was declined")
        if state == "pending":
            booking.approval, booking.decided_by = "approved", user.id
        return _view(session, booking, config)


@router.post("/bookings/{booking_id}/decline")
def decline_booking(
    booking_id: str,
    user: User = Depends(require("barber", "owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The barber says no: the booking is cancelled and the time is free again.
    Only while it waits - once it stands, ending it is the owner's cancellation."""
    now = datetime.now(UTC)
    with write_lock(session):
        booking = _waiting_booking(session, booking_id, user, now)
        state = approval_state(booking, now)
        if state == "declined":
            return _view(session, booking, config)
        if state == "approved":
            raise DomainError(409, "already_approved", "that booking already stands")
        booking.approval, booking.decided_by = "declined", user.id
        booking.status, booking.cancelled_at, booking.cancelled_by = "cancelled", now, user.id
        return _view(session, booking, config)


def _own_finished_booking(session: Session, booking_id: str, user: User, now: datetime) -> Booking:
    booking = visible_booking_or_404(session, booking_id, user)
    if booking.status != "confirmed" or approval_state(booking, now) == "declined":
        raise DomainError(409, "not_reviewable", "only a booking that stood can be reviewed")
    if booking.end_utc > now:
        raise DomainError(409, "not_over_yet", "a booking can be reviewed once it is over")
    return booking


@router.post("/bookings/{booking_id}/review", status_code=201)
def review_booking(
    booking_id: str,
    body: ReviewIn,
    user: User = Depends(require("customer")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The customer's stars - and words, if they add any - for a booking that is over.
    One per booking: a second is refused, never replaces the first."""
    now = datetime.now(UTC)
    with write_lock(session):
        booking = _own_finished_booking(session, booking_id, user, now)
        if session.scalar(select(Review).where(Review.booking_id == booking.id)) is not None:
            raise DomainError(409, "already_reviewed", "that booking already has a review")
        session.add(
            Review(
                booking_id=booking.id,
                customer_id=user.id,
                barber_id=booking.barber_id,
                stars=body.stars,
                text=body.text or None,
            )
        )
        session.flush()
        return _view(session, booking, config)


@router.patch("/bookings/{booking_id}/review")
def add_words_to_review(
    booking_id: str,
    body: ReviewTextIn,
    user: User = Depends(require("customer")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The words that follow the stars: they may be added or changed; the stars stay."""
    now = datetime.now(UTC)
    with write_lock(session):
        booking = _own_finished_booking(session, booking_id, user, now)
        review = session.scalar(select(Review).where(Review.booking_id == booking.id))
        if review is None:
            raise DomainError(409, "no_review_yet", "give the stars first")
        review.text = body.text or None
        return _view(session, booking, config)


@router.post("/bookings/{booking_id}/move")
def move_booking(
    booking_id: str,
    body: BookingMoveIn,
    user: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The same booking at another time - same barber, service and price.

    One step, under the write lock: the old time is held until the new one is
    taken. Cancel-then-book would leave the customer with nothing whenever
    somebody else took the new time in between."""
    start = body.start.astimezone(UTC)
    now = datetime.now(UTC)
    with write_lock(session):
        booking = visible_booking_or_404(session, booking_id, user)
        if user.role == "barber":
            raise DomainError(403, "forbidden", "barbers cannot move bookings; ask the owner")
        if booking.status == "cancelled":
            raise DomainError(409, "already_cancelled", "that booking is cancelled")
        if booking.start_utc <= now:
            raise DomainError(409, "already_started", "that booking has already started")
        if user.role == "customer" and booking.start_utc - now < timedelta(hours=config.move_cutoff_hours):
            raise DomainError(
                409, "late_move", f"bookings can be moved up to {config.move_cutoff_hours} hours ahead"
            )
        if start == booking.start_utc:
            # A second tap on the same choice: already done.
            return _view(session, booking, config)

        bookable_barber_or_error(session, booking.barber_id)
        # The service as it is now may be off the menu; the booking keeps it.
        service = session.get(Service, booking.service_id)
        wanted = check_bookable(session, config, booking.barber_id, service, start, now)
        _refuse_clashes(session, wanted, booking.barber_id, booking.customer_id, excluding=booking.id)

        booking.start_utc, booking.end_utc = wanted.start, wanted.end
        # A customer's new time answers to the same rule as a new booking; the
        # owner moving it has decided it, whatever the hour. The customer's move is
        # counted - after asking whether they were already flagged.
        flagged = user.role == "customer" and (
            service.requires_approval or is_flagged(session, config, user.id, now)
        )
        if user.role == "customer":
            session.add(BookingMove(booking_id=booking.id, customer_id=user.id, moved_at=now))
        if flagged:
            booking.approval, booking.decide_by, booking.decided_by = "pending", None, None
        elif user.role == "customer" and needs_approval(session, config, wanted.start):
            booking.approval, booking.decide_by, booking.decided_by = (
                "pending",
                decide_by(config, now, wanted.start),
                None,
            )
        else:
            booking.approval, booking.decide_by, booking.decided_by = None, None, None
        return _view(session, booking, config)


@router.post("/bookings/guest", status_code=201)
def create_guest_booking(
    body: GuestBookingIn,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """The owner books, by name, someone who phoned or walked in. The same
    chair, hours and lock as every booking - a phone booking the site does not
    know about is how a shop double books - but no account, so no limit on
    bookings ahead: that limit is for the site's customers."""
    start = body.start.astimezone(UTC)
    now = datetime.now(UTC)
    with write_lock(session):
        bookable_barber_or_error(session, body.barber_id)
        service = active_service_or_error(session, body.service_id)
        wanted = check_bookable(session, config, body.barber_id, service, start, now)
        _refuse_clashes(session, wanted, body.barber_id, None)
        booking = Booking(
            guest_name=body.guest_name,
            barber_id=body.barber_id,
            service_id=service.id,
            start_utc=wanted.start,
            end_utc=wanted.end,
            price_minor=service.price_minor,
            currency=service.currency,
        )
        session.add(booking)
        session.flush()
        return _view(session, booking, config)
