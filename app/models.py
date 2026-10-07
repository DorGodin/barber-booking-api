from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id(prefix: str) -> str:
    """Opaque and unguessable. A sequential id lets anyone walk every booking."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now_utc() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Stored as naive UTC, returned as aware UTC. SQLite has no time zones, so
    the conversion happens here, once, and nowhere else."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("refusing to store a naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("phone", name="uq_users_phone"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("usr"))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(80))
    # The person's mobile, 0501234567: who they are when they sign in with a
    # code. Unique - two people may share a name, never a phone.
    phone: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    # A barber who left: kept, with every booking they had, but offered to no
    # one and signed in nowhere. server_default so the rows that exist when the
    # column arrives are active too.
    active: Mapped[bool] = mapped_column(default=True, server_default=true())


class OtpCode(Base):
    """A sign-in code sent by SMS. Only its HMAC is kept - like a password, the
    code itself is never stored. The full name waits here for the first sign-in,
    which opens the account."""

    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(10), index=True)
    full_name: Mapped[str] = mapped_column(String(80))
    code_hash: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Set when the code signed someone in, or when a newer code replaced it.
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RevokedToken(Base):
    """A sign-in ended by signing out. A signed token stays valid until it
    expires - nothing in it can be changed - so the server keeps the ones that
    were ended, until they would have expired anyway."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class Signup(Base):
    """One account created, and from where - to limit how many one address makes."""

    __tablename__ = "signups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True, default=now_utc)


class LoginFailure(Base):
    """One failed sign-in. Kept in the database, not in memory: the server runs
    several workers, and a count in each one's memory would let an attacker
    spread guesses across them."""

    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True, default=now_utc)


class BarberHours(Base):
    """The weekly schedule, local wall-clock times: {"sun": ["09:00", "19:00"], "sat": null}."""

    __tablename__ = "barber_hours"

    barber_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    hours_json: Mapped[str] = mapped_column(Text)

    @property
    def hours(self) -> dict:
        return json.loads(self.hours_json)


class TimeOff(Base):
    __tablename__ = "time_off"
    __table_args__ = (UniqueConstraint("barber_id", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barber_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    day: Mapped[str] = mapped_column(String(10))


class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("svc"))
    name: Mapped[str] = mapped_column(String(80), unique=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    # Integer minor units, never a float: 80.00 ILS is 8000. A float total of
    # three haircuts is 239.99999999999997.
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="ILS")
    active: Mapped[bool] = mapped_column(default=True)
    # A booking of this service always waits for its barber's answer - any day, any
    # hour, and silence is never a yes (an emergency haircut, say).
    requires_approval: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Offered on every day and at every hour, past the barber's hours and days off - only
    # their bookings take times from it. The calendar opens whole for such a service.
    any_time: Mapped[bool] = mapped_column(default=False, server_default=false())


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_barber_start", "barber_id", "start_utc"),
        Index("ix_bookings_customer_start", "customer_id", "start_utc"),
        # A customer with an account, or a guest the owner booked by name - one
        # or the other, never both and never neither.
        CheckConstraint(
            "(customer_id IS NULL) != (guest_name IS NULL)", name="ck_bookings_customer_or_guest"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bkg"))
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Booked by the owner for someone who phoned or walked in, with no account.
    guest_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    barber_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    start_utc: Mapped[datetime] = mapped_column(UTCDateTime)
    end_utc: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    # The price when it was booked. A later price change does not reach back
    # into bookings already made.
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # A booking in the hours that need the barber's yes: "pending" until they
    # answer or decide_by passes, then "approved" or "declined". None: nothing
    # to approve. "pending" past decide_by reads as approved (booking_rules); with
    # no decide_by it waits for the barber however long it takes.
    approval: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decide_by: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # A booking made for someone else - a child, a friend - in one go with the customer's own:
    # who it is for, and the group the bookings were made together in. Each is its own
    # booking afterwards: moved, cancelled and answered one by one.
    for_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # When the customer was reminded of it; None until they are. A move clears it.
    reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BookingMove(Base):
    """One time a customer moved a booking: kept to count them. The owner's moves
    are not kept - only the customer's own count against them."""

    __tablename__ = "booking_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    moved_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True, default=now_utc)


class PushSubscription(Base):
    """A browser that asked to be told about news: the address its push service gave it.
    No keys - nothing is sent in the message, so nothing is encrypted."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)


class PushNotice(Base):
    """What one browser is to be told the next time the push service wakes it. The push carries no
    words, so the service worker asks for them - with its own address, which only that browser has -
    and is given them once."""

    __tablename__ = "push_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("push_subscriptions.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Review(Base):
    """What a customer says about a booking once it is over: stars, and words if
    they add any. One per booking, kept even if the barber later leaves."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_reviews_booking"),
        CheckConstraint("stars BETWEEN 1 AND 5", name="ck_reviews_stars"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rev"))
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    barber_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    stars: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)


class Course(Base):
    """A course the shop gives, shown to customers as a card whose button opens
    WhatsApp. Withdrawn ones are kept, never deleted - like a service."""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("crs"))
    title: Mapped[str] = mapped_column(String(80))
    # One short line under the title: "8 מפגשים".
    subtitle: Mapped[str] = mapped_column(String(120), default="")
    starts_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A file name in the media folder, written by the server when the owner
    # uploads a picture - never a value a client chooses.
    image: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)


class ShopSetting(Base):
    """A setting the owner changes from the page, kept as JSON under a name.
    No row: the setting is what the server's own settings say."""

    __tablename__ = "shop_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)


class IdempotencyKey(Base):
    """A double tap on "Book" must not book twice. The client sends the same
    Idempotency-Key with both requests; the second gets the first's booking."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"))
