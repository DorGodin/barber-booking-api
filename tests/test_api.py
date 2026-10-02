from datetime import UTC, datetime

from tests.conftest import COMBO, HAIRCUT, TRIM, at, book, local_day, slots


def test_an_unknown_user_and_a_wrong_password_get_the_same_answer(client):
    unknown = client.post("/auth/token", json={"username": "nobody", "password": "x"})
    wrong = client.post("/auth/token", json={"username": "owner", "password": "x"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_a_booked_slot_leaves_the_availability_and_appears_in_my_bookings(client, customer, barber, services):
    haircut = services[HAIRCUT]["id"]
    day = local_day(3)
    first = slots(client, customer, barber, haircut, day)[0]

    created = book(client, customer, barber, haircut, first)

    assert created.status_code == 201, created.text
    assert first not in slots(client, customer, barber, haircut, day)
    mine = client.get("/bookings", headers=customer).json()
    assert [b["id"] for b in mine["content"]] == [created.json()["id"]]


def test_every_slot_the_listing_offers_can_actually_be_booked(
    client, customer, new_customer, barber, services
):
    service = services[COMBO]["id"]
    day = local_day(4)
    offered = slots(client, customer, barber, service, day)

    # A customer of its own for each: one customer may hold only two bookings ahead.
    for start in offered[::9]:
        if start in slots(client, customer, barber, service, day):
            assert book(client, new_customer(), barber, service, start).status_code == 201, start


def test_a_start_without_an_offset_is_refused(client, customer, barber, services):
    day = local_day(3)
    resp = book(client, customer, barber, services[HAIRCUT]["id"], f"{day}T10:00:00")

    assert resp.status_code == 422


def test_an_overlap_is_refused_and_back_to_back_is_not(client, customer, new_customer, barber, services):
    day = local_day(5)
    other = new_customer()
    assert book(client, customer, barber, services[HAIRCUT]["id"], at(day, "10:00")).status_code == 201

    overlapping = book(client, other, barber, services[TRIM]["id"], at(day, "10:15"))
    after = book(client, other, barber, services[TRIM]["id"], at(day, "10:30"))

    assert overlapping.status_code == 409 and overlapping.json()["code"] == "slot_taken"
    assert after.status_code == 201


def test_a_customer_cannot_be_in_two_chairs_at_once(client, owner, customer, barber, services):
    day = local_day(5)
    second = client.post(
        "/barbers",
        headers=owner,
        json={"username": "b-two", "password": "long-enough", "display_name": "Two"},
    ).json()["id"]
    client.put(
        f"/barbers/{second}/hours",
        headers=owner,
        json={"hours": dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), ["00:00", "24:00"])},
    )
    assert book(client, customer, barber, services[HAIRCUT]["id"], at(day, "12:00")).status_code == 201

    clash = book(client, customer, second, services[HAIRCUT]["id"], at(day, "12:15"))

    assert clash.status_code == 409 and clash.json()["code"] == "customer_overlap"
    assert at(day, "12:15") not in slots(
        client, customer, second, services[HAIRCUT]["id"], day
    ), "offered what it refuses"


def test_a_customer_cannot_cancel_inside_the_cutoff_but_the_owner_can(
    client, owner, customer, barber, services
):
    soon = slots(client, customer, barber, services[TRIM]["id"], local_day(0)) or slots(
        client, customer, barber, services[TRIM]["id"], local_day(1)
    )
    booking = book(client, customer, barber, services[TRIM]["id"], soon[0]).json()

    late = client.post(f"/bookings/{booking['id']}/cancel", headers=customer)
    by_owner = client.post(f"/bookings/{booking['id']}/cancel", headers=owner)

    assert late.status_code == 409 and late.json()["code"] == "late_cancellation"
    assert by_owner.status_code == 200 and by_owner.json()["status"] == "cancelled"


