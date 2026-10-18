"""A standing booking: a customer's regular time, every few weeks. Only the next booking is held; the
one after it is made once that one has begun, at the same hour on the shop's clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models import Booking, StandingBooking
from app.scheduling import local_instant
from app.standing import renew_due
from tests.conftest import HAIRCUT, book, local_day
from tests.test_api import at


def stand(client, headers, booking_id, every=3):
    return client.post(f"/bookings/{booking_id}/standing", json={"every_weeks": every}, headers=headers)


def begin(client, booking_id) -> datetime:
    """The booking has begun: moved an hour into the past, as time would. Returns its new start."""
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    start = now.replace(minute=now.minute - now.minute % 15) - timedelta(hours=1)
    with client.app.state.sessionmaker() as session:
        session.execute(
            update(Booking)
            .where(Booking.id == booking_id)
            .values(start_utc=start, end_utc=start + timedelta(minutes=30))
        )
        session.commit()
    return start


def renew(client, now=None):
    with client.app.state.sessionmaker() as session:
        return renew_due(session, client.app.state.settings, now or datetime.now(UTC))


def of_standing(client, standing_id) -> list[Booking]:
    with client.app.state.sessionmaker() as session:
        return session.scalars(
            select(Booking).where(Booking.standing_id == standing_id).order_by(Booking.start_utc)
        ).all()


def test_a_booking_ahead_becomes_a_standing_booking_once(client, new_customer, barber, services):
    me = new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    stood = stand(client, me, made["id"])

    assert stood.status_code == 201, stood.text
    assert stood.json()["standing"]["every_weeks"] == 3
    again = stand(client, me, made["id"], every=2)
    assert again.status_code == 409 and again.json()["code"] == "already_standing"


def test_somebody_elses_booking_is_not_found_and_only_two_three_or_four_weeks_stand(
    client, new_customer, barber, services
):
    me, other = new_customer(), new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    assert stand(client, other, made["id"]).status_code == 404
    assert stand(client, me, made["id"], every=5).status_code == 422


def test_once_it_has_begun_the_next_is_made_at_the_same_hour_and_only_once(
    client, new_customer, barber, services
):
    me = new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()
    standing_id = stand(client, me, made["id"]).json()["standing"]["id"]
    start = begin(client, made["id"])

    told = renew(client)
    renew(client)

    first, nxt = of_standing(client, standing_id)
    tz = client.app.state.settings.shop_tz
    assert nxt.start_utc.astimezone(tz).date() == start.astimezone(tz).date() + timedelta(weeks=3)
    assert nxt.start_utc.astimezone(tz).time() == start.astimezone(tz).time()
    assert nxt.status == "confirmed" and first.id == made["id"]
    assert any(t.user_ids == [nxt.customer_id] and t.notice[0] == "התור הקבוע הבא נקבע" for t in told)


def test_nothing_is_made_while_a_booking_of_it_is_ahead(client, new_customer, barber, services):
    me = new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()
    standing_id = stand(client, me, made["id"]).json()["standing"]["id"]

    assert renew(client) == []
    assert len(of_standing(client, standing_id)) == 1


def test_a_time_that_is_taken_is_skipped_and_told_once(client, new_customer, barber, services):
    me, rival = new_customer(), new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()
    standing_id = stand(client, me, made["id"]).json()["standing"]["id"]
    start = begin(client, made["id"])
    # Three weeks on at the same hour on the shop's clock - which a change of clock moves in UTC.
    tz = client.app.state.settings.shop_tz
    local = start.astimezone(tz)
    then = local_instant(local.date() + timedelta(weeks=3), local.hour * 60 + local.minute, tz)
    taken = book(client, rival, barber, services[HAIRCUT]["id"], then.isoformat())
    assert taken.status_code == 201, taken.text

    told = renew(client)

    assert len(of_standing(client, standing_id)) == 1
    assert [t.notice[0] for t in told] == ["לא הצלחנו לשמור את התור הקבוע"]
    assert renew(client) == [], "told once about the same time"
    with client.app.state.sessionmaker() as session:
        assert session.get(StandingBooking, standing_id).skipped_until == then


def test_a_stopped_standing_booking_makes_nothing_and_the_booking_stays(
    client, new_customer, barber, services
):
    me = new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()
    standing_id = stand(client, me, made["id"]).json()["standing"]["id"]

    assert client.post(f"/standing/{standing_id}/stop", headers=me).status_code == 204
    begin(client, made["id"])

    assert renew(client) == []
    mine = client.get("/bookings", headers=me).json()["content"]
    assert [b["standing"] for b in mine if b["id"] == made["id"]] == [None]


def test_deleting_the_account_stops_its_standing_bookings(client, new_customer, barber, services):
    me = new_customer()
    made = book(client, me, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()
    standing_id = stand(client, me, made["id"]).json()["standing"]["id"]

    assert client.delete("/me", headers=me).status_code == 204

    with client.app.state.sessionmaker() as session:
        assert session.get(StandingBooking, standing_id).stopped_at is not None
