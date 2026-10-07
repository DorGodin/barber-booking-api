"""Web Push: the barber is told of a request, the customer of an answer. Nothing but "there is news"
is sent, and only to a push service's own address."""

from __future__ import annotations

import secrets
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.push import VapidSender, endpoint_allowed, generate_keys, unb64, vapid_token
from tests.conftest import HAIRCUT, TZ, SentTexts, a_second_barber, at, book, local_day, login

FCM = "https://fcm.googleapis.com/fcm/send/"
PRIVATE, PUBLIC = generate_keys()


class FakePush:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.answer = 201
        self.explode = False

    def send(self, endpoint: str) -> int:
        if self.explode:
            raise RuntimeError("the push service is down")
        self.sent.append(endpoint)
        return self.answer


@pytest.fixture
def pushed(tmp_path: Path, monkeypatch, passwords):
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
        vapid_public_key=PUBLIC,
    )
    fake = FakePush()
    with TestClient(create_app(config, sms=SentTexts(), push_sender=fake)) as client:
        yield client, fake


def shop(client, passwords):
    """The pushed app is its own server: its barber and menu are made through it."""
    owner = login(client, "owner", passwords["owner"])
    barber_id, barber_headers = a_second_barber(client, owner)
    menu = {s["name"]: s for s in client.get("/services", headers=owner).json()["content"]}
    return owner, barber_id, barber_headers, menu[HAIRCUT]["id"]


def fresh(client):
    username = f"c-{secrets.token_hex(4)}"
    client.post("/customers", json={"username": username, "password": "long-enough", "display_name": "C"})
    return login(client, username, "long-enough")


def subscribe(client, headers, name="a"):
    endpoint = f"{FCM}{name}-{secrets.token_hex(4)}"
    assert client.post("/push/subscribe", headers=headers, json={"endpoint": endpoint}).status_code == 201
    return endpoint


def test_without_a_key_pair_there_is_no_push(client, customer):
    assert client.get("/push/key", headers=customer).status_code == 404
    answer = client.post("/push/subscribe", headers=customer, json={"endpoint": FCM + "x"})
    assert answer.status_code == 404 and answer.json()["code"] == "push_unavailable"


def test_the_public_key_is_given_to_a_signed_in_user_only(pushed, passwords):
    client, _ = pushed
    customer = fresh(client)

    assert client.get("/push/key", headers=customer).json() == {"key": PUBLIC}
    assert client.get("/push/key").status_code == 401


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example/collect",
        "http://fcm.googleapis.com/fcm/send/x",
        "http://127.0.0.1:8000/admin",
        "https://fcm.googleapis.com.evil.example/x",
        "javascript:alert(1)",
    ],
)
def test_an_address_that_is_not_a_push_service_is_refused(pushed, endpoint, passwords):
    client, _ = pushed
    customer = fresh(client)

    refused = client.post("/push/subscribe", headers=customer, json={"endpoint": endpoint})

    assert refused.status_code == 422 and refused.json()["code"] == "push_endpoint_refused"


def test_the_push_services_own_hosts_are_accepted():
    for endpoint in (
        "https://fcm.googleapis.com/fcm/send/x",
        "https://web.push.apple.com/x",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://wns2-par02p.notify.windows.com/x",
    ):
        assert endpoint_allowed(endpoint), endpoint
    assert not endpoint_allowed("http://localhost/x")
    assert endpoint_allowed("http://127.0.0.1:9000/x", ("127.0.0.1",))


def test_subscribing_twice_is_one_subscription_and_it_follows_the_person(pushed, passwords):
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    client.post("/push/subscribe", headers=me, json={"endpoint": endpoint})
    client.post("/push/subscribe", headers=owner, json={"endpoint": endpoint})

    made = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()
    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    assert fake.sent == []


def test_a_customer_is_told_when_the_barber_answers(pushed, passwords):
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()

    client.post(f"/bookings/{made['id']}/approve", headers=owner)

    assert fake.sent == [endpoint]


def test_a_customer_is_told_of_a_no_too_and_only_once_for_the_same_answer(pushed, passwords):
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, me)
    first = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()
    second = book(client, me, barber, haircut, at(local_day(3), "15:30")).json()
    client.post(f"/bookings/{first['id']}/decline", headers=owner)
    client.post(f"/bookings/{second['id']}/approve", headers=owner)
    client.post(f"/bookings/{second['id']}/approve", headers=owner)

    assert fake.sent == [endpoint, endpoint]


