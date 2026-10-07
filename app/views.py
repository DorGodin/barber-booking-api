"""How each entity looks on the wire. One function per entity, used everywhere."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.booking_rules import approval_state
from app.models import Booking, Service, User, now_utc


def iso_utc(instant: datetime | None) -> str | None:
    return None if instant is None else instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def user_view(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role, "display_name": user.display_name}


def barber_view(user: User) -> dict:
    return {"id": user.id, "display_name": user.display_name, "active": user.active}


def service_view(service: Service) -> dict:
    return {
        "id": service.id,
        "name": service.name,
        "duration_minutes": service.duration_minutes,
        "price_minor": service.price_minor,
        "currency": service.currency,
        "active": service.active,
        "requires_approval": service.requires_approval,
        "any_time": service.any_time,
    }


def course_view(course, whatsapp: str | None) -> dict:
    # The button on the card opens the shop's WhatsApp with the course already
    # named, so the customer's first message says what they are asking about.
    link = None
    if whatsapp:
        link = f"{whatsapp}?text={quote(f'שלום, אני מעוניין בקורס: {course.title}')}"
    return {
        "id": course.id,
        "title": course.title,
        "subtitle": course.subtitle,
        "starts_on": course.starts_on,
        "price_minor": course.price_minor,
        "currency": "ILS",
        "image_url": f"/media/{course.image}" if course.image else None,
        "active": course.active,
        "whatsapp_url": link,
    }


def cancelled_by_label(booking: Booking) -> str | None:
    if booking.cancelled_by is None:
        return None
    return "customer" if booking.cancelled_by == booking.customer_id else "staff"


def booking_view(
    booking: Booking,
    service_name: str,
    barber_name: str,
    tz: ZoneInfo,
    now: datetime | None = None,
    review=None,
) -> dict:
    now = now or now_utc()
    return {
        "id": booking.id,
        "customer_id": booking.customer_id,
        "guest_name": booking.guest_name,
        "barber_id": booking.barber_id,
        # In the booking itself: a customer's list of barbers no longer has one
        # who left, and their bookings with them must still say who.
        "barber_name": barber_name,
        "service_id": booking.service_id,
        "service_name": service_name,
        "start": iso_utc(booking.start_utc),
        "end": iso_utc(booking.end_utc),
        # The same instant on the shop's clock, with its offset. Across a DST
        # change the offset is what tells 01:30 from 01:30.
        "start_local": booking.start_utc.astimezone(tz).isoformat(),
        "status": booking.status,
        "price_minor": booking.price_minor,
        "currency": booking.currency,
        "created_at": iso_utc(booking.created_at),
        "cancelled_at": iso_utc(booking.cancelled_at),
        # Who ended it - the customer themselves, or the shop - so a customer
        # can be told a booking was taken from them, and not only one they
        # cancelled.
        "cancelled_by": cancelled_by_label(booking),
        # None: no one's yes was needed. pending: waiting for the barber until
        # decide_by, then it stands. approved, or declined - which cancels it.
        # What the customer said about it, once it was over - and whether they may
        # still be asked: it is over, it stood, and nothing was said yet.
        "review": None if review is None else {"stars": review.stars, "text": review.text},
        "reviewable": review is None
        and booking.customer_id is not None
        and booking.status == "confirmed"
        and booking.end_utc <= now
        and approval_state(booking, now) != "declined",
        "approval": approval_state(booking, now),
        "decide_by": iso_utc(booking.decide_by) if approval_state(booking, now) == "pending" else None,
        # The same instant on the shop's clock, for the page to write as it is.
        "decide_by_local": (
            booking.decide_by.astimezone(tz).isoformat()
            if approval_state(booking, now) == "pending" and booking.decide_by is not None
            else None
        ),
    }


def page(total: int, content: list[dict]) -> dict:
    return {"total": total, "content": content}
