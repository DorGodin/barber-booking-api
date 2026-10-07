"""Booking for two - the customer and a child or a friend - back to back with one barber, all or none."""

from __future__ import annotations

from datetime import datetime

from tests.conftest import ALL_WEEK, HAIRCUT, TRIM, a_second_barber, at, book, local_day, slots


def group(client, headers, barber, people, start, **extra):
    return client.post(
        "/bookings/group",
        headers=headers,
        json={"barber_id": barber, "start": start, "people": people, **extra},
    )


def two(services, first=HAIRCUT, second=TRIM, name=None):
    return [{"service_id": services[first]["id"]}, {"service_id": services[second]["id"], "name": name}]


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_two_bookings_back_to_back_with_one_barber_for_one_customer(client, customer, barber, services):
    made = group(client, customer, barber, two(services, name="יוני"), at(local_day(4), "10:00"))

    assert made.status_code == 201
    first, second = made.json()["bookings"]
    assert instant(second["start"]) == instant(first["end"])
    assert (first["barber_id"], first["customer_id"]) == (second["barber_id"], second["customer_id"])
    assert first["group_id"] == second["group_id"] == made.json()["group_id"]
    assert (first["for_name"], second["for_name"]) == (None, "יוני")
    assert (first["service_name"], second["service_name"]) == (HAIRCUT, TRIM)
    assert (first["price_minor"], second["price_minor"]) == (
        services[HAIRCUT]["price_minor"],
        services[TRIM]["price_minor"],
    )


def test_if_the_second_does_not_fit_nothing_is_booked(client, owner, customer, services):
    barber_id, _ = a_second_barber(client, owner)
    short = {**ALL_WEEK, **dict.fromkeys(ALL_WEEK, ["09:00", "10:00"])}
    client.put(f"/barbers/{barber_id}/hours", headers=owner, json={"hours": short})
    day = local_day(4)

    refused = group(client, customer, barber_id, two(services, HAIRCUT, HAIRCUT), at(day, "09:30"))

    assert refused.status_code == 422 and refused.json()["code"] == "outside_hours"
    assert client.get("/bookings", headers=customer).json()["total"] == 0


def test_if_the_second_time_is_taken_nothing_is_booked(client, customer, new_customer, barber, services):
    day = local_day(4)
    assert book(client, new_customer(), barber, services[TRIM]["id"], at(day, "10:30")).status_code == 201

    refused = group(client, customer, barber, two(services, HAIRCUT, HAIRCUT), at(day, "10:00"))

    assert refused.status_code == 409 and refused.json()["code"] == "slot_taken"
    assert client.get("/bookings", headers=customer).json()["total"] == 0


def test_a_group_counts_as_one_toward_the_limit_of_bookings_ahead(client, new_customer, barber, services):
    me, haircut = new_customer(), services[HAIRCUT]["id"]
    book(client, me, barber, haircut, at(local_day(3), "09:00"))

    made = group(client, me, barber, two(services), at(local_day(4), "10:00"))

    assert made.status_code == 201
    refused = book(client, me, barber, haircut, at(local_day(5), "10:00"))
    assert refused.status_code == 409 and refused.json()["code"] == "too_many_bookings"


def test_a_customer_at_the_limit_cannot_book_a_group(client, new_customer, barber, services):
    me, haircut = new_customer(), services[HAIRCUT]["id"]
    book(client, me, barber, haircut, at(local_day(3), "09:00"))
    book(client, me, barber, haircut, at(local_day(3), "11:00"))

    refused = group(client, me, barber, two(services), at(local_day(4), "10:00"))

    assert refused.status_code == 409 and refused.json()["code"] == "too_many_bookings"


def test_more_people_than_the_shop_allows_is_refused(client, customer, barber, services):
    three = two(services) + [{"service_id": services[TRIM]["id"]}]

    refused = group(client, customer, barber, three, at(local_day(4), "10:00"))

    assert refused.status_code == 422 and refused.json()["code"] == "group_too_big"


def test_one_person_is_not_a_group(client, customer, barber, services):
    assert group(client, customer, barber, two(services)[:1], at(local_day(4), "10:00")).status_code == 422


