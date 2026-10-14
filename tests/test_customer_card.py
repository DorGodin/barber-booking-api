"""A customer as the staff know them - visits, cancellations, bookings not come to, a note - and the
mark for a booking the customer did not come to, which counts with their cancellations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Booking, User
from tests.conftest import HAIRCUT, a_second_barber, at, book, local_day, login
from tests.test_reviews import past_booking
from tests.test_sign_in_with_code import sign_in


def me_id(client, headers) -> str:
    return client.get("/me", headers=headers).json()["id"]


def card(client, headers, customer_id):
    return client.get(f"/customers/{customer_id}/card", headers=headers)


def test_the_card_counts_what_the_customer_did(client, owner, customer, barber, services):
    haircut = services[HAIRCUT]["id"]
    past_booking(client, customer, barber, haircut, hours_ago=50)
    latest = past_booking(client, customer, barber, haircut, hours_ago=30)
    missed = past_booking(client, customer, barber, haircut, hours_ago=5)
    with client.app.state.sessionmaker() as session:
        session.get(Booking, missed).no_show = True
        session.commit()
    gone = book(client, customer, barber, haircut, at(local_day(4), "10:00")).json()["id"]
    client.post(f"/bookings/{gone}/cancel", headers=customer)
    book(client, customer, barber, haircut, at(local_day(5), "10:00"))

    seen = card(client, owner, me_id(client, customer)).json()

    assert (seen["visits"], seen["no_shows"], seen["cancellations"], seen["upcoming"]) == (2, 1, 1, 1)
    with client.app.state.sessionmaker() as session:
        latest_start = session.get(Booking, latest).start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert seen["last_visit"] == latest_start, "the last one come to - not the one missed after it"
    assert seen["note"] == ""


def test_the_owner_sees_the_phone_and_a_barber_does_not(client, owner, barber, services, texts):
    headers = sign_in(client, texts, phone="0541112222", name="רותם")
    book(client, headers, barber, services[HAIRCUT]["id"], at(local_day(4), "11:00"))
    customer = me_id(client, headers)
    with client.app.state.sessionmaker() as session:
        barber_headers = login(client, session.get(User, barber).username, "long-enough")

    assert card(client, owner, customer).json()["phone"] == "0541112222"
    assert card(client, barber_headers, customer).json()["phone"] is None


def test_a_barber_knows_only_the_customers_who_booked_with_them(client, owner, customer, barber, services):
    _, other_barber = a_second_barber(client, owner)
    book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(4), "12:00"))

    assert card(client, other_barber, me_id(client, customer)).status_code == 404
    assert card(client, customer, me_id(client, customer)).status_code == 403
    assert card(client, owner, "usr_nobody").status_code == 404


def test_the_note_is_kept_shared_and_taken_away_when_empty(client, owner, customer):
    customer_id = me_id(client, customer)

    kept = client.put(f"/customers/{customer_id}/note", headers=owner, json={"text": "  מספר 2 בצדדים  "})

    assert kept.json()["note"] == "מספר 2 בצדדים"
    assert card(client, owner, customer_id).json()["note"] == "מספר 2 בצדדים"
    assert client.put(f"/customers/{customer_id}/note", headers=owner, json={"text": ""}).json()["note"] == ""
    assert (
        client.put(f"/customers/{customer_id}/note", headers=owner, json={"text": "x" * 1001}).status_code
        == 422
    )
    assert (
        client.put(f"/customers/{customer_id}/note", headers=customer, json={"text": "x"}).status_code == 403
    )


def test_a_booking_is_marked_not_come_to_once_its_time_has_come_and_the_mark_is_taken_back(
    client, owner, customer, barber, services
):
    started = past_booking(client, customer, barber, services[HAIRCUT]["id"], hours_ago=0)
    with client.app.state.sessionmaker() as session:
        row = session.get(Booking, started)
        row.start_utc = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
        row.end_utc = row.start_utc + timedelta(minutes=30)
        session.commit()
    ahead = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(4), "13:00")).json()["id"]

    marked = client.post(f"/bookings/{started}/no-show", headers=owner)
    again = client.post(f"/bookings/{started}/no-show", headers=owner)
    early = client.post(f"/bookings/{ahead}/no-show", headers=owner)

    assert marked.status_code == 200 and marked.json()["no_show"] is True and again.status_code == 200
    assert (early.status_code, early.json()["code"]) == (409, "not_started")
    assert client.post(f"/bookings/{started}/no-show", headers=customer).status_code == 403
    assert client.delete(f"/bookings/{started}/no-show", headers=owner).json()["no_show"] is False


def test_bookings_not_come_to_count_with_cancellations_toward_waiting_for_the_barber(
    client, owner, customer, barber, services
):
    haircut = services[HAIRCUT]["id"]
    for day in (4, 5):
        made = book(client, customer, barber, haircut, at(local_day(day), "10:00")).json()["id"]
        client.post(f"/bookings/{made}/cancel", headers=customer)
    missed = past_booking(client, customer, barber, haircut, hours_ago=30)
    with client.app.state.sessionmaker() as session:
        session.get(Booking, missed).no_show = True
        session.commit()

    next_one = book(client, customer, barber, haircut, at(local_day(6), "10:00")).json()

    assert next_one["approval"] == "pending"


def test_a_booking_not_come_to_is_not_reviewed(client, customer, barber, services):
    missed = past_booking(client, customer, barber, services[HAIRCUT]["id"], hours_ago=30)
    with client.app.state.sessionmaker() as session:
        session.get(Booking, missed).no_show = True
        session.commit()

    refused = client.post(f"/bookings/{missed}/review", headers=customer, json={"stars": 5})

    assert (refused.status_code, refused.json()["code"]) == (409, "not_reviewable")


def test_the_staff_see_the_whole_of_today_and_a_customer_only_what_is_ahead(
    client, owner, customer, barber, services
):
    over = past_booking(client, customer, barber, services[HAIRCUT]["id"], hours_ago=0)
    with client.app.state.sessionmaker() as session:
        row = session.get(Booking, over)
        row.end_utc = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
        row.start_utc = row.end_utc - timedelta(minutes=30)
        session.commit()
        still_today = row.start_utc.astimezone(client.app.state.settings.shop_tz).date() == (
            datetime.now(UTC).astimezone(client.app.state.settings.shop_tz).date()
        )

    def ids(headers):
        return {
            b["id"]
            for b in client.get("/bookings?upcoming=true&limit=100", headers=headers).json()["content"]
        }

    assert over not in ids(customer)
    assert (over in ids(owner)) == still_today
