"""A customer who has cancelled or moved three times in 90 days has every booking wait for the
barber, at any hour, with no silence-is-a-yes - and is never told."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.booking_rules import approval_state
from app.models import Booking, BookingMove
from tests.conftest import HAIRCUT, TRIM, a_second_barber, at, book, local_day, move


def cancel_times(client, me, barber, service, times):
    for hhmm in times:
        made = book(client, me, barber, service, at(local_day(4), hhmm)).json()
        assert client.post(f"/bookings/{made['id']}/cancel", headers=me).status_code == 200


def move_times(client, me, barber, service, count):
    made = book(client, me, barber, service, at(local_day(4), "09:00")).json()
    for n in range(count):
        assert move(client, me, made["id"], at(local_day(5 + n), "09:00")).status_code == 200
    return made


def a_booking_at_ten(client, me, barber, service):
    return book(client, me, barber, service, at(local_day(9), "10:00")).json()


def test_three_cancellations_flag_the_customer_and_the_next_booking_waits_at_any_hour(
    client, new_customer, barber, services
):
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber, service, ["10:00", "11:00", "12:00"])

    made = a_booking_at_ten(client, me, barber, service)

    assert (made["status"], made["approval"], made["decide_by"]) == ("confirmed", "pending", None)


def test_two_cancellations_are_not_enough(client, new_customer, barber, services):
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber, service, ["10:00", "11:00"])

    assert a_booking_at_ten(client, me, barber, service)["approval"] is None


def test_three_moves_flag_the_customer(client, new_customer, barber, services):
    me, service = new_customer(), services[HAIRCUT]["id"]
    move_times(client, me, barber, service, 3)

    assert a_booking_at_ten(client, me, barber, service)["approval"] == "pending"


def test_two_moves_are_not_enough(client, new_customer, barber, services):
    me, service = new_customer(), services[HAIRCUT]["id"]
    move_times(client, me, barber, service, 2)

    assert a_booking_at_ten(client, me, barber, service)["approval"] is None


def test_a_flagged_customer_is_never_approved_by_silence(client, new_customer, barber, services):
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber, service, ["10:00", "11:00", "12:00"])
    made = a_booking_at_ten(client, me, barber, service)
    booking = Booking(status="confirmed", approval="pending", decide_by=None)

    assert approval_state(booking, datetime.now(UTC) + timedelta(days=365)) == "pending"
    assert client.get(f"/bookings/{made['id']}", headers=me).json()["approval"] == "pending"


def test_the_barber_still_answers_a_flagged_customers_request(client, owner, new_customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber_id, service, ["10:00", "11:00", "12:00"])
    made = a_booking_at_ten(client, me, barber_id, service)

    approved = client.post(f"/bookings/{made['id']}/approve", headers=barber_headers).json()

    assert approved["approval"] == "approved"


def test_a_flagged_customers_move_waits_again_whatever_the_hour(client, new_customer, barber, services):
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber, service, ["10:00", "11:00", "12:00"])
    made = book(client, me, barber, service, at(local_day(9), "10:00")).json()

    moved = move(client, me, made["id"], at(local_day(9), "11:00")).json()

    assert moved["approval"] == "pending" and moved["decide_by"] is None


def test_the_owner_moving_a_flagged_customers_booking_decides_it(
    client, owner, new_customer, barber, services
):
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber, service, ["10:00", "11:00", "12:00"])
    made = a_booking_at_ten(client, me, barber, service)

    moved = move(client, owner, made["id"], at(local_day(9), "11:00")).json()

    assert moved["approval"] is None


def test_other_customers_are_not_affected(client, new_customer, barber, services):
    flagged, other, service = new_customer(), new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, flagged, barber, service, ["10:00", "11:00", "12:00"])

    assert a_booking_at_ten(client, other, barber, service)["approval"] is None


def test_a_booking_the_shop_cancelled_or_declined_is_not_the_customers_cancellation(
    client, owner, new_customer, barber, services
):
    me, service = new_customer(), services[HAIRCUT]["id"]
    for hhmm in ("10:00", "11:00", "12:00"):
        made = book(client, me, barber, service, at(local_day(4), hhmm)).json()
        assert client.post(f"/bookings/{made['id']}/cancel", headers=owner).status_code == 200

    assert a_booking_at_ten(client, me, barber, service)["approval"] is None


def test_the_owners_moves_are_not_the_customers(client, owner, new_customer, barber, services):
    me, service = new_customer(), services[HAIRCUT]["id"]
    made = book(client, me, barber, service, at(local_day(4), "09:00")).json()
    for n in range(4):
        assert move(client, owner, made["id"], at(local_day(5 + n), "09:00")).status_code == 200

    assert a_booking_at_ten(client, me, barber, service)["approval"] is None


def test_what_is_older_than_ninety_days_no_longer_counts(client, new_customer, barber, services):
    me, service = new_customer(), services[TRIM]["id"]
    customer_id = client.get("/me", headers=me).json()["id"]
    long_ago = datetime.now(UTC) - timedelta(days=91)
    with client.app.state.sessionmaker() as session:
        old = Booking(
            customer_id=customer_id,
            barber_id=barber,
            service_id=service,
            start_utc=long_ago,
            end_utc=long_ago + timedelta(minutes=15),
            price_minor=4000,
            currency="ILS",
            status="cancelled",
            cancelled_at=long_ago,
            cancelled_by=customer_id,
        )
        session.add(old)
        session.flush()
        for _ in range(3):
            session.add(BookingMove(booking_id=old.id, customer_id=customer_id, moved_at=long_ago))
        for _ in range(3):
            session.add(
                Booking(
                    customer_id=customer_id,
                    barber_id=barber,
                    service_id=service,
                    start_utc=long_ago,
                    end_utc=long_ago + timedelta(minutes=15),
                    price_minor=4000,
                    currency="ILS",
                    status="cancelled",
                    cancelled_at=long_ago,
                    cancelled_by=customer_id,
                )
            )
        session.commit()

    assert a_booking_at_ten(client, me, barber, service)["approval"] is None


@pytest.mark.parametrize("hhmm", ["09:00", "10:00", "16:00", "20:00"])
def test_a_flagged_customer_waits_at_every_hour(client, new_customer, barber, services, hhmm):
    me, service = new_customer(), services[HAIRCUT]["id"]
    cancel_times(client, me, barber, service, ["10:00", "11:00", "12:00"])

    assert book(client, me, barber, service, at(local_day(9), hhmm)).json()["approval"] == "pending"