def test_only_a_customer_books_a_group(client, owner, barber, services):
    assert group(client, owner, barber, two(services), at(local_day(4), "10:00")).status_code == 403
    assert client.post("/bookings/group", json={}).status_code == 401


def test_a_service_that_is_withdrawn_or_unknown_is_refused(client, owner, customer, barber, services):
    client.patch(f"/services/{services[TRIM]['id']}", headers=owner, json={"active": False})

    withdrawn = group(client, customer, barber, two(services), at(local_day(4), "10:00"))
    unknown = group(
        client,
        customer,
        barber,
        [{"service_id": "svc_nope"}, {"service_id": services[HAIRCUT]["id"]}],
        at(local_day(4), "10:00"),
    )

    assert withdrawn.status_code == 422 and withdrawn.json()["code"] == "service_inactive"
    assert unknown.status_code == 404


def test_the_times_offered_for_two_are_those_where_both_fit_one_after_the_other(
    client, owner, customer, services
):
    barber_id, _ = a_second_barber(client, owner)
    client.put(
        f"/barbers/{barber_id}/hours",
        headers=owner,
        json={"hours": dict.fromkeys(ALL_WEEK, ["09:00", "10:00"])},
    )
    day = local_day(4)
    haircut = services[HAIRCUT]["id"]

    one = slots(client, customer, barber_id, haircut, day)
    both = client.get(
        f"/barbers/{barber_id}/availability",
        headers=customer,
        params={"date": day.isoformat(), "service_id": haircut, "also": [haircut]},
    ).json()["slots"]

    assert len(one) == 3
    assert [s["start"] for s in both] == [at(day, "09:00")]


def test_the_calendar_counts_the_times_for_two(client, owner, customer, services):
    barber_id, _ = a_second_barber(client, owner)
    client.put(
        f"/barbers/{barber_id}/hours",
        headers=owner,
        json={"hours": dict.fromkeys(ALL_WEEK, ["09:00", "10:00"])},
    )
    haircut, month = services[HAIRCUT]["id"], local_day(4).isoformat()[:7]

    alone = client.get(
        f"/barbers/{barber_id}/days", headers=customer, params={"month": month, "service_id": haircut}
    ).json()["days"]
    paired = client.get(
        f"/barbers/{barber_id}/days",
        headers=customer,
        params={"month": month, "service_id": haircut, "also": [haircut]},
    ).json()["days"]

    assert alone[2]["free"] == 3 and paired[2]["free"] == 1


def test_each_booking_waits_for_the_barber_by_the_same_rules(client, customer, barber, services):
    made = group(client, customer, barber, two(services), at(local_day(4), "15:00")).json()["bookings"]

    assert [b["approval"] for b in made] == ["pending", "pending"]


def test_afterwards_each_is_a_booking_of_its_own(client, customer, barber, services):
    first, second = group(client, customer, barber, two(services), at(local_day(5), "10:00")).json()[
        "bookings"
    ]

    cancelled = client.post(f"/bookings/{first['id']}/cancel", headers=customer).json()

    assert cancelled["status"] == "cancelled"
    assert client.get(f"/bookings/{second['id']}", headers=customer).json()["status"] == "confirmed"


def test_the_barber_sees_who_each_booking_is_for(client, owner, customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    group(client, customer, barber_id, two(services, name="יוני"), at(local_day(4), "10:00"))

    seen = client.get("/bookings", headers=barber_headers).json()["content"]

    assert sorted(b["for_name"] or "" for b in seen) == ["", "יוני"]


def test_the_group_cannot_overlap_the_customers_other_booking_elsewhere(
    client, owner, customer, barber, services
):
    other, _ = a_second_barber(client, owner)
    day = local_day(4)
    assert book(client, customer, other, services[TRIM]["id"], at(day, "10:30")).status_code == 201

    refused = group(client, customer, barber, two(services, HAIRCUT, HAIRCUT), at(day, "10:00"))

    assert refused.status_code == 409 and refused.json()["code"] == "customer_overlap"
