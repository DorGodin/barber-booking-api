"""How each entity looks on the wire. One function per entity, used everywhere."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import Booking, Service, User


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
    }


def booking_view(booking: Booking, service_name: str, tz: ZoneInfo) -> dict:
    return {
        "id": booking.id,
        "customer_id": booking.customer_id,
        "guest_name": booking.guest_name,
        "barber_id": booking.barber_id,
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
    }


def page(total: int, content: list[dict]) -> dict:
    return {"total": total, "content": content}
