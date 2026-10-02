"""The race, against a real server with two worker processes.

In-process tests cannot show this: TestClient runs one request at a time. Two
workers also rule out a Python lock quietly doing the job - only the database
can serialise across processes.

Asserted as "exactly one 201, every other a 409, and no 5xx". Asserting only
"one booking exists" would pass a server that answers the losers with 500s,
which is what SQLite does without BEGIN IMMEDIATE.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tests.conftest import ALL_WEEK, HAIRCUT, TZ

PASSWORDS = {role: secrets.token_urlsafe(12) for role in ("owner", "barber", "customer")}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path_factory.mktemp('race') / 'race.db'}",
        "SECRET_KEY": secrets.token_hex(32),
        **{f"SEED_{role.upper()}_PASSWORD": pw for role, pw in PASSWORDS.items()},
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--port",
            str(port),
            "--workers",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health").status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("the server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def token(base, username, password):
    resp = httpx.post(f"{base}/auth/token", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.parametrize(
    "offsets",
    [[0] * 12, [0, 15, 0, 15, 0, 15, 0, 15, 0, 15, 0, 15]],
    ids=["same-start", "overlapping-starts"],
)
def test_many_customers_racing_for_one_slot_get_exactly_one_booking(server, offsets):
    owner = token(server, "owner", PASSWORDS["owner"])
    barber = httpx.post(
        f"{server}/barbers",
        headers=owner,
        json={"username": f"r-{secrets.token_hex(4)}", "password": "long-enough", "display_name": "R"},
    ).json()["id"]
    httpx.put(f"{server}/barbers/{barber}/hours", headers=owner, json={"hours": ALL_WEEK})
    haircut = next(
        s for s in httpx.get(f"{server}/services", headers=owner).json()["content"] if s["name"] == HAIRCUT
    )

    customers = []
    for n, _ in enumerate(offsets):
        name = f"c-{secrets.token_hex(4)}"
        # Each from an address of its own, as different people's phones are: one
        # address may make only a few accounts an hour.
        httpx.post(
            f"{server}/customers",
            json={"username": name, "password": "long-enough", "display_name": "C"},
            headers={"X-Forwarded-For": f"198.18.0.{n + 1}"},
        )
        customers.append(token(server, name, "long-enough"))

    day = (datetime.now(UTC).astimezone(TZ) + timedelta(days=3)).date()
    ten = datetime(day.year, day.month, day.day, 10, 0, tzinfo=TZ).astimezone(UTC)

    def attempt(args):
        headers, offset = args
        start = (ten + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return httpx.post(
            f"{server}/bookings",
            headers=headers,
            json={"barber_id": barber, "service_id": haircut["id"], "start": start},
            timeout=30,
        ).status_code

    with ThreadPoolExecutor(max_workers=len(offsets)) as pool:
        codes = sorted(pool.map(attempt, zip(customers, offsets, strict=True)))

    assert [c for c in codes if c >= 500] == [], f"the losers crashed instead of being refused: {codes}"
    assert codes.count(201) == 1, f"expected exactly one booking: {codes}"
    assert codes.count(409) == len(offsets) - 1, codes


def test_sign_ins_and_sign_outs_at_once_never_answer_with_a_server_error(server):
    """Every sign-in writes now - it clears or records a failure - and so does
    every sign-out. Two workers that each read, then try to write, deadlock in
    SQLite, and one is answered with "database is locked": a 500 for an owner
    signing in while a customer on the same page signs out. Found in CI."""
    people = []
    for n in range(10):
        name = f"c-{secrets.token_hex(4)}"
        httpx.post(
            f"{server}/customers",
            json={"username": name, "password": "long-enough", "display_name": "C"},
            headers={"X-Forwarded-For": f"2001:db8::1:{n + 1:x}"},
        )
        people.append(name)
    sessions = [token(server, name, "long-enough") for name in people]

    def sign_in(name):
        return httpx.post(f"{server}/auth/token", json={"username": name, "password": "long-enough"})

    def fail_sign_in(name):
        return httpx.post(f"{server}/auth/token", json={"username": name, "password": "not-the-password"})

    def sign_out(headers):
        return httpx.post(f"{server}/auth/logout", headers=headers)

    calls = [lambda n=n: sign_in(n) for n in people] + [lambda n=n: fail_sign_in(n) for n in people]
    calls += [lambda h=h: sign_out(h) for h in sessions]
    with ThreadPoolExecutor(len(calls)) as pool:
        codes = sorted(r.status_code for r in pool.map(lambda call: call(), calls))

    assert [c for c in codes if c >= 500] == [], f"a sign-in or sign-out met a locked database: {codes}"
    assert codes.count(200) == 10 and codes.count(401) == 10 and codes.count(204) == 10, codes


def test_the_owner_saving_while_customers_book_never_answers_with_a_server_error(server):
    """The owner's writes - hours, days off, services, barbers - took no write lock.
    A save that read before it wrote, while a booking held the lock, was refused
    by SQLite at once: a 500 for the owner. The same deadlock as the sign-ins."""
    owner = token(server, "owner", PASSWORDS["owner"])
    barber = httpx.post(
        f"{server}/barbers",
        headers=owner,
        json={"username": f"b-{secrets.token_hex(4)}", "password": "long-enough", "display_name": "B"},
    ).json()["id"]
    httpx.put(f"{server}/barbers/{barber}/hours", headers=owner, json={"hours": ALL_WEEK})
    haircut = next(
        s for s in httpx.get(f"{server}/services", headers=owner).json()["content"] if s["name"] == HAIRCUT
    )["id"]
    people = []
    for n in range(10):
        name = f"c-{secrets.token_hex(4)}"
        httpx.post(
            f"{server}/customers",
            json={"username": name, "password": "long-enough", "display_name": "C"},
            headers={"X-Forwarded-For": f"2001:db8::2:{n + 1:x}"},
        )
        people.append(token(server, name, "long-enough"))
    day = (datetime.now(UTC).astimezone(TZ) + timedelta(days=5)).date()
    starts = [datetime(day.year, day.month, day.day, 8 + n, 0, tzinfo=TZ).astimezone(UTC) for n in range(10)]

    def book(n):
        return httpx.post(
            f"{server}/bookings",
            headers=people[n],
            json={
                "barber_id": barber,
                "service_id": haircut,
                "start": starts[n].strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

    def save_hours(_):
        return httpx.put(f"{server}/barbers/{barber}/hours", headers=owner, json={"hours": ALL_WEEK})

    def add_service(n):
        return httpx.post(
            f"{server}/services",
            headers=owner,
            json={"name": f"s-{secrets.token_hex(4)}", "duration_minutes": 30, "price_minor": 5000},
        )

    calls = [lambda n=n: book(n) for n in range(10)] + [lambda n=n: save_hours(n) for n in range(10)]
    calls += [lambda n=n: add_service(n) for n in range(10)]
    with ThreadPoolExecutor(len(calls)) as pool:
        codes = sorted(r.status_code for r in pool.map(lambda call: call(), calls))

    assert [c for c in codes if c >= 500] == [], f"an owner's save met a locked database: {codes}"


def test_customers_moving_to_one_time_at_once_get_it_once_and_the_rest_keep_theirs(server):
    """Six customers, each with a booking of their own, all move to the same
    time at once. One gets it; every other is refused and still has the
    booking they had - a move never leaves a customer with nothing."""
    owner = token(server, "owner", PASSWORDS["owner"])
    barber = httpx.post(
        f"{server}/barbers",
        headers=owner,
        json={"username": f"m-{secrets.token_hex(4)}", "password": "long-enough", "display_name": "M"},
    ).json()["id"]
    httpx.put(f"{server}/barbers/{barber}/hours", headers=owner, json={"hours": ALL_WEEK})
    haircut = next(
        s for s in httpx.get(f"{server}/services", headers=owner).json()["content"] if s["name"] == HAIRCUT
    )
    day = (datetime.now(UTC).astimezone(TZ) + timedelta(days=4)).date()

    def local(hour):
        return (
            datetime(day.year, day.month, day.day, hour, 0, tzinfo=TZ)
            .astimezone(UTC)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    holders = []
    for n in range(6):
        name = f"mv-{secrets.token_hex(4)}"
        httpx.post(
            f"{server}/customers",
            json={"username": name, "password": "long-enough", "display_name": "C"},
            headers={"X-Forwarded-For": f"2001:db8:fe::{n + 1}"},
        )
        headers = token(server, name, "long-enough")
        booking = httpx.post(
            f"{server}/bookings",
            headers=headers,
            json={"barber_id": barber, "service_id": haircut["id"], "start": local(8 + n)},
        )
        assert booking.status_code == 201, booking.text
        holders.append((headers, booking.json()))

    def attempt(holder):
        headers, booking = holder
        return httpx.post(
            f"{server}/bookings/{booking['id']}/move", headers=headers, json={"start": local(17)}, timeout=30
        ).status_code

    with ThreadPoolExecutor(max_workers=len(holders)) as pool:
        codes = sorted(pool.map(attempt, holders))

    assert [c for c in codes if c >= 500] == [], f"the losers crashed instead of being refused: {codes}"
    assert codes.count(200) == 1, f"expected exactly one move: {codes}"
    assert codes.count(409) == len(holders) - 1, codes
    starts = sorted(httpx.get(f"{server}/bookings/{b['id']}", headers=h).json()["start"] for h, b in holders)
    stayed = sorted(b["start"] for _, b in holders)
    assert local(17) in starts
    assert len([s for s in starts if s in stayed]) == len(holders) - 1, starts


def test_a_phone_booking_and_customers_racing_for_one_time_get_it_once(server):
    """The owner books a caller while customers on the site go for the same
    time. Exactly one of them gets it - whichever lock comes first."""
    owner = token(server, "owner", PASSWORDS["owner"])
    barber = httpx.post(
        f"{server}/barbers",
        headers=owner,
        json={"username": f"g-{secrets.token_hex(4)}", "password": "long-enough", "display_name": "G"},
    ).json()["id"]
    httpx.put(f"{server}/barbers/{barber}/hours", headers=owner, json={"hours": ALL_WEEK})
    haircut = next(
        s for s in httpx.get(f"{server}/services", headers=owner).json()["content"] if s["name"] == HAIRCUT
    )
    day = (datetime.now(UTC).astimezone(TZ) + timedelta(days=5)).date()
    start = (
        datetime(day.year, day.month, day.day, 12, 0, tzinfo=TZ)
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    customers = []
    for n in range(5):
        name = f"gc-{secrets.token_hex(4)}"
        httpx.post(
            f"{server}/customers",
            json={"username": name, "password": "long-enough", "display_name": "C"},
            headers={"X-Forwarded-For": f"2001:db8:fd::{n + 1}"},
        )
        customers.append(token(server, name, "long-enough"))
    body = {"barber_id": barber, "service_id": haircut["id"], "start": start}

    def attempt(who):
        if who == "owner":
            return httpx.post(
                f"{server}/bookings/guest", headers=owner, json={**body, "guest_name": "בטלפון"}, timeout=30
            ).status_code
        return httpx.post(f"{server}/bookings", headers=who, json=body, timeout=30).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(attempt, ["owner", *customers]))

    assert [c for c in codes if c >= 500] == [], f"the losers crashed instead of being refused: {codes}"
    assert codes.count(201) == 1, f"expected exactly one booking: {codes}"
    assert codes.count(409) == 5, codes
