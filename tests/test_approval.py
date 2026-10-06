"""A customer's booking from 14:00 to 16:00 waits for its barber's yes. No answer
in two hours, and it stands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.booking_rules import approval_state, decide_by, default_approval_rules, in_approval_hours
from app.config import Settings
from app.models import Booking
from tests.conftest import HAIRCUT, TZ, a_second_barber, at, book, local_day, move

CONFIG = Settings(
    database_url="sqlite://",
    secret_key="x" * 32,
    shop_tz=TZ,
    booking_window_days=60,
    cancel_cutoff_hours=24,
    token_hours=1,
)


def needs_approval(config: Settings, start: datetime) -> bool:
    return in_approval_hours(default_approval_rules(config), config.shop_tz, start)


def local(hhmm: str, days: int = 3) -> datetime:
    hours, minutes = map(int, hhmm.split(":"))
    day = local_day(days)
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=TZ).astimezone(UTC)


@pytest.mark.parametrize(
    ("hhmm", "waits"),
    [
        ("13:45", False),
        ("14:00", True),
        ("15:00", True),
        ("15:45", True),
        ("16:00", False),
        ("10:00", False),
    ],
)
def test_the_hours_that_wait_are_from_two_up_to_but_not_including_four(hhmm, waits):
    assert needs_approval(CONFIG, local(hhmm)) is waits


def test_the_hours_are_the_shops_whatever_the_season():
    in_summer = datetime(2026, 7, 15, 14, 0, tzinfo=TZ).astimezone(UTC)
    in_winter = datetime(2026, 1, 15, 14, 0, tzinfo=TZ).astimezone(UTC)
    assert needs_approval(CONFIG, in_summer) and needs_approval(CONFIG, in_winter)
    assert not needs_approval(CONFIG, in_summer - timedelta(minutes=15))
    assert not needs_approval(CONFIG, in_winter + timedelta(hours=2))


def test_the_wait_is_two_hours_or_until_the_booking_starts_if_that_is_sooner():
    asked = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)

    assert decide_by(CONFIG, asked, asked + timedelta(days=2)) == asked + timedelta(hours=2)
    assert decide_by(CONFIG, asked, asked + timedelta(minutes=30)) == asked + timedelta(minutes=30)


def test_a_booking_in_the_hours_waits_for_the_barber(client, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00"))

    assert made.status_code == 201
    body = made.json()
    assert body["status"] == "confirmed", "the chair is held while the barber answers"
    assert body["approval"] == "pending"
    assert body["decide_by"] is not None


def test_a_booking_outside_the_hours_waits_for_no_one(client, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    assert made["approval"] is None
    assert made["decide_by"] is None


def test_the_owner_booking_a_guest_in_the_hours_needs_no_yes(client, owner, barber, services):
    made = client.post(
        "/bookings/guest",
        headers=owner,
        json={
            "barber_id": barber,
            "service_id": services[HAIRCUT]["id"],
            "start": at(local_day(3), "15:00"),
            "guest_name": "Yossi",
        },
    )

    assert made.json()["approval"] is None


def test_a_waiting_booking_holds_the_chair(client, new_customer, barber, services):
    first, second = new_customer(), new_customer()
    haircut, start = services[HAIRCUT]["id"], at(local_day(3), "15:00")
    book(client, first, barber, haircut, start)

    taken = book(client, second, barber, haircut, start)

    assert taken.status_code == 409 and taken.json()["code"] == "slot_taken"


def test_the_barber_approves_their_own_booking(client, owner, customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    made = book(client, customer, barber_id, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    approved = client.post(f"/bookings/{made['id']}/approve", headers=barber_headers)

    assert approved.status_code == 200
    assert approved.json()["approval"] == "approved"
    assert approved.json()["status"] == "confirmed"
    assert approved.json()["decide_by"] is None
    assert client.post(f"/bookings/{made['id']}/approve", headers=barber_headers).status_code == 200


def test_the_barber_declines_and_the_time_is_free_again(client, owner, customer, new_customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    haircut, start = services[HAIRCUT]["id"], at(local_day(3), "15:00")
    made = book(client, customer, barber_id, haircut, start).json()

    declined = client.post(f"/bookings/{made['id']}/decline", headers=barber_headers)

    assert declined.status_code == 200
    body = declined.json()
    assert (body["status"], body["approval"], body["cancelled_by"]) == ("cancelled", "declined", "staff")
    assert book(client, new_customer(), barber_id, haircut, start).status_code == 201


def test_a_declined_booking_no_longer_counts_toward_the_limit(client, owner, customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    haircut = services[HAIRCUT]["id"]
    first = book(client, customer, barber_id, haircut, at(local_day(3), "15:00")).json()
    book(client, customer, barber_id, haircut, at(local_day(3), "10:00"))
    client.post(f"/bookings/{first['id']}/decline", headers=barber_headers)

    assert book(client, customer, barber_id, haircut, at(local_day(3), "11:00")).status_code == 201


def test_the_owner_may_answer_for_any_barber(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "14:30")).json()

    assert client.post(f"/bookings/{made['id']}/approve", headers=owner).json()["approval"] == "approved"


def test_a_barber_cannot_answer_for_another_barbers_booking(client, owner, customer, barber, services):
    _, someone_else = a_second_barber(client, owner)
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    for verb in ("approve", "decline"):
        assert client.post(f"/bookings/{made['id']}/{verb}", headers=someone_else).status_code == 404


def test_a_customer_cannot_answer_for_the_barber(client, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    for verb in ("approve", "decline"):
        assert client.post(f"/bookings/{made['id']}/{verb}", headers=customer).status_code == 403


def test_there_is_nothing_to_approve_in_a_booking_outside_the_hours(
    client, owner, customer, barber, services
):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    answer = client.post(f"/bookings/{made['id']}/approve", headers=owner)

    assert answer.status_code == 409 and answer.json()["code"] == "nothing_to_approve"


def test_a_declined_booking_cannot_then_be_approved(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()
    client.post(f"/bookings/{made['id']}/decline", headers=owner)

    answer = client.post(f"/bookings/{made['id']}/approve", headers=owner)

    assert answer.status_code == 409 and answer.json()["code"] == "already_declined"


def test_an_approved_booking_cannot_then_be_declined(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()
    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    answer = client.post(f"/bookings/{made['id']}/decline", headers=owner)

    assert answer.status_code == 409 and answer.json()["code"] == "already_approved"


def _age(client, booking_id: str, hours: float) -> None:
    """Make the booking's wait start `hours` ago, as if the time had passed."""
    with client.app.state.sessionmaker() as session:
        booking = session.get(Booking, booking_id)
        booking.decide_by = booking.decide_by - timedelta(hours=hours)
        session.commit()


