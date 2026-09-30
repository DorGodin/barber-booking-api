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

from tests.conftest import ALL_WEEK, TZ

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
        s for s in httpx.get(f"{server}/services", headers=owner).json()["content"] if s["name"] == "Haircut"
    )

    customers = []
    for _ in offsets:
        name = f"c-{secrets.token_hex(4)}"
        httpx.post(
            f"{server}/customers", json={"username": name, "password": "long-enough", "display_name": "C"}
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
