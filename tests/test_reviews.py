"""A customer rates a booking once it is over: stars at a tap, words after if they like."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Booking
from tests.conftest import HAIRCUT, a_second_barber, at, book, local_day


def past_booking(client, me, barber, haircut, hours_ago=3, status="confirmed", approval=None) -> str:
    customer_id = client.get("/me", headers=me).json()["id"]
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=hours_ago)
    with client.app.state.sessionmaker() as session:
        booking = Booking(
            customer_id=customer_id,
            barber_id=barber,
            service_id=haircut,
            start_utc=start,
            end_utc=start + timedelta(minutes=30),
            price_minor=8000,
            currency="ILS",
            status=status,
            approval=approval,
            decide_by=start if approval else None,
        )
        session.add(booking)
        session.commit()
        return booking.id


def review(client, headers, booking_id, **body):
    return client.post(f"/bookings/{booking_id}/review", headers=headers, json={"stars": 5, **body})


def test_a_booking_that_is_over_can_be_reviewed_with_stars_alone(client, customer, barber, services):
    booking = past_booking(client, customer, barber, services[HAIRCUT]["id"])
    before = client.get(f"/bookings/{booking}", headers=customer).json()
    assert (before["reviewable"], before["review"]) == (True, None)

    made = review(client, customer, booking, stars=4)

    assert made.status_code == 201
    assert (made.json()["review"], made.json()["reviewable"]) == ({"stars": 4, "text": None}, False)


def test_the_words_may_come_with_the_stars(client, customer, barber, services):
    booking = past_booking(client, customer, barber, services[HAIRCUT]["id"])

    made = review(client, customer, booking, stars=5, text="  אלוף העולם  ").json()

    assert made["review"] == {"stars": 5, "text": "אלוף העולם"}


@pytest.mark.parametrize(
    "body", [{"stars": 0}, {"stars": 6}, {"stars": "five"}, {"stars": 5, "text": "x" * 501}, {}]
)
def test_stars_outside_one_to_five_and_too_long_words_are_refused(client, customer, barber, services, body):
    booking = past_booking(client, customer, barber, services[HAIRCUT]["id"])

    assert client.post(f"/bookings/{booking}/review", headers=customer, json=body).status_code == 422


def test_a_booking_not_over_yet_cannot_be_reviewed(client, customer, barber, services):
    future = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    refused = review(client, customer, future["id"])

    assert refused.status_code == 409 and refused.json()["code"] == "not_over_yet"
    assert future["reviewable"] is False


def test_a_booking_that_did_not_stand_cannot_be_reviewed(client, customer, barber, services):
    haircut = services[HAIRCUT]["id"]
    cancelled = past_booking(client, customer, barber, haircut, status="cancelled")
    declined = past_booking(
        client, customer, barber, haircut, hours_ago=6, status="cancelled", approval="declined"
    )

    for booking in (cancelled, declined):
        refused = review(client, customer, booking)
        assert refused.status_code == 409 and refused.json()["code"] == "not_reviewable"


def test_a_second_review_is_refused_and_the_first_stands(client, customer, barber, services):
    booking = past_booking(client, customer, barber, services[HAIRCUT]["id"])
    review(client, customer, booking, stars=3)

    again = review(client, customer, booking, stars=5)

    assert again.status_code == 409 and again.json()["code"] == "already_reviewed"
    assert client.get(f"/bookings/{booking}", headers=customer).json()["review"]["stars"] == 3


def test_only_the_customers_own_booking_and_only_a_customer(client, new_customer, owner, barber, services):
    mine, other = new_customer(), new_customer()
    booking = past_booking(client, mine, barber, services[HAIRCUT]["id"])

    assert review(client, other, booking).status_code == 404
    assert review(client, owner, booking).status_code == 403
    assert client.post(f"/bookings/{booking}/review", json={"stars": 5}).status_code == 401


def test_the_words_are_added_changed_and_cleared_and_the_stars_stay(client, customer, barber, services):
    booking = past_booking(client, customer, barber, services[HAIRCUT]["id"])
    early = client.patch(f"/bookings/{booking}/review", headers=customer, json={"text": "x"})
    assert early.status_code == 409 and early.json()["code"] == "no_review_yet"
    review(client, customer, booking, stars=4)

    added = client.patch(f"/bookings/{booking}/review", headers=customer, json={"text": "מעולה"}).json()
    changed = client.patch(
        f"/bookings/{booking}/review", headers=customer, json={"text": "מעולה מאוד"}
    ).json()
    cleared = client.patch(f"/bookings/{booking}/review", headers=customer, json={"text": "  "}).json()

    assert [r["review"] for r in (added, changed, cleared)] == [
        {"stars": 4, "text": "מעולה"},
        {"stars": 4, "text": "מעולה מאוד"},
        {"stars": 4, "text": None},
    ]


def test_a_guest_booking_is_never_reviewable(client, owner, barber, services):
    owner_view = client.post(
        "/bookings/guest",
        headers=owner,
        json={
            "barber_id": barber,
            "service_id": services[HAIRCUT]["id"],
            "start": at(local_day(3), "10:00"),
            "guest_name": "Yossi",
        },
    ).json()

    assert owner_view["reviewable"] is False and owner_view["review"] is None


def test_the_barber_and_the_owner_see_the_review_in_the_diary(client, owner, customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    booking = past_booking(client, customer, barber_id, services[HAIRCUT]["id"])
    review(client, customer, booking, stars=5, text="אלוף")

    [seen] = client.get("/bookings", headers=barber_headers).json()["content"]
    as_owner = client.get(f"/bookings/{booking}", headers=owner).json()

    assert seen["review"] == as_owner["review"] == {"stars": 5, "text": "אלוף"}