def test_cancelling_gives_the_slot_back(client, customer, barber, services):
    day = local_day(6)
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "11:00")).json()

    assert client.post(f"/bookings/{booking['id']}/cancel", headers=customer).status_code == 200
    assert at(day, "11:00") in slots(client, customer, barber, services[HAIRCUT]["id"], day)


def test_a_double_tap_with_the_same_key_books_once(client, customer, barber, services):
    day = local_day(7)
    key = {"Idempotency-Key": "tap-123"}

    first = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "09:00"), **key)
    second = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "09:00"), **key)
    different = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "15:00"), **key)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert different.status_code == 409 and different.json()["code"] == "idempotency_mismatch"
    assert client.get("/bookings", headers=customer).json()["total"] == 1


def test_somebody_elses_booking_is_not_found_rather_than_forbidden(
    client, customer, new_customer, barber, services
):
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(8), "10:00")).json()

    peek = client.get(f"/bookings/{booking['id']}", headers=new_customer())

    assert peek.status_code == 404


def test_a_price_change_does_not_reach_back_into_a_booking(client, owner, customer, barber, services):
    haircut = services[HAIRCUT]
    booking = book(client, customer, barber, haircut["id"], at(local_day(9), "10:00")).json()

    client.patch(f"/services/{haircut['id']}", headers=owner, json={"price_minor": 9900})

    assert (
        client.get(f"/bookings/{booking['id']}", headers=customer).json()["price_minor"]
        == haircut["price_minor"]
    )


def test_nothing_is_offered_on_a_day_off(client, owner, customer, barber, services):
    day = local_day(10)
    assert (
        client.post(f"/barbers/{barber}/time-off", headers=owner, json={"date": day.isoformat()}).status_code
        == 201
    )

    assert slots(client, customer, barber, services[HAIRCUT]["id"], day) == []
    refused = book(client, customer, barber, services[HAIRCUT]["id"], at(day, "10:00"))
    assert refused.status_code == 422 and refused.json()["code"] == "barber_off"


def test_the_booking_window_is_enforced_on_both_the_listing_and_the_booking(
    client, customer, barber, services
):
    too_far = local_day(61)

    listing = client.get(
        f"/barbers/{barber}/availability",
        headers=customer,
        params={"date": too_far.isoformat(), "service_id": services[HAIRCUT]["id"]},
    )
    booking = book(client, customer, barber, services[HAIRCUT]["id"], at(too_far, "10:00"))

    assert listing.status_code == 422 and listing.json()["code"] == "beyond_window"
    assert booking.status_code == 422 and booking.json()["code"] == "beyond_window"


def test_a_customer_cannot_manage_the_shop(client, customer):
    assert (
        client.post(
            "/services", headers=customer, json={"name": "x", "duration_minutes": 15, "price_minor": 1}
        ).status_code
        == 403
    )


def test_the_booking_page_is_served_at_the_root(client):
    page = client.get("/")

    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    for testid in ("login-form", "slots", "book", "bookings"):
        assert f'data-testid="{testid}"' in page.text


def test_the_shop_publishes_its_own_clock_and_rules(client):
    from tests.conftest import TZ

    shop = client.get("/shop").json()

    assert shop["timezone"] == TZ.key
    assert shop["today"] == datetime.now(UTC).astimezone(TZ).date().isoformat()
    assert shop["booking_window_days"] == 60 and shop["cancel_cutoff_hours"] == 24


def test_the_owner_sees_a_barbers_days_off_in_date_order(client, owner, barber):
    later, sooner = local_day(12), local_day(10)
    for day in (later, sooner):
        client.post(f"/barbers/{barber}/time-off", headers=owner, json={"date": day.isoformat()})

    listed = client.get(f"/barbers/{barber}/time-off", headers=owner).json()["days"]

    assert listed == [sooner.isoformat(), later.isoformat()]


def test_only_the_owner_sees_days_off(client, customer, barber):
    assert client.get(f"/barbers/{barber}/time-off", headers=customer).status_code == 403
