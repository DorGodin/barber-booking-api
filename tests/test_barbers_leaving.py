"""A barber who leaves: made inactive, never deleted. Offered to no one, signed
in nowhere, and every booking they had kept for the owner to deal with."""

from __future__ import annotations

import secrets

from tests.conftest import ALL_WEEK, HAIRCUT, at, book, local_day, login, move


def a_barber_who_will_leave(client, owner) -> tuple[str, dict, str]:
    username = f"leaving-{secrets.token_hex(4)}"
    barber_id = client.post(
        "/barbers", headers=owner, json={"username": username, "password": "long-enough", "display_name": "L"}
    ).json()["id"]
    client.put(f"/barbers/{barber_id}/hours", headers=owner, json={"hours": ALL_WEEK})
    return barber_id, login(client, username, "long-enough"), username


def leave(client, owner, barber_id, active=False):
    return client.patch(f"/barbers/{barber_id}", headers=owner, json={"active": active})


def test_a_barber_who_left_is_offered_to_no_one_and_the_owner_still_sees_them(client, owner, customer):
    barber_id, _, _ = a_barber_who_will_leave(client, owner)

    left = leave(client, owner, barber_id)

    assert left.status_code == 200 and left.json()["active"] is False
    assert barber_id not in [b["id"] for b in client.get("/barbers", headers=customer).json()["content"]]
    seen_by_owner = {b["id"]: b for b in client.get("/barbers", headers=owner).json()["content"]}
    assert seen_by_owner[barber_id]["active"] is False


def test_nobody_books_a_barber_who_left(client, owner, customer, services):
    barber_id, _, _ = a_barber_who_will_leave(client, owner)
    leave(client, owner, barber_id)
    day = local_day(6)
    haircut = services[HAIRCUT]["id"]

    listing = client.get(
        f"/barbers/{barber_id}/availability",
        headers=customer,
        params={"date": day.isoformat(), "service_id": haircut},
    )
    by_customer = book(client, customer, barber_id, haircut, at(day, "11:00"))
    by_owner = client.post(
        "/bookings/guest",
        headers=owner,
        json={"barber_id": barber_id, "service_id": haircut, "start": at(day, "11:00"), "guest_name": "משה"},
    )

    for resp in (listing, by_customer, by_owner):
        assert resp.status_code == 422 and resp.json()["code"] == "barber_inactive", resp.text


def test_their_bookings_stay_for_the_owner_to_cancel_and_cannot_be_moved(client, owner, customer, services):
    barber_id, _, _ = a_barber_who_will_leave(client, owner)
    day = local_day(6)
    booking = book(client, customer, barber_id, services[HAIRCUT]["id"], at(day, "11:00")).json()

    leave(client, owner, barber_id)

    kept = client.get(f"/bookings/{booking['id']}", headers=customer).json()
    assert kept["status"] == "confirmed", "leaving does not cancel anyone's booking by itself"
    in_the_diary = client.get("/bookings", headers=owner, params={"barber_id": barber_id}).json()["content"]
    assert [b["id"] for b in in_the_diary] == [booking["id"]]
    moved = move(client, owner, booking["id"], at(day, "15:00"))
    assert moved.status_code == 422 and moved.json()["code"] == "barber_inactive"
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=owner).json()["status"] == "cancelled"


def test_a_barber_who_left_is_signed_out_and_cannot_sign_in(client, owner):
    barber_id, signed_in, username = a_barber_who_will_leave(client, owner)

    leave(client, owner, barber_id)

    assert client.get("/me", headers=signed_in).status_code == 401
    refused = client.post("/auth/token", json={"username": username, "password": "long-enough"})
    assert refused.status_code == 403 and refused.json()["code"] == "account_inactive"
    # Without the password nothing is confirmed: the same answer as for anyone.
    guessed = client.post("/auth/token", json={"username": username, "password": "not-the-password"})
    assert guessed.status_code == 401 and guessed.json()["code"] == "bad_credentials"


def test_a_barber_who_comes_back_is_bookable_and_signs_in_again(client, owner, customer, services):
    barber_id, _, username = a_barber_who_will_leave(client, owner)
    leave(client, owner, barber_id)

    back = leave(client, owner, barber_id, active=True)

    assert back.status_code == 200 and back.json()["active"] is True
    assert (
        book(client, customer, barber_id, services[HAIRCUT]["id"], at(local_day(6), "11:00")).status_code
        == 201
    )
    assert (
        client.post("/auth/token", json={"username": username, "password": "long-enough"}).status_code == 200
    )


def test_only_the_owner_decides_who_has_left(client, owner, customer):
    barber_id, as_barber, _ = a_barber_who_will_leave(client, owner)

    assert leave(client, customer, barber_id).status_code == 403
    assert leave(client, as_barber, barber_id).status_code == 403
    assert client.patch("/barbers/usr_nobody", headers=owner, json={"active": False}).status_code == 404
    assert client.patch(f"/barbers/{barber_id}", headers=owner, json={}).status_code == 422