def test_the_barber_is_told_of_a_request_and_not_of_an_ordinary_booking(pushed, passwords):
    client, fake = pushed
    _, barber, barber_headers, haircut = shop(client, passwords)
    me = fresh(client)
    endpoint = subscribe(client, barber_headers, "barber")

    book(client, me, barber, haircut, at(local_day(3), "10:00"))
    assert fake.sent == []
    book(client, me, barber, haircut, at(local_day(3), "15:00"))

    assert fake.sent == [endpoint]


def test_a_move_into_the_hours_tells_the_barber_again(pushed, passwords):
    client, fake = pushed
    _, barber, barber_headers, haircut = shop(client, passwords)
    me = fresh(client)
    subscribe(client, barber_headers, "barber")
    made = book(client, me, barber, haircut, at(local_day(3), "10:00")).json()

    client.post(f"/bookings/{made['id']}/move", headers=me, json={"start": at(local_day(3), "15:00")})

    assert len(fake.sent) == 1


def test_a_push_that_fails_never_breaks_the_booking(pushed, passwords):
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    subscribe(client, me)
    made = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()
    fake.explode = True

    answered = client.post(f"/bookings/{made['id']}/approve", headers=owner)

    assert answered.status_code == 200 and answered.json()["approval"] == "approved"


def test_a_subscription_the_push_service_says_is_gone_is_removed(pushed, passwords):
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    subscribe(client, me)
    first = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()
    second = book(client, me, barber, haircut, at(local_day(3), "15:30")).json()
    fake.answer = 410
    client.post(f"/bookings/{first['id']}/approve", headers=owner)
    sent_before = len(fake.sent)

    client.post(f"/bookings/{second['id']}/approve", headers=owner)

    assert len(fake.sent) == sent_before, "nothing is sent to an address that was removed"


def test_a_service_error_keeps_the_subscription(pushed, passwords):
    client, fake = pushed
    owner, barber, _, haircut = shop(client, passwords)
    me = fresh(client)
    subscribe(client, me)
    first = book(client, me, barber, haircut, at(local_day(3), "15:00")).json()
    second = book(client, me, barber, haircut, at(local_day(3), "15:30")).json()
    fake.answer = 503
    client.post(f"/bookings/{first['id']}/approve", headers=owner)
    client.post(f"/bookings/{second['id']}/approve", headers=owner)

    assert len(fake.sent) == 2


def test_only_the_owner_of_a_subscription_can_remove_it(pushed, passwords):
    client, _ = pushed
    me, other = fresh(client), login(client, "owner", passwords["owner"])
    endpoint = subscribe(client, me)

    client.post("/push/unsubscribe", headers=other, json={"endpoint": endpoint})
    client.post("/push/unsubscribe", headers=me, json={"endpoint": endpoint})

    assert client.post("/push/subscribe", headers=me, json={"endpoint": endpoint}).status_code == 201


def test_a_key_pair_is_a_private_scalar_and_an_uncompressed_point():
    private, public = generate_keys()

    assert len(unb64(private)) == 32
    point = unb64(public)
    assert len(point) == 65 and point[0] == 4


def test_the_token_names_the_push_service_the_shop_and_when_it_ends():
    token = vapid_token(FCM + "x", PRIVATE, "mailto:owner@example.com", now=1_000_000)
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(PUBLIC))
    public_pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    claims = jwt.decode(
        token,
        public_pem,
        algorithms=["ES256"],
        audience="https://fcm.googleapis.com",
        options={"verify_exp": False},
    )

    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:owner@example.com"
    assert claims["exp"] == 1_000_000 + 12 * 3600


def test_the_sender_posts_nothing_in_the_body_and_signs_with_the_shops_key(monkeypatch):
    private, public = generate_keys()
    seen = {}

    def fake_post(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return httpx.Response(201)

    monkeypatch.setattr(httpx, "post", fake_post)

    status = VapidSender(private, public, "mailto:o@example.com").send(FCM + "abc")

    assert status == 201 and seen["url"] == FCM + "abc"
    assert (
        seen["headers"]["Authorization"].startswith("vapid t=")
        and f"k={public}" in seen["headers"]["Authorization"]
    )
    assert seen["headers"]["Content-Length"] == "0"


def test_the_sender_never_posts_to_an_address_that_is_not_a_push_service(monkeypatch):
    called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.append(a) or httpx.Response(201))

    status = VapidSender(PRIVATE, PUBLIC, "mailto:o@example.com").send("http://169.254.169.254/latest")

    assert status == 400 and called == []
