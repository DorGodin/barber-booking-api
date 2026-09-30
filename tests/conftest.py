from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.seed import MENU

# The seeded menu by duration, read from the seed itself, so renaming a service
# there never breaks a test here.
HAIRCUT, TRIM, COMBO = (name for name, _minutes, _price in MENU)

TZ = ZoneInfo("Asia/Jerusalem")
PASSWORDS = {role: secrets.token_urlsafe(12) for role in ("owner", "barber", "customer")}
ALL_WEEK = dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), ["00:00", "24:00"])


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    for role, password in PASSWORDS.items():
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", password)
    config = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key=secrets.token_hex(32),
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
    )
    with TestClient(create_app(config)) as test_client:
        yield test_client


def login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/auth/token", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def owner(client):
    return login(client, "owner", PASSWORDS["owner"])


@pytest.fixture
def customer(client):
    return login(client, "customer", PASSWORDS["customer"])


@pytest.fixture
def new_customer(client):
    def _make() -> dict:
        username = f"c-{secrets.token_hex(4)}"
        client.post("/customers", json={"username": username, "password": "long-enough", "display_name": "C"})
        return login(client, username, "long-enough")

    return _make


@pytest.fixture
def barber(client, owner) -> str:
    """A barber of this test's own, working around the clock, so a test never
    depends on the time of day it happens to run at."""
    created = client.post(
        "/barbers",
        headers=owner,
        json={"username": f"b-{secrets.token_hex(4)}", "password": "long-enough", "display_name": "B"},
    )
    barber_id = created.json()["id"]
    assert (
        client.put(f"/barbers/{barber_id}/hours", headers=owner, json={"hours": ALL_WEEK}).status_code == 200
    )
    return barber_id


@pytest.fixture
def services(client, owner) -> dict[str, dict]:
    return {s["name"]: s for s in client.get("/services", headers=owner).json()["content"]}


def local_day(days_ahead: int):
    return (datetime.now(UTC).astimezone(TZ) + timedelta(days=days_ahead)).date()


def slots(client, headers, barber_id, service_id, day) -> list[str]:
    resp = client.get(
        f"/barbers/{barber_id}/availability",
        headers=headers,
        params={"date": day.isoformat(), "service_id": service_id},
    )
    assert resp.status_code == 200, resp.text
    return [s["start"] for s in resp.json()["slots"]]


def book(client, headers, barber_id, service_id, start, **extra):
    return client.post(
        "/bookings",
        headers={**headers, **extra},
        json={"barber_id": barber_id, "service_id": service_id, "start": start},
    )
