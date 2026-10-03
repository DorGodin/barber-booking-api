"""The month's calendar: for each bookable day, whether the barber works it and
how many times are free - always the same count as that day's own list."""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import HAIRCUT, a_second_barber, at, book, local_day, slots


def days(client, headers, barber_id, service_id, month, **params):
    return client.get(
        f"/barbers/{barber_id}/days",
        headers=headers,
        params={"month": month, "service_id": service_id, **params},
    )


def month_of(day) -> str:
    return day.isoformat()[:7]


def test_each_day_counts_exactly_the_times_its_own_list_offers(client, customer, barber, services):
    service = services[HAIRCUT]["id"]
    later = local_day(3)
    book(client, customer, barber, service, at(later, "12:00"))

    resp = days(client, customer, barber, service, month_of(later))

    assert resp.status_code == 200, resp.text
    listed = {d["date"]: d for d in resp.json()["days"]}
    assert later.isoformat() in listed
    for day_text, entry in listed.items():
        day = date.fromisoformat(day_text)
        assert entry["works"] is True
        assert entry["free"] == len(slots(client, customer, barber, service, day)), day_text


def test_the_month_starts_today_and_never_offers_a_past_day(client, customer, barber, services):
    today = local_day(0)

    listed = days(client, customer, barber, services[HAIRCUT]["id"], month_of(today)).json()["days"]

    assert listed[0]["date"] == today.isoformat()


def test_the_month_stops_where_the_booking_window_ends(client, customer, barber, services):
    last = local_day(60)

    listed = days(client, customer, barber, services[HAIRCUT]["id"], month_of(last)).json()["days"]

    assert listed[-1]["date"] == last.isoformat()


def test_a_day_off_is_a_day_the_barber_does_not_work(client, owner, customer, barber, services):
    off = local_day(4)
    assert (
        client.post(f"/barbers/{barber}/time-off", headers=owner, json={"date": off.isoformat()}).status_code
        == 201
    )

    listed = {
        d["date"]: d
        for d in days(client, customer, barber, services[HAIRCUT]["id"], month_of(off)).json()["days"]
    }

    assert listed[off.isoformat()] == {"date": off.isoformat(), "works": False, "free": 0}


def test_a_customer_is_not_counted_a_time_their_own_booking_elsewhere_takes(
    client, owner, customer, barber, services
):
    service = services[HAIRCUT]["id"]
    day = local_day(5)
    other, _ = a_second_barber(client, owner)
    assert book(client, customer, other, service, at(day, "15:00")).status_code == 201

    def free(headers):
        listed = days(client, headers, barber, service, month_of(day)).json()["days"]
        return next(d["free"] for d in listed if d["date"] == day.isoformat())

    assert free(customer) < free(owner)
    assert free(customer) == len(slots(client, customer, barber, service, day))


def test_while_moving_the_bookings_own_time_counts_as_free(client, customer, barber, services):
    service = services[HAIRCUT]["id"]
    day = local_day(6)
    booking = book(client, customer, barber, service, at(day, "11:00")).json()

    def free(**params):
        listed = days(client, customer, barber, service, month_of(day), **params).json()["days"]
        return next(d["free"] for d in listed if d["date"] == day.isoformat())

    assert free(moving=booking["id"]) > free()


def test_a_month_already_over_or_not_yet_open_is_refused_with_the_reason(client, customer, barber, services):
    service = services[HAIRCUT]["id"]
    gone = local_day(0).replace(day=1) - timedelta(days=1)
    far = local_day(60).replace(day=28) + timedelta(days=10)

    past = days(client, customer, barber, service, month_of(gone))
    beyond = days(client, customer, barber, service, month_of(far))

    assert (past.status_code, past.json()["code"]) == (422, "in_past")
    assert (beyond.status_code, beyond.json()["code"]) == (422, "beyond_window")


def test_a_month_that_is_not_a_month_is_refused(client, customer, barber, services):
    for month in ("2026-13", "2026-1", "26-10", "2026-10-01"):
        assert days(client, customer, barber, services[HAIRCUT]["id"], month).status_code == 422, month
