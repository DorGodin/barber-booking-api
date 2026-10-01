from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Booking
from tests.conftest import HAIRCUT, book, local_day
from tests.test_api import at


def test_two_bookings_ahead_are_allowed_and_a_third_is_refused(client, new_customer, barber, services):
    me, haircut = new_customer(), services[HAIRCUT]["id"]
    day = local_day(3)
    assert book(client, me, barber, haircut, at(day, "10:00")).status_code == 201
    assert book(client, me, barber, haircut, at(day, "11:00")).status_code == 201

    third = book(client, me, barber, haircut, at(day, "12:00"))

    assert third.status_code == 409
    assert third.json()["code"] == "too_many_bookings"
    assert third.json()["limit"] == 2


def test_the_limit_is_checked_before_whether_the_time_is_free(client, new_customer, barber, services):
    me, other, haircut = new_customer(), new_customer(), services[HAIRCUT]["id"]
    day = local_day(3)
    book(client, other, barber, haircut, at(day, "14:00"))
    for hhmm in ("10:00", "11:00"):
        book(client, me, barber, haircut, at(day, hhmm))

    taken = book(client, me, barber, haircut, at(day, "14:00"))

    assert (
        taken.json()["code"] == "too_many_bookings"
    ), "a customer at the limit is told that, not that a time is taken"


def test_cancelling_one_makes_room_for_another(client, new_customer, barber, services):
    me, haircut = new_customer(), services[HAIRCUT]["id"]
    day = local_day(3)
    first = book(client, me, barber, haircut, at(day, "10:00")).json()
    book(client, me, barber, haircut, at(day, "11:00"))

    client.post(f"/bookings/{first['id']}/cancel", headers=me)

    assert book(client, me, barber, haircut, at(day, "12:00")).status_code == 201


def test_a_booking_that_has_already_happened_does_not_count(client, new_customer, barber, services):
    me, haircut = new_customer(), services[HAIRCUT]["id"]
    customer_id = client.get("/me", headers=me).json()["id"]
    yesterday = datetime.now(UTC) - timedelta(days=1)
    with client.app.state.sessionmaker() as session:
        for hours in (0, 1):
            start = yesterday + timedelta(hours=hours)
            session.add(
                Booking(
                    customer_id=customer_id,
                    barber_id=barber,
                    service_id=haircut,
                    start_utc=start,
                    end_utc=start + timedelta(minutes=30),
                    price_minor=8000,
                    currency="ILS",
                )
            )
        session.commit()
    day = local_day(3)

    assert book(client, me, barber, haircut, at(day, "10:00")).status_code == 201
    assert book(client, me, barber, haircut, at(day, "11:00")).status_code == 201


def test_sending_the_second_booking_again_at_the_limit_returns_it_and_is_not_refused(
    client, new_customer, barber, services
):
    me, haircut = new_customer(), services[HAIRCUT]["id"]
    day = local_day(3)
    book(client, me, barber, haircut, at(day, "10:00"))
    second = book(client, me, barber, haircut, at(day, "11:00"), **{"Idempotency-Key": "second-booking"})

    again = book(client, me, barber, haircut, at(day, "11:00"), **{"Idempotency-Key": "second-booking"})

    assert again.status_code == 201
    assert again.json()["id"] == second.json()["id"]
    assert again.headers["Idempotent-Replayed"] == "true"


def test_the_seed_holds_no_customer_above_the_limit(client, owner):
    rows, offset = [], 0
    while True:
        page = client.get("/bookings", headers=owner, params={"limit": 100, "offset": offset}).json()
        rows += page["content"]
        offset += 100
        if offset >= page["total"]:
            break
    now = datetime.now(UTC)
    ahead: dict[str, int] = {}
    for b in rows:
        if b["status"] == "confirmed" and datetime.fromisoformat(b["start"]) > now:
            ahead[b["customer_id"]] = ahead.get(b["customer_id"], 0) + 1

    assert rows, "the seed made no bookings"
    assert max(ahead.values()) <= 2, "the seed broke the product's own rule"
