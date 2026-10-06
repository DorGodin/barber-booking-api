"""The shop's courses: the owner keeps them, a customer reads them, and the button on a
card opens WhatsApp with the course named."""

from __future__ import annotations

import base64
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.identity import identity_from
from app.main import create_app
from tests.conftest import PASSWORDS, TZ, SentTexts, login

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40


def encoded(raw: bytes) -> dict:
    return {"data": base64.b64encode(raw).decode()}


@pytest.fixture
def with_whatsapp(tmp_path: Path, monkeypatch):
    for role, password in PASSWORDS.items():
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", password)
    config = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key=secrets.token_hex(32),
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
        signups_per_address=1000,
        identity=identity_from({"SHOP_WHATSAPP": "0547868277"}, "TomGoldin"),
    )
    with TestClient(create_app(config, sms=SentTexts())) as client:
        yield client


def make(client, owner, **fields):
    body = {"title": "קורס ברברינג", "subtitle": "8 מפגשים", "starts_on": "2026-11-02", "price_minor": 320000}
    return client.post("/courses", headers=owner, json={**body, **fields})


def test_the_owner_adds_a_course_and_a_customer_reads_it(client, owner, customer):
    made = make(client, owner)

    assert made.status_code == 201
    [seen] = client.get("/courses", headers=customer).json()["content"]
    assert seen["id"] == made.json()["id"]
    assert (seen["title"], seen["subtitle"], seen["starts_on"], seen["price_minor"]) == (
        "קורס ברברינג",
        "8 מפגשים",
        "2026-11-02",
        320000,
    )
    assert seen["image_url"] is None and seen["active"] is True


def test_a_course_may_have_no_date_and_no_price(client, owner, customer):
    made = client.post("/courses", headers=owner, json={"title": "סדנה"}).json()

    assert (made["subtitle"], made["starts_on"], made["price_minor"]) == ("", None, None)


def test_only_the_owner_adds_changes_or_pictures_a_course(client, owner, customer):
    course = make(client, owner).json()["id"]

    assert client.post("/courses", headers=customer, json={"title": "x"}).status_code == 403
    assert client.patch(f"/courses/{course}", headers=customer, json={"title": "y"}).status_code == 403
    assert client.put(f"/courses/{course}/image", headers=customer, json=encoded(JPEG)).status_code == 403
    assert client.delete(f"/courses/{course}/image", headers=customer).status_code == 403
    assert client.get("/courses").status_code == 401


def test_courses_are_listed_by_date_and_those_without_one_come_last(client, owner, customer):
    make(client, owner, title="ג", starts_on=None)
    make(client, owner, title="ב", starts_on="2026-12-01")
    make(client, owner, title="א", starts_on="2026-11-02")

    titles = [c["title"] for c in client.get("/courses", headers=customer).json()["content"]]

    assert titles == ["א", "ב", "ג"]


def test_a_withdrawn_course_is_hidden_from_customers_and_kept_for_the_owner(client, owner, customer):
    course = make(client, owner).json()["id"]

    client.patch(f"/courses/{course}", headers=owner, json={"active": False})

    assert client.get("/courses", headers=customer).json()["total"] == 0
    [kept] = client.get("/courses", headers=owner).json()["content"]
    assert kept["active"] is False


def test_the_owner_changes_a_course_and_clears_its_date_and_price(client, owner):
    course = make(client, owner).json()["id"]

    changed = client.patch(
        f"/courses/{course}", headers=owner, json={"title": "חדש", "starts_on": None, "price_minor": None}
    ).json()

    assert (changed["title"], changed["starts_on"], changed["price_minor"]) == ("חדש", None, None)


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 81},
        {"title": "x", "subtitle": "y" * 121},
        {"title": "x", "price_minor": -1},
        {"title": "x", "starts_on": "soon"},
    ],
)
def test_a_course_that_makes_no_sense_is_refused(client, owner, body):
    assert client.post("/courses", headers=owner, json=body).status_code == 422


def test_an_unknown_course_is_not_found(client, owner):
    assert client.patch("/courses/crs_nope", headers=owner, json={"title": "x"}).status_code == 404
    assert client.put("/courses/crs_nope/image", headers=owner, json=encoded(JPEG)).status_code == 404


def test_the_button_opens_whatsapp_with_the_course_named(with_whatsapp):
    client = with_whatsapp
    owner, customer = (
        login(client, "owner", PASSWORDS["owner"]),
        login(client, "customer", PASSWORDS["customer"]),
    )
    make(client, owner, title="קורס ברברינג")

    [seen] = client.get("/courses", headers=customer).json()["content"]

    link = urlparse(seen["whatsapp_url"])
    assert (link.scheme, link.netloc, link.path) == ("https", "wa.me", "/972547868277")
    assert "קורס ברברינג" in parse_qs(link.query)["text"][0]


def test_without_a_whatsapp_number_there_is_no_link(client, owner, customer):
    make(client, owner)

    [seen] = client.get("/courses", headers=customer).json()["content"]

    assert seen["whatsapp_url"] is None


@pytest.mark.parametrize(
    ("raw", "ending", "kind"),
    [(JPEG, ".jpg", "image/jpeg"), (PNG, ".png", "image/png"), (WEBP, ".webp", "image/webp")],
)
def test_a_picture_is_accepted_by_its_bytes_and_served(client, owner, customer, raw, ending, kind):
    course = make(client, owner).json()["id"]

    saved = client.put(f"/courses/{course}/image", headers=owner, json=encoded(raw))

    assert saved.status_code == 200
    url = saved.json()["image_url"]
    assert url.startswith("/media/course-") and url.endswith(ending)
    served = client.get(url)
    assert (served.status_code, served.headers["content-type"], served.content) == (200, kind, raw)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (encoded(b"GIF89a" + b"\x00" * 20), "invalid_image"),
        (encoded(b"<script>alert(1)</script>"), "invalid_image"),
        ({"data": "not base64 !!"}, "invalid_image"),
        (encoded(JPEG + b"\x00" * 3_000_000), "image_too_large"),
    ],
    ids=["a gif", "a script", "not base64", "too large"],
)
def test_a_picture_that_is_not_one_is_refused(client, owner, body, code):
    course = make(client, owner).json()["id"]

    refused = client.put(f"/courses/{course}/image", headers=owner, json=body)

    assert refused.status_code == 422 and refused.json()["code"] == code
    assert client.get("/courses", headers=owner).json()["content"][0]["image_url"] is None


def test_a_new_picture_replaces_the_old_one_and_the_old_file_goes(client, owner):
    course = make(client, owner).json()["id"]
    first = client.put(f"/courses/{course}/image", headers=owner, json=encoded(JPEG)).json()["image_url"]

    second = client.put(f"/courses/{course}/image", headers=owner, json=encoded(PNG)).json()["image_url"]

    assert first != second
    assert client.get(first).status_code == 404
    assert client.get(second).status_code == 200


def test_removing_a_picture_removes_the_file(client, owner):
    course = make(client, owner).json()["id"]
    url = client.put(f"/courses/{course}/image", headers=owner, json=encoded(JPEG)).json()["image_url"]

    removed = client.delete(f"/courses/{course}/image", headers=owner).json()

    assert removed["image_url"] is None
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("name", ["../barber.db", "..%2Fbarber.db", "course-x.jpg", "profile.jpg"])
def test_the_media_route_serves_no_other_file(client, name):
    assert client.get(f"/media/{name}").status_code == 404
