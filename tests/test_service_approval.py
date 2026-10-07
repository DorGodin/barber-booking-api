"""A service whose every booking waits for the barber - any day, any hour, and no yes by silence."""

from __future__ import annotations

import pytest

from tests.conftest import HAIRCUT, at, book, local_day, move


@pytest.fixture
def emergency(client, owner):
    made = client.post(
        "/services",
        headers=owner,
        json={
            "name": "חירום בדיקה",
            "duration_minutes": 30,
            "price_minor": 20000,
            "requires_approval": True,
        },
    )
    assert made.status_code == 201
    return made.json()


def test_a_service_says_whether_it_needs_the_barber_and_the_menu_does_not_by_default(
    client, owner, services, emergency
):
    assert emergency["requires_approval"] is True
    assert services[HAIRCUT]["requires_approval"] is False
    plain = client.post(
        "/services", headers=owner, json={"name": "רגיל בדיקה", "duration_minutes": 30, "price_minor": 100}
    ).json()
    assert plain["requires_approval"] is False


def test_the_owner_turns_it_on_and_off_and_nobody_else(client, owner, customer, services):
    service = services[HAIRCUT]["id"]

    assert (
        client.patch(f"/services/{service}", headers=customer, json={"requires_approval": True}).status_code
        == 403
    )
    on = client.patch(f"/services/{service}", headers=owner, json={"requires_approval": True}).json()
    off = client.patch(f"/services/{service}", headers=owner, json={"requires_approval": False}).json()

    assert (on["requires_approval"], off["requires_approval"]) == (True, False)


@pytest.mark.parametrize("hhmm", ["09:00", "10:00", "16:00", "20:00"])
def test_a_booking_of_it_waits_at_every_hour_with_no_time_limit(client, customer, barber, emergency, hhmm):
    made = book(client, customer, barber, emergency["id"], at(local_day(9), hhmm)).json()

    assert (made["status"], made["approval"], made["decide_by"]) == ("confirmed", "pending", None)


def test_the_same_hour_with_an_ordinary_service_does_not_wait(client, customer, barber, services):
    assert (
        book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(9), "10:00")).json()["approval"]
        is None
    )


def test_the_barber_answers_it_like_any_request(client, owner, customer, barber, emergency):
    made = book(client, customer, barber, emergency["id"], at(local_day(9), "10:00")).json()

    assert client.post(f"/bookings/{made['id']}/approve", headers=owner).json()["approval"] == "approved"


def test_moving_it_waits_again_and_the_owner_moving_it_decides(client, owner, customer, barber, emergency):
    made = book(client, customer, barber, emergency["id"], at(local_day(9), "10:00")).json()
    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    by_customer = move(client, customer, made["id"], at(local_day(9), "11:00")).json()
    by_owner = move(client, owner, made["id"], at(local_day(9), "12:00")).json()

    assert (by_customer["approval"], by_customer["decide_by"]) == ("pending", None)
    assert by_owner["approval"] is None


def test_the_owner_booking_it_for_a_guest_needs_no_yes(client, owner, barber, emergency):
    made = client.post(
        "/bookings/guest",
        headers=owner,
        json={
            "barber_id": barber,
            "service_id": emergency["id"],
            "start": at(local_day(9), "10:00"),
            "guest_name": "Yossi",
        },
    ).json()

    assert made["approval"] is None
