from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.main import create_app, prepare_database
from app.seed import MENU
from app.sms import SmsFailed

# The seeded menu by duration, read from the seed itself, so renaming a service
# there never breaks a test here.
HAIRCUT, TRIM, COMBO = (name for name, _minutes, _price in MENU)

TZ = ZoneInfo("Asia/Jerusalem")
PASSWORDS = {role: secrets.token_urlsafe(12) for role in ("owner", "barber", "customer")}
ALL_WEEK = dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), ["00:00", "24:00"])


class SentTexts:
    """The SMS provider, for the product's own tests: every message kept, and
    told to fail when a test needs it to."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.failing = False

    def send(self, phone: str, text: str) -> None:
        if self.failing:
            raise SmsFailed("the provider is down")
        self.messages.append((phone, text))

    def code_for(self, phone: str) -> str:
        [code] = re.findall(r"\b\d{4}\b", next(t for p, t in reversed(self.messages) if p == phone))
        return code


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
        # These tests make customers from one address, the test client's. The
        # limit itself is tested with its real value in test_signup_limits.py.
        signups_per_address=1000,
    )
    with TestClient(create_app(config, sms=SentTexts())) as test_client:
        yield test_client


@pytest.fixture
def texts(client) -> SentTexts:
    return client.app.state.sms


def login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/auth/token", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def passwords() -> dict[str, str]:
    """The seed passwords, through a fixture and never through an import:
    `from tests.conftest import PASSWORDS` loads this file a second time under a
    second module name, and the random passwords above come out different."""
    return PASSWORDS


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


def at(day, hhmm):
    hours, minutes = map(int, hhmm.split(":"))
    return (
        datetime(day.year, day.month, day.day, hours, minutes, tzinfo=TZ)
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


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


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    """A database file of the test's own, for tests of what happens to the
    file itself - migrations, backups - rather than through the API."""
    for role in ("owner", "barber", "customer"):
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", secrets.token_urlsafe(12))
    engine = make_engine(f"sqlite:///{tmp_path / 'shop.db'}")
    yield engine
    engine.dispose()


def start(engine, **settings) -> None:
    """What every worker does when the server starts."""
    config = Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        secret_key=secrets.token_hex(32),
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
        **settings,
    )
    prepare_database(engine, make_sessionmaker(engine), config)


def version(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def move(client, headers, booking_id, start):
    return client.post(f"/bookings/{booking_id}/move", headers=headers, json={"start": start})


def a_second_barber(client, owner) -> tuple[str, dict]:
    username = f"b-{secrets.token_hex(4)}"
    barber_id = client.post(
        "/barbers",
        headers=owner,
        json={"username": username, "password": "long-enough", "display_name": "B2"},
    ).json()["id"]
    client.put(f"/barbers/{barber_id}/hours", headers=owner, json={"hours": ALL_WEEK})
    return barber_id, login(client, username, "long-enough")
