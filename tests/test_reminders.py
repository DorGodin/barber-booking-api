"""A reminder two hours before a booking, by push: once, only for a booking that stands, with the
words fetched by the browser that was woken."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.models import Booking
from app.reminders import send_due, when_words
from tests.conftest import HAIRCUT, TRIM, TZ, at, book, local_day
from tests.test_push import fresh, pushed, shop, subscribe  # noqa: F401


def start_of(client, booking_id: str) -> datetime:
    with client.app.state.sessionmaker() as session:
        return session.get(Booking, booking_id).start_utc


def remind(client, now: datetime) -> int:
    app = client.app
    return send_due(app.state.sessionmaker, app.state.push, app.state.settings, now)


def reminded(client, fake, endpoint: str, now: datetime) -> int:
    """How many pushes this call sent to this browser - the shop's seeded bookings may be due too."""
    before = fake.sent.count(endpoint)
    remind(client, now)
    return fake.sent.count(endpoint) - before


def the_words(client, endpoint: str) -> dict:
    return client.post("/push/notice", json={"endpoint": endpoint}).json()


def test_a_booking_two_hours_off_is_reminded_with_when_what_and_where(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()
    now = start_of(client, made["id"]) - timedelta(minutes=100)

    assert reminded(client, fake, endpoint, now) == 1

    assert fake.sent == [endpoint]
    notice = the_words(client, endpoint)
    assert notice["title"] == "תזכורת לתור"
    assert "10:00" in notice["body"] and HAIRCUT in notice["body"] and "אצל" in notice["body"]


def test_the_words_are_given_once_then_the_browser_shows_its_fixed_wording(pushed, passwords):  # noqa: F811
    client, _ = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()
    remind(client, start_of(client, made["id"]) - timedelta(minutes=100))

    first, second = the_words(client, endpoint), the_words(client, endpoint)

    assert first["title"] == "תזכורת לתור" and second == {"title": None, "body": None}


def test_a_stranger_with_a_guessed_address_gets_no_words(pushed):  # noqa: F811
    client, _ = pushed

    assert the_words(client, "https://fcm.googleapis.com/fcm/send/nobody") == {"title": None, "body": None}


def test_it_is_not_time_before_the_window_nor_after_the_booking_began(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    start = start_of(client, book(client, me, barber, haircut, at(local_day(3), "10:00")).json()["id"])

    assert reminded(client, fake, endpoint, start - timedelta(hours=3)) == 0
    assert reminded(client, fake, endpoint, start + timedelta(minutes=1)) == 0
    assert fake.sent == []


def test_a_booking_is_reminded_once(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    start = start_of(client, book(client, me, barber, haircut, at(local_day(3), "10:00")).json()["id"])

    assert reminded(client, fake, endpoint, start - timedelta(minutes=100)) == 1
    assert reminded(client, fake, endpoint, start - timedelta(minutes=90)) == 0
    assert len(fake.sent) == 1


def test_a_booking_made_inside_the_window_is_not_reminded_of_at_once(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()
    start = start_of(client, made["id"])
    with client.app.state.sessionmaker() as session:
        session.get(Booking, made["id"]).created_at = start - timedelta(minutes=30)
        session.commit()

    assert reminded(client, fake, endpoint, start - timedelta(minutes=20)) == 0
    assert fake.sent == []


def test_a_booking_that_waits_for_the_barber_is_reminded_only_once_it_stands(pushed, passwords):  # noqa: F811
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()
    assert made["approval"] == "pending"
    start = start_of(client, made["id"])
    with client.app.state.sessionmaker() as session:
        session.get(Booking, made["id"]).decide_by = start
        session.commit()

    assert reminded(client, fake, endpoint, start - timedelta(minutes=100)) == 0
    client.post(f"/bookings/{made['id']}/approve", headers=owner)
    fake.sent.clear()
    assert reminded(client, fake, endpoint, start - timedelta(minutes=90)) == 1
    assert len(fake.sent) == 1


def test_a_cancelled_booking_is_not_reminded(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()
    client.post(f"/bookings/{made['id']}/cancel", headers=me)

    assert reminded(client, fake, endpoint, start_of(client, made["id"]) - timedelta(minutes=100)) == 0
    assert fake.sent == []


def test_a_move_gives_the_new_time_its_own_reminder(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()
    remind(client, start_of(client, made["id"]) - timedelta(minutes=100))
    moved = client.post(f"/bookings/{made['id']}/move", headers=me, json={"start": at(local_day(4), "11:00")})
    assert moved.status_code == 200

    assert reminded(client, fake, endpoint, start_of(client, made["id"]) - timedelta(minutes=100)) == 1
    assert len(fake.sent) == 2


def test_two_bookings_made_together_are_one_reminder_naming_both(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    menu = {s["name"]: s["id"] for s in client.get("/services", headers=me).json()["content"]}
    made = client.post(
        "/bookings/group",
        headers=me,
        json={
            "barber_id": barber,
            "start": at(local_day(3), "10:00"),
            "people": [{"service_id": menu[HAIRCUT]}, {"service_id": menu[TRIM], "name": "יוני"}],
        },
    ).json()["bookings"]

    assert reminded(client, fake, endpoint, start_of(client, made[0]["id"]) - timedelta(minutes=100)) == 1

    assert len(fake.sent) == 1
    body = the_words(client, endpoint)["body"]
    assert HAIRCUT in body and TRIM in body and "יוני" in body and "+" in body


def test_only_the_customer_who_has_the_booking_is_reminded(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, barber_headers, haircut = shop(client, passwords)
    me, other = fresh(client), fresh(client)
    subscribe(client, other)
    subscribe(client, barber_headers, "barber")
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()

    remind(client, start_of(client, made["id"]) - timedelta(minutes=100))

    assert fake.sent == []


def test_a_shop_that_turns_reminders_off_sends_none(pushed, passwords):  # noqa: F811
    client, fake = pushed
    _, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    start = start_of(client, book(client, me, barber, haircut, at(local_day(3), "10:00")).json()["id"])
    settings = client.app.state.settings
    client.app.state.settings = Settings(**{**settings.__dict__, "reminder_minutes": 0})

    assert reminded(client, fake, endpoint, start - timedelta(minutes=100)) == 0
    assert fake.sent == []


def test_the_time_is_said_as_today_tomorrow_or_the_date():
    config = Settings(
        database_url="sqlite://",
        secret_key="x" * 32,
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=12,
        token_hours=1,
    )
    now = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)

    assert when_words(datetime(2026, 10, 8, 12, 30, tzinfo=UTC), now, config) == "היום ב־15:30"
    assert when_words(datetime(2026, 10, 9, 8, 0, tzinfo=UTC), now, config) == "מחר ב־11:00"
    assert when_words(datetime(2026, 10, 12, 8, 0, tzinfo=UTC), now, config) == "ב־12.10 בשעה 11:00"
