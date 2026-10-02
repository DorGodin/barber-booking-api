"""Moving a booking to another time: the same booking, barber, service and price."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.conftest import HAIRCUT, TRIM, a_second_barber, at, book, local_day, move, slots


def quarter_after(delta: timedelta) -> str:
    """The first quarter hour at least `delta` from now."""
    t = datetime.now(UTC) + delta
    t = t.replace(second=0, microsecond=0) + timedelta(minutes=15 - t.minute % 15)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_customer_moves_a_booking_and_the_old_time_is_free_again(client, customer, barber, services):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()

    moved = move(client, customer, booking["id"], at(day, "14:00"))

    assert moved.status_code == 200, moved.text
    assert moved.json()["id"] == booking["id"]
    assert moved.json()["start"] == at(day, "14:00")
    assert moved.json()["status"] == "confirmed"
    free = slots(client, customer, barber, services[HAIRCUT]["id"], day)
    assert at(day, "11:00") in free
    assert at(day, "14:00") not in free
    assert client.get("/bookings", headers=customer).json()["total"] == 1


def test_a_move_keeps_the_price_it_was_booked_at(client, owner, customer, barber, services):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()
    client.patch(
        f"/services/{services[HAIRCUT]['id']}",
        headers=owner,
        json={"price_minor": services[HAIRCUT]["price_minor"] + 1000},
    )

    moved = move(client, customer, booking["id"], at(day, "14:00")).json()

    assert moved["price_minor"] == booking["price_minor"]


def test_a_move_to_a_taken_time_is_refused_and_the_booking_stays_where_it_was(
    client, customer, new_customer, barber, services
):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()
    book(client, new_customer(), barber, services[HAIRCUT]["id"], at(day, "14:00"))

    refused = move(client, customer, booking["id"], at(day, "14:00"))

    assert refused.status_code == 409 and refused.json()["code"] == "slot_taken"
    kept = client.get(f"/bookings/{booking['id']}", headers=customer).json()
    assert kept["start"] == at(day, "11:00") and kept["status"] == "confirmed"


def test_a_booking_can_move_by_a_quarter_hour_into_its_own_time(client, customer, barber, services):
    assert services[HAIRCUT]["duration_minutes"] > 15, "the move below must overlap the booking itself"
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()

    listed = client.get(
        f"/barbers/{barber}/availability",
        headers=customer,
        params={"date": day.isoformat(), "service_id": services[HAIRCUT]["id"], "moving": booking["id"]},
    ).json()["slots"]
    moved = move(client, customer, booking["id"], at(day, "11:15"))

    # The listing for a move offers what the move accepts - its own time
    # included - and a listing without `moving` still does not.
    assert at(day, "11:15") in [s["start"] for s in listed]
    assert at(day, "11:15") not in slots(client, customer, barber, services[HAIRCUT]["id"], day)
    assert moved.status_code == 200 and moved.json()["start"] == at(day, "11:15")


def test_a_customer_cannot_move_into_a_clash_with_their_own_booking_at_another_barber(
    client, owner, customer, barber, services
):
    other, _ = a_second_barber(client, owner)
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()
    book(client, customer, other, services[HAIRCUT]["id"], at(day, "14:00"))

    refused = move(client, customer, booking["id"], at(day, "14:00"))

    assert refused.status_code == 409 and refused.json()["code"] == "customer_overlap"


def test_inside_12_hours_only_the_owner_can_move(client, owner, customer, barber, services):
    booking = book(client, customer, barber, services[TRIM]["id"], quarter_after(timedelta(hours=2))).json()

    late = move(client, customer, booking["id"], quarter_after(timedelta(hours=40)))
    by_owner = move(client, owner, booking["id"], quarter_after(timedelta(hours=40)))

    assert late.status_code == 409 and late.json()["code"] == "late_move"
    assert by_owner.status_code == 200


def test_between_12_and_24_hours_a_customer_can_move_but_not_cancel(client, customer, barber, services):
    booking = book(client, customer, barber, services[TRIM]["id"], quarter_after(timedelta(hours=13))).json()

    cancel = client.post(f"/bookings/{booking['id']}/cancel", headers=customer)
    moved = move(client, customer, booking["id"], quarter_after(timedelta(hours=40)))

    assert cancel.status_code == 409 and cancel.json()["code"] == "late_cancellation"
    assert moved.status_code == 200, moved.text


def test_the_same_move_sent_twice_is_done_once(client, customer, barber, services):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()

    first = move(client, customer, booking["id"], at(day, "14:00"))
    second = move(client, customer, booking["id"], at(day, "14:00"))

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()


def test_a_customer_at_the_booking_limit_can_still_move(client, customer, barber, services):
    day = local_day(6)
    first = book(client, customer, barber, services[TRIM]["id"], at(day, "10:00")).json()
    assert book(client, customer, barber, services[TRIM]["id"], at(day, "12:00")).status_code == 201
    assert book(client, customer, barber, services[TRIM]["id"], at(day, "13:00")).status_code == 409

    # A move replaces a booking; it does not add one.
    assert move(client, customer, first["id"], at(day, "15:00")).status_code == 200


def test_a_move_obeys_the_same_rules_as_a_booking(client, customer, barber, services):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()

    off_the_quarter = move(client, customer, booking["id"], at(day, "11:07"))
    in_the_past = move(client, customer, booking["id"], quarter_after(timedelta(hours=-3)))

    assert off_the_quarter.status_code == 422 and off_the_quarter.json()["code"] == "not_aligned"
    assert in_the_past.status_code == 422 and in_the_past.json()["code"] == "in_past"


def test_a_cancelled_booking_cannot_be_moved(client, customer, barber, services):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()
    client.post(f"/bookings/{booking['id']}/cancel", headers=customer)

    refused = move(client, customer, booking["id"], at(day, "14:00"))

    assert refused.status_code == 409 and refused.json()["code"] == "already_cancelled"


def test_only_the_customer_and_the_owner_can_move_a_booking(client, owner, customer, new_customer, services):
    barber_id, barber = a_second_barber(client, owner)
    day = local_day(6)
    booking = book(client, customer, barber_id, services[HAIRCUT]["id"], at(day, "11:00")).json()
    stranger = new_customer()

    by_stranger = move(client, stranger, booking["id"], at(day, "14:00"))
    by_barber = move(client, barber, booking["id"], at(day, "14:00"))
    listing_for_a_stranger = client.get(
        f"/barbers/{barber_id}/availability",
        headers=stranger,
        params={"date": day.isoformat(), "service_id": services[HAIRCUT]["id"], "moving": booking["id"]},
    )

    # Somebody else's booking is not found, not forbidden - a 403 would confirm it exists.
    assert by_stranger.status_code == 404
    assert listing_for_a_stranger.status_code == 404
    assert by_barber.status_code == 403
