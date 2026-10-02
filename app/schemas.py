from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

from app.scheduling import WEEKDAYS, parse_hhmm

USERNAME = r"^[a-z0-9._-]{3,64}$"


class LoginIn(BaseModel):
    username: str
    password: str


class AccountIn(BaseModel):
    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    duration_minutes: int = Field(ge=15, le=240, multiple_of=15)
    price_minor: int = Field(ge=0, le=10_000_000)
    currency: str = Field(default="ILS", pattern=r"^[A-Z]{3}$")


class ServicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    duration_minutes: int | None = Field(default=None, ge=15, le=240, multiple_of=15)
    price_minor: int | None = Field(default=None, ge=0, le=10_000_000)
    active: bool | None = None


class BarberPatch(BaseModel):
    active: bool


class HoursIn(BaseModel):
    """All seven days, every time. A missing day is ambiguous - closed, or forgotten?"""

    hours: dict[str, list[str] | None]

    @field_validator("hours")
    @classmethod
    def _week(cls, hours: dict) -> dict:
        if set(hours) != set(WEEKDAYS):
            raise ValueError(f"give every day exactly once: {', '.join(WEEKDAYS)}; null means closed")
        for day, span in hours.items():
            if span is None:
                continue
            if len(span) != 2:
                raise ValueError(f"{day}: expected [open, close]")
            opening, closing = parse_hhmm(span[0]), parse_hhmm(span[1])
            if opening >= closing:
                raise ValueError(f"{day}: opens at {span[0]} and closes at {span[1]}")
        return hours


class TimeOffIn(BaseModel):
    date: date


class BookingMoveIn(BaseModel):
    start: AwareDatetime


class BookingIn(BaseModel):
    barber_id: str
    service_id: str
    # AwareDatetime: a start with no offset is refused. "10:00" means a
    # different instant in every time zone, and guessing the shop's is how a
    # booking made abroad lands an hour off.
    start: AwareDatetime


class GuestBookingIn(BookingIn):
    """The owner books someone with no account - who phoned, or walked in."""

    guest_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
