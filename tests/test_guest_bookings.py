"""The owner books, by name, someone with no account - who phoned or walked in."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.conftest import HAIRCUT, TRIM, a_second_barber, at, book, local_day, login, move, slots


def guest(client, headers, barber_id, service_id, start, name="משה - בטלפון"):
    return client.post(
        "/bookings/guest",
        headers=headers,
        json={"barber_id": barber_id, "service_id": service_id, "start": start, "guest_name": name},
    )


def test_the_owner_books_a_guest_and_the_time_is_gone_for_everyone(client, owner, customer, barber, services):
    day = local_day(6)

    booked = guest(client, owner, barber, services[HAIRCUT]["id"], at(day, "11:00"))

    assert booked.status_code == 201, booked.text
    body = booked.json()
    assert body["guest_name"] == "משה - בטלפון" and body["customer_id"] is None
    assert body["price_minor"] == services[HAIRCUT]["price_minor"]
    assert at(day, "11:00") not in slots(client, customer, barber, services[HAIRCUT]["id"], day)
    taken = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00"))
    assert taken.status_code == 409 and taken.json()["code"] == "slot_taken"


def test_a_guest_booking_cannot_take_a_time_a_customer_has(client, owner, customer, barber, services):
    day = local_day(6)
    book(client, customer, barber, services[HAIRCUT]["id"], at(day, "12:00"))

    refused = guest(client, owner, barber, services[HAIRCUT]["id"], at(day, "12:15"))

    assert refused.status_code == 409 and refused.json()["code"] == "slot_taken"


def test_a_guest_booking_obeys_the_same_rules_as_any_booking(client, owner, barber, services):
    day = local_day(6)

    assert (
        guest(client, owner, barber, services[TRIM]["id"], at(day, "11:07")).json()["code"] == "not_aligned"
    )
    assert (
        guest(client, owner, barber, services[TRIM]["id"], at(local_day(-1), "11:00")).json()["code"]
        == "in_past"
    )
    assert guest(client, owner, "usr_nobody", services[TRIM]["id"], at(day, "11:00")).status_code == 404


@pytest.mark.parametrize("name", ["", "   ", "א" * 81])
def test_a_guest_needs_a_name(client, owner, barber, services, name):
    resp = guest(client, owner, barber, services[TRIM]["id"], at(local_day(6), "11:00"), name=name)

    assert resp.status_code == 422


def test_the_name_is_kept_without_the_spaces_around_it(client, owner, barber, services):
    resp = guest(client, owner, barber, services[TRIM]["id"], at(local_day(6), "11:00"), name="  דנה  ")

    assert resp.json()["guest_name"] == "דנה"


def test_only_the_owner_books_guests(client, customer, passwords, barber, services):
    start = at(local_day(6), "11:00")
    as_barber = login(client, "barber", passwords["barber"])

    assert guest(client, customer, barber, services[TRIM]["id"], start).status_code == 403
    assert guest(client, as_barber, barber, services[TRIM]["id"], start).status_code == 403
    assert guest(client, {}, barber, services[TRIM]["id"], start).status_code == 401


def test_the_booking_limit_is_for_customers_not_for_the_owner(client, owner, barber, services):
    day = local_day(6)

    codes = [
        guest(client, owner, barber, services[TRIM]["id"], at(day, f"1{n}:00")).status_code for n in range(4)
    ]

    assert codes == [201] * 4


def test_a_customer_neither_sees_nor_cancels_a_guest_booking(client, owner, customer, barber, services):
    booked = guest(client, owner, barber, services[HAIRCUT]["id"], at(local_day(6), "11:00")).json()

    assert client.get(f"/bookings/{booked['id']}", headers=customer).status_code == 404
    assert client.post(f"/bookings/{booked['id']}/cancel", headers=customer).status_code == 404
    assert booked["id"] not in [b["id"] for b in client.get("/bookings", headers=customer).json()["content"]]


def test_the_barber_sees_the_guest_by_name(client, owner, services):
    barber_id, barber = a_second_barber(client, owner)
    guest(client, owner, barber_id, services[HAIRCUT]["id"], at(local_day(6), "11:00"), name="יוסי מהכניסה")

    [mine] = client.get("/bookings", headers=barber).json()["content"]

    assert mine["guest_name"] == "יוסי מהכניסה"


def test_the_owner_moves_and_cancels_a_guest_booking(client, owner, customer, barber, services):
    other, _ = a_second_barber(client, owner)
    day = local_day(6)
    booked = guest(client, owner, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()
    # Someone else, at another barber, at the time the guest moves to. A guest
    # has no other bookings to clash with - this must not count as theirs.
    book(client, customer, other, services[HAIRCUT]["id"], at(day, "15:00"))

    moved = move(client, owner, booked["id"], at(day, "15:00"))
    cancelled = client.post(f"/bookings/{booked['id']}/cancel", headers=owner)

    assert moved.status_code == 200, moved.text
    assert moved.json()["start"] == at(day, "15:00") and moved.json()["guest_name"] == booked["guest_name"]
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


@pytest.mark.parametrize(
    ("customer_id", "guest_name"), [(None, None), ("both", "and a name")], ids=["neither", "both"]
)
def test_the_database_holds_a_booking_to_exactly_one_customer_or_guest(
    client, owner, barber, services, tmp_path: Path, customer_id, guest_name
):
    booked = guest(client, owner, barber, services[TRIM]["id"], at(local_day(6), "11:00")).json()
    if customer_id == "both":
        customer_id = client.get("/me", headers=owner).json()["id"]

    with sqlite3.connect(tmp_path / "test.db") as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE bookings SET customer_id = ?, guest_name = ? WHERE id = ?",
            (customer_id, guest_name, booked["id"]),
        )
