"""A service that works at any time (an emergency haircut) opens the whole day on every day, whatever
the barber's hours and days off - and a booking that is already there still takes its time."""

from __future__ import annotations

import pytest

from tests.conftest import ALL_WEEK, HAIRCUT, a_second_barber, at, book, local_day, slots

SHORT_DAYS = {**dict.fromkeys(ALL_WEEK, ["09:00", "10:00"]), "sat": None}


@pytest.fixture
def emergency(client, owner):
    made = client.post(
        "/services",
        headers=owner,
        json={"name": "חירום זמן", "duration_minutes": 30, "price_minor": 20000, "any_time": True},
    )
    assert made.status_code == 201
    return made.json()


@pytest.fixture
def short_barber(client, owner):
    barber_id, _ = a_second_barber(client, owner)
    assert (
        client.put(f"/barbers/{barber_id}/hours", headers=owner, json={"hours": SHORT_DAYS}).status_code
        == 200
    )
    return barber_id


def test_a_service_says_whether_it_works_at_any_time_and_only_the_owner_sets_it(
    client, owner, customer, services
):
    service = services[HAIRCUT]["id"]
    assert services[HAIRCUT]["any_time"] is False

    assert client.patch(f"/services/{service}", headers=customer, json={"any_time": True}).status_code == 403
    on = client.patch(f"/services/{service}", headers=owner, json={"any_time": True}).json()
    off = client.patch(f"/services/{service}", headers=owner, json={"any_time": False}).json()

    assert (on["any_time"], off["any_time"]) == (True, False)


def test_it_offers_the_whole_day_where_an_ordinary_service_offers_the_barbers_hour(
    client, customer, short_barber, services, emergency
):
    day = local_day(4)
    ordinary = slots(client, customer, short_barber, services[HAIRCUT]["id"], day)
    anytime = slots(client, customer, short_barber, emergency["id"], day)

    assert len(ordinary) == 3, ordinary
    assert at(day, "03:00") in anytime and at(day, "23:15") in anytime
    assert len(anytime) > 40


def test_it_offers_a_day_the_barber_is_closed(client, owner, customer, short_barber, services, emergency):
    closed = next(local_day(n) for n in range(2, 12) if local_day(n).weekday() == 5)

    assert slots(client, customer, short_barber, services[HAIRCUT]["id"], closed) == []
    assert len(slots(client, customer, short_barber, emergency["id"], closed)) > 40


def test_it_offers_a_day_off(client, owner, customer, short_barber, emergency):
    day = local_day(5)
    client.post(f"/barbers/{short_barber}/time-off", headers=owner, json={"date": day.isoformat()})

    assert len(slots(client, customer, short_barber, emergency["id"], day)) > 40


def test_a_booking_already_there_still_takes_its_time(
    client, owner, new_customer, short_barber, services, emergency
):
    day = local_day(6)
    other = book(client, new_customer(), short_barber, services[HAIRCUT]["id"], at(day, "09:00"))
    assert other.status_code == 201
    taken = book(client, new_customer(), short_barber, emergency["id"], at(day, "18:00"))
    assert taken.status_code == 201

    offered = slots(client, owner, short_barber, emergency["id"], day)
    refused = book(client, new_customer(), short_barber, emergency["id"], at(day, "18:00"))

    assert at(day, "09:00") not in offered and at(day, "18:00") not in offered
    assert at(day, "08:45") not in offered, "a half hour from 08:45 would run into the booking at 09:00"
    assert at(day, "18:30") in offered
    assert refused.status_code == 409 and refused.json()["code"] == "slot_taken"


def test_an_emergency_booking_takes_the_time_from_the_ordinary_services_too(
    client, new_customer, short_barber, services, emergency
):
    day = local_day(6)
    assert book(client, new_customer(), short_barber, emergency["id"], at(day, "09:00")).status_code == 201

    ordinary = book(client, new_customer(), short_barber, services[HAIRCUT]["id"], at(day, "09:00"))

    assert ordinary.status_code == 409 and ordinary.json()["code"] == "slot_taken"


def test_it_can_be_booked_at_three_in_the_morning_and_an_ordinary_service_cannot(
    client, customer, new_customer, short_barber, services, emergency
):
    day = local_day(7)

    night = book(client, customer, short_barber, emergency["id"], at(day, "03:00"))
    ordinary = book(client, new_customer(), short_barber, services[HAIRCUT]["id"], at(day, "03:00"))

    assert night.status_code == 201
    assert ordinary.status_code == 422 and ordinary.json()["code"] == "outside_hours"


def test_the_calendar_shows_every_day_as_free_for_it(client, customer, short_barber, services, emergency):
    month = local_day(3).isoformat()[:7]

    ordinary = client.get(
        f"/barbers/{short_barber}/days",
        headers=customer,
        params={"month": month, "service_id": services[HAIRCUT]["id"]},
    ).json()["days"]
    anytime = client.get(
        f"/barbers/{short_barber}/days",
        headers=customer,
        params={"month": month, "service_id": emergency["id"]},
    ).json()["days"]

    assert any(not d["works"] for d in ordinary), "the barber has a closed day"
    assert anytime and all(d["works"] and d["free"] > 0 for d in anytime[1:])


def test_the_rule_stays_inside_the_booking_window(client, customer, short_barber, emergency):
    too_far = local_day(120)

    assert (
        client.get(
            f"/barbers/{short_barber}/availability",
            headers=customer,
            params={"date": too_far.isoformat(), "service_id": emergency["id"]},
        ).status_code
        == 422
    )
