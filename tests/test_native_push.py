"""Notifications to the shop's app on a phone, through Firebase: the device is registered, told the fixed
words of its person's role - never a name or a time - and forgotten when Firebase says it is gone."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import PushDevice
from app.native_push import WORDS, FcmSender, ServiceAccount
from tests.conftest import TZ, SentTexts, at, book, local_day
from tests.test_push import fresh, shop

TOKEN = "fcm-token-" + "a" * 40


class FakePhones:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.gone: set[str] = set()

    def send(self, token: str, title: str, body: str) -> bool:
        self.sent.append((token, title, body))
        return token not in self.gone


@pytest.fixture
def phones(tmp_path: Path, monkeypatch, passwords):
    for role, password in passwords.items():
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", password)
    config = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key=secrets.token_hex(32),
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
        signups_per_address=1000,
    )
    fake = FakePhones()
    with TestClient(create_app(config, sms=SentTexts(), native_sender=fake)) as client:
        yield client, fake


def register(client, headers, token=TOKEN, platform="ios"):
    return client.post("/push/devices", headers=headers, json={"platform": platform, "token": token})


def test_the_barbers_phone_is_told_of_a_new_booking_in_the_staffs_words_and_no_more(phones, passwords):
    client, fake = phones
    _, barber, barber_headers, haircut = shop(client, passwords)
    assert register(client, barber_headers, platform="android").status_code == 201

    book(client, fresh(client), barber, haircut, at(local_day(3), "10:00"))

    assert fake.sent == [(TOKEN, *WORDS["staff"])]


def test_the_customers_phone_is_told_of_the_barbers_answer_in_the_customers_words(phones, passwords):
    client, fake = phones
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    register(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()

    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    assert fake.sent == [(TOKEN, *WORDS["customer"])]


def test_a_phone_firebase_says_is_gone_is_forgotten(phones, passwords):
    client, fake = phones
    _, barber, barber_headers, haircut = shop(client, passwords)
    register(client, barber_headers)
    fake.gone.add(TOKEN)

    book(client, fresh(client), barber, haircut, at(local_day(3), "10:00"))
    book(client, fresh(client), barber, haircut, at(local_day(4), "10:00"))

    assert len(fake.sent) == 1
    with client.app.state.sessionmaker() as session:
        assert session.query(PushDevice).count() == 0


def test_a_phone_follows_the_person_signed_in_on_it_and_signing_out_ends_it(phones, passwords):
    client, fake = phones
    _, barber, barber_headers, haircut = shop(client, passwords)
    me = fresh(client)
    register(client, me)
    register(client, barber_headers)

    assert client.post("/push/devices/remove", headers=me, json={"token": TOKEN}).json() == {
        "registered": False
    }
    with client.app.state.sessionmaker() as session:
        assert session.query(PushDevice).count() == 1, "only the person it belongs to removes it"
    client.post("/push/devices/remove", headers=barber_headers, json={"token": TOKEN})
    book(client, fresh(client), barber, haircut, at(local_day(3), "10:00"))

    assert fake.sent == []


def test_a_token_is_checked_and_a_shop_without_firebase_takes_none(phones, client, customer):
    shop_client, _ = phones
    me = fresh(shop_client)

    assert register(shop_client, me, token="short").status_code == 422
    assert register(shop_client, me, token="a" * 30 + "/../x").status_code == 422
    assert register(shop_client, me, platform="windows").status_code == 422
    assert shop_client.post("/push/devices", json={"platform": "ios", "token": TOKEN}).status_code == 401
    refused = register(client, customer)
    assert (refused.status_code, refused.json()["code"]) == (404, "push_unavailable")


def test_deleting_the_account_forgets_its_phones(phones):
    client, _ = phones
    me = fresh(client)
    register(client, me)

    client.delete("/me", headers=me)

    with client.app.state.sessionmaker() as session:
        assert session.query(PushDevice).count() == 0


def test_firebase_is_asked_as_the_shops_service_account_and_told_the_device_and_the_words(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    account = ServiceAccount(
        "shop-123", "push@shop-123.iam.gserviceaccount.com", pem.decode(), "https://oauth2.example/token"
    )
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.host == "oauth2.example":
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        if json.loads(request.content)["message"]["token"] == "gone-token":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        return httpx.Response(200, json={"name": "projects/shop-123/messages/1"})

    transport = httpx.MockTransport(answer)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    sender = FcmSender(account, "https://fcm.example")

    assert sender.send(TOKEN, *WORDS["staff"]) is True
    assert sender.send("gone-token", *WORDS["staff"]) is False

    grant, message = asked[0], asked[1]
    assertion = dict(httpx.QueryParams(grant.content.decode()))["assertion"]
    claims = jwt.decode(
        assertion, key.public_key(), algorithms=["RS256"], audience="https://oauth2.example/token"
    )
    assert claims["iss"] == account.client_email and claims["scope"].endswith("firebase.messaging")
    assert str(message.url) == "https://fcm.example/v1/projects/shop-123/messages:send"
    assert message.headers["authorization"] == "Bearer ya29.token"
    sent = json.loads(message.content)["message"]
    assert (sent["token"], sent["notification"]) == (
        TOKEN,
        {"title": WORDS["staff"][0], "body": WORDS["staff"][1]},
    )
    assert (
        len([r for r in asked if r.url.host == "oauth2.example"]) == 1
    ), "the access token is kept for its hour"
