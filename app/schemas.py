from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

from app.scheduling import WEEKDAYS, parse_hhmm

USERNAME = r"^[a-z0-9._-]{3,64}$"


class LoginIn(BaseModel):
    username: str
    password: str


class CodeRequestIn(BaseModel):
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    # Checked and normalised by app.phones, which says what is wrong with it.
    phone: str = Field(max_length=20)


class CodeVerifyIn(BaseModel):
    phone: str = Field(max_length=20)
    code: str = Field(pattern=r"^\d{4}$")


class AccountIn(BaseModel):
    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    duration_minutes: int = Field(ge=15, le=240, multiple_of=15)
    price_minor: int = Field(ge=0, le=10_000_000)
    currency: str = Field(default="ILS", pattern=r"^[A-Z]{3}$")
    requires_approval: bool = False
    any_time: bool = False


class ServicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    duration_minutes: int | None = Field(default=None, ge=15, le=240, multiple_of=15)
    price_minor: int | None = Field(default=None, ge=0, le=10_000_000)
    active: bool | None = None
    requires_approval: bool | None = None
    any_time: bool | None = None


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


class ReviewIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ReviewTextIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class CourseIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    starts_on: date | None = None
    price_minor: int | None = Field(default=None, ge=0, le=10_000_000)


class CoursePatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    starts_on: date | None = None
    price_minor: int | None = Field(default=None, ge=0, le=10_000_000)
    active: bool | None = None


class ImageIn(BaseModel):
    """A picture as base64 text: the page reads the file it was given and sends it
    in a JSON body, so no multipart machinery is needed."""

    data: str = Field(min_length=1, max_length=4_200_000)


class ApprovalRulesIn(HoursIn):
    """When a customer's booking waits for its barber: on or off for the shop, and
    per day the hours from and up to (not including), null meaning never that day."""

    enabled: bool


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
