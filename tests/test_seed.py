"""The first-run data is part of the product: it is what a new person sees, so it
must obey every rule the product enforces."""

from datetime import UTC, datetime, timedelta
from itertools import combinations

from app.scheduling import WEEKDAYS
from app.seed import BARBERS
from tests.conftest import HAIRCUT, TZ, login


def next_local(weekday: str):
    day = datetime.now(UTC).astimezone(TZ).date()
    while True:
        day += timedelta(days=1)
        if WEEKDAYS[day.weekday()] == weekday:
            return day


def barber_ids(client, owner) -> dict[str, str]:
    return {b["display_name"]: b["id"] for b in client.get("/barbers", headers=owner).json()["content"]}


def times_offered(client, headers, barber_id, service_id, day) -> list[str]:
    params = {"date": day.isoformat(), "service_id": service_id}
    slots = client.get(f"/barbers/{barber_id}/availability", headers=headers, params=params).json()["slots"]
    return [s["start_local"][11:16] for s in slots]


def test_the_shop_is_open_sunday_to_thursday_ten_to_seven(client, owner):
    created = client.post(
        "/barbers",
        headers=owner,
        json={"username": "new-one", "password": "long-enough", "display_name": "N"},
    ).json()
    hours = client.get(f"/barbers/{created['id']}/hours", headers=owner).json()["hours"]

    assert {day for day, span in hours.items() if span} == {"sun", "mon", "tue", "wed", "thu"}
    assert {tuple(span) for span in hours.values() if span} == {("10:00", "19:00")}


def test_the_seeded_barbers_take_turns(client, owner, customer, services):
    ids = barber_ids(client, owner)
    haircut = services[HAIRCUT]["id"]

    for _username, name, days in BARBERS:
        for weekday in ("sun", "mon", "tue", "wed", "thu"):
            offered = times_offered(client, customer, ids[name], haircut, next_local(weekday))
            if weekday in days:
                assert offered, f"{name} works {weekday} but offers nothing"
            else:
                assert offered == [], f"{name} does not work {weekday} but offers {offered[:3]}"


def test_the_seeded_week_alternates_free_and_taken_times(client, owner, customer, services):
    avi = barber_ids(client, owner)["אבי"]
    offered = times_offered(client, customer, avi, services[HAIRCUT]["id"], next_local("mon"))

    assert "10:00" not in offered and "12:00" not in offered, "the seeded bookings are taken"
    assert "10:30" in offered and "11:00" in offered, "the times between them are free"


def test_no_seeded_customer_is_ever_in_two_chairs_at_once(client, owner):
    rows, offset = [], 0
    while True:
        page = client.get("/bookings", headers=owner, params={"limit": 100, "offset": offset}).json()
        rows += page["content"]
        offset += 100
        if offset >= page["total"]:
            break
    by_customer: dict[str, list] = {}
    for r in rows:
        by_customer.setdefault(r["customer_id"], []).append(
            (datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"]))
        )

    assert rows, "the seed made no bookings"
    clashes = [
        (a, b)
        for spans in by_customer.values()
        for a, b in combinations(spans, 2)
        if a[0] < b[1] and b[0] < a[1]
    ]
    assert clashes == [], f"the seed broke the product's own rule: {clashes[:2]}"


def test_the_two_customers_to_sign_in_as_are_free_to_book(client, passwords):
    for username in ("customer", "yael"):
        mine = client.get("/bookings", headers=login(client, username, passwords["customer"])).json()
        assert (
            mine["total"] == 0
        ), f"{username} must be able to book: the demo is two of them going for one time"


def test_every_seeded_barber_can_sign_in(client, passwords):
    for username, name, _days in BARBERS:
        me = client.get("/me", headers=login(client, username, passwords["barber"])).json()
        assert me == {**me, "role": "barber", "display_name": name}