def test_with_no_answer_the_booking_stands_after_the_wait(client, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()
    _age(client, made["id"], 2)

    shown = client.get(f"/bookings/{made['id']}", headers=customer).json()

    assert shown["approval"] == "approved"
    assert shown["status"] == "confirmed"
    assert shown["decide_by"] is None


def test_a_wait_that_ran_out_cannot_be_declined(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()
    _age(client, made["id"], 2)

    answer = client.post(f"/bookings/{made['id']}/decline", headers=owner)

    assert answer.status_code == 409 and answer.json()["code"] == "already_approved"


def test_approval_state_reads_silence_as_yes_only_for_a_booking_still_standing():
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    waiting = Booking(status="confirmed", approval="pending", decide_by=now + timedelta(hours=1))
    assert approval_state(waiting, now) == "pending"
    assert approval_state(waiting, now + timedelta(hours=1)) == "approved"
    waiting.status = "cancelled"
    assert approval_state(waiting, now) is None, "a booking the customer cancelled is not waiting"
    declined = Booking(status="cancelled", approval="declined", decide_by=now)
    assert approval_state(declined, now) == "declined"


def test_the_customer_cancelling_a_waiting_booking_stops_the_wait(client, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    cancelled = client.post(f"/bookings/{made['id']}/cancel", headers=customer).json()

    assert cancelled["status"] == "cancelled"
    assert cancelled["approval"] is None


def test_the_barber_sees_the_waiting_booking_in_their_diary(client, owner, customer, services):
    barber_id, barber_headers = a_second_barber(client, owner)
    made = book(client, customer, barber_id, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    [seen] = client.get("/bookings", headers=barber_headers).json()["content"]

    assert (seen["id"], seen["approval"]) == (made["id"], "pending")


def test_moving_into_the_hours_makes_the_booking_wait_again(client, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    moved = move(client, customer, made["id"], at(local_day(3), "15:00")).json()

    assert moved["approval"] == "pending"


def test_moving_out_of_the_hours_ends_the_wait(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()
    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    moved = move(client, customer, made["id"], at(local_day(3), "10:00")).json()

    assert moved["approval"] is None


def test_an_approved_booking_moved_inside_the_hours_waits_again(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "14:00")).json()
    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    moved = move(client, customer, made["id"], at(local_day(3), "15:00")).json()

    assert moved["approval"] == "pending"


def test_the_owner_moving_a_booking_into_the_hours_decides_it(client, owner, customer, barber, services):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()

    moved = move(client, owner, made["id"], at(local_day(3), "15:00")).json()

    assert moved["approval"] is None


def test_the_hours_can_be_set_by_the_shop():
    shop = Settings(
        database_url="sqlite://",
        secret_key="x" * 32,
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
        approval_from="09:00",
        approval_until="10:00",
        approval_wait_minutes=30,
    )

    assert needs_approval(shop, local("09:30")) and not needs_approval(shop, local("15:00"))
    asked = local("08:00")
    assert decide_by(shop, asked, local("09:30")) == asked + timedelta(minutes=30)


def rules_with(**days) -> dict:
    hours = dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), None)
    hours.update(days)
    return {"enabled": True, "hours": hours}


def test_rules_name_the_days_and_hours_one_by_one():
    thursday_noon = datetime(2026, 10, 8, 12, 0, tzinfo=TZ).astimezone(UTC)
    rules = rules_with(thu=["11:00", "13:00"])

    assert in_approval_hours(rules, TZ, thursday_noon)
    assert not in_approval_hours(rules, TZ, thursday_noon + timedelta(hours=1))
    assert not in_approval_hours(rules, TZ, thursday_noon + timedelta(days=1)), "friday has none"


def test_rules_turned_off_ask_for_nothing_whatever_the_hours():
    thursday_noon = datetime(2026, 10, 8, 12, 0, tzinfo=TZ).astimezone(UTC)

    assert not in_approval_hours({**rules_with(thu=["00:00", "24:00"]), "enabled": False}, TZ, thursday_noon)


def put_rules(client, owner, rules):
    return client.put("/approval-rules", headers=owner, json=rules)


def test_until_the_owner_sets_them_the_rules_are_the_servers(client, owner):
    assert client.get("/approval-rules", headers=owner).json() == default_approval_rules(
        client.app.state.settings
    )


def test_the_owner_turns_the_barbers_yes_off_and_new_bookings_stop_waiting(
    client, owner, customer, barber, services
):
    saved = put_rules(client, owner, {**default_approval_rules(CONFIG), "enabled": False})
    assert saved.status_code == 200 and saved.json()["enabled"] is False

    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    assert made["approval"] is None


def test_the_owner_asks_for_the_yes_only_on_the_days_and_hours_chosen(
    client, owner, new_customer, barber, services
):
    day = local_day(3)
    weekday = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()]
    put_rules(client, owner, rules_with(**{weekday: ["09:00", "11:00"]}))
    haircut = services[HAIRCUT]["id"]

    inside = book(client, new_customer(), barber, haircut, at(day, "10:00")).json()
    after = book(client, new_customer(), barber, haircut, at(day, "15:00")).json()
    next_day = book(client, new_customer(), barber, haircut, at(day + timedelta(days=1), "10:00")).json()

    assert (inside["approval"], after["approval"], next_day["approval"]) == ("pending", None, None)


def test_changing_the_rules_leaves_bookings_already_waiting_to_wait(
    client, owner, customer, barber, services
):
    made = book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "15:00")).json()

    put_rules(client, owner, {**default_approval_rules(CONFIG), "enabled": False})

    assert client.get(f"/bookings/{made['id']}", headers=customer).json()["approval"] == "pending"


def test_only_the_owner_reads_or_changes_the_rules(client, customer):
    assert client.get("/approval-rules", headers=customer).status_code == 403
    assert put_rules(client, customer, default_approval_rules(CONFIG)).status_code == 403
    assert client.get("/approval-rules").status_code == 401


def test_rules_that_make_no_sense_are_refused(client, owner):
    good = default_approval_rules(CONFIG)

    assert put_rules(client, owner, {**good, "hours": {"mon": ["14:00", "16:00"]}}).status_code == 422
    assert (
        put_rules(client, owner, {**good, "hours": {**good["hours"], "mon": ["16:00", "14:00"]}}).status_code
        == 422
    )
    assert (
        put_rules(client, owner, {**good, "hours": {**good["hours"], "mon": ["14:10", "16:00"]}}).status_code
        == 422
    )
    assert put_rules(client, owner, {"hours": good["hours"]}).status_code == 422
