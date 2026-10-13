"""The owner and the barbers sign in as a customer does - a mobile, and the code sent to it.
Whose phone it is decides what opens: the owner's screen, a barber's diary, or a customer's
bookings. There is no other way in on the page."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import User
from tests.conftest import PASSWORDS, TZ, SentTexts
from tests.test_sign_in_with_code import ask, sign_in, verify

OWNER_PHONE, BARBER_PHONE = "0500000001", "0521112233"


def shop(tmp_path: Path, monkeypatch, **settings) -> TestClient:
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
        **settings,
    )
    return TestClient(create_app(config, sms=SentTexts()))


def new_barber(client, owner, **fields):
    return client.post("/barbers", headers=owner, json={"display_name": "תומר", **fields})


def role_of(client, headers) -> str:
    return client.get("/me", headers=headers).json()["role"]


def test_the_owners_phone_opens_the_owners_screen_whatever_name_is_typed(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, owner_phone=OWNER_PHONE) as client:
        headers = sign_in(client, client.app.state.sms, phone=OWNER_PHONE, name="מישהו אחר")

        me = client.get("/me", headers=headers).json()

    assert (me["role"], me["display_name"]) == ("owner", "בעל המספרה")


def test_the_owners_name_typed_with_another_phone_is_only_a_customer(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, owner_phone=OWNER_PHONE) as client:
        headers = sign_in(client, client.app.state.sms, phone="0539998877", name="בעל המספרה")

        assert role_of(client, headers) == "customer"
        assert client.get("/barbers", headers=headers).status_code == 200
        assert client.post("/barbers", headers=headers, json={"display_name": "x"}).status_code == 403


def test_a_shop_from_before_the_setting_gets_the_phone_and_a_changed_setting_changes_it(
    tmp_path, monkeypatch
):
    with shop(tmp_path, monkeypatch) as client:
        assert ask(client, OWNER_PHONE).status_code == 202
        opened = verify(client, client.app.state.sms.code_for(OWNER_PHONE), OWNER_PHONE)
        assert opened.json()["role"] == "customer", "with no setting the number is anybody's"
    monkeypatch.undo()

    with pytest.raises(RuntimeError, match="OWNER_PHONE"):
        with shop(tmp_path, monkeypatch, owner_phone=OWNER_PHONE):
            pass
    with shop(tmp_path, monkeypatch, owner_phone="0500000002") as client:
        assert role_of(client, sign_in(client, client.app.state.sms, phone="0500000002")) == "owner"
    with shop(tmp_path, monkeypatch, owner_phone="0500000003") as client:
        assert role_of(client, sign_in(client, client.app.state.sms, phone="0500000003")) == "owner"
        with client.app.state.sessionmaker() as session:
            assert (
                session.scalar(select(User).where(User.phone == "0500000002")) is None
            ), "the old number is free"


@pytest.mark.parametrize("raw", ["050123", "03-5551234", "owner"])
def test_a_number_that_is_not_a_mobile_stops_the_server_naming_the_setting(monkeypatch, raw):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    monkeypatch.setenv("SMS_URL", "console")
    monkeypatch.setenv("OWNER_PHONE", raw)

    with pytest.raises(RuntimeError, match="OWNER_PHONE"):
        Settings.from_env()


def test_the_setting_is_stored_the_way_every_phone_is(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    monkeypatch.setenv("SMS_URL", "console")
    monkeypatch.setenv("OWNER_PHONE", "+972 50-588 9067")

    assert Settings.from_env().owner_phone == "0505889067"


def test_a_barber_added_with_a_name_and_a_phone_signs_in_by_code(client, owner, texts):
    made = new_barber(client, owner, phone="052-111 2233")

    assert made.status_code == 201 and made.json()["phone"] == BARBER_PHONE
    headers = sign_in(client, texts, phone=BARBER_PHONE, name="כל שם")
    me = client.get("/me", headers=headers).json()
    assert (me["id"], me["role"], me["display_name"]) == (made.json()["id"], "barber", "תומר")


def test_a_barbers_phone_is_the_owners_to_see_and_nobody_elses(client, owner, customer):
    barber = new_barber(client, owner, phone=BARBER_PHONE).json()["id"]

    def listed(headers):
        return next(b for b in client.get("/barbers", headers=headers).json()["content"] if b["id"] == barber)

    assert listed(owner)["phone"] == BARBER_PHONE
    assert "phone" not in listed(customer)


@pytest.mark.parametrize("phone", ["123", "03-5551234", "05012345678"])
def test_a_barbers_phone_must_be_a_mobile(client, owner, phone):
    refused = new_barber(client, owner, phone=phone)

    assert (refused.status_code, refused.json()["code"]) == (422, "bad_phone")


def test_a_phone_is_one_persons(client, owner, texts):
    sign_in(client, texts, phone="0531234567")
    first = new_barber(client, owner, phone=BARBER_PHONE).json()["id"]
    second = new_barber(client, owner).json()["id"]

    for taken in ("0531234567", BARBER_PHONE):
        refused = client.patch(f"/barbers/{second}", headers=owner, json={"phone": taken})
        assert (refused.status_code, refused.json()["code"]) == (409, "phone_taken")
    assert new_barber(client, owner, phone=BARBER_PHONE).json()["code"] == "phone_taken"
    again = client.patch(f"/barbers/{first}", headers=owner, json={"phone": BARBER_PHONE})
    assert again.status_code == 200, "a barber's own number, saved again"


def test_the_owner_gives_changes_and_takes_away_a_barbers_phone(client, owner, texts):
    barber = new_barber(client, owner).json()
    assert barber["phone"] is None

    given = client.patch(f"/barbers/{barber['id']}", headers=owner, json={"phone": BARBER_PHONE})
    assert given.json()["phone"] == BARBER_PHONE and given.json()["active"] is True
    assert role_of(client, sign_in(client, texts, phone=BARBER_PHONE)) == "barber"

    taken = client.patch(f"/barbers/{barber['id']}", headers=owner, json={"phone": ""})
    assert taken.json()["phone"] is None
    assert role_of(client, sign_in(client, texts, phone="0547654321")) == "customer"


def test_leaving_keeps_the_phone_and_the_phone_no_longer_signs_in(client, owner, texts):
    barber = new_barber(client, owner, phone=BARBER_PHONE).json()["id"]

    left = client.patch(f"/barbers/{barber}", headers=owner, json={"active": False})

    assert (left.json()["active"], left.json()["phone"]) == (False, BARBER_PHONE)
    assert ask(client, BARBER_PHONE).status_code == 202
    refused = verify(client, texts.code_for(BARBER_PHONE), BARBER_PHONE)
    assert (refused.status_code, refused.json()["code"]) == (403, "account_inactive")


def test_only_the_owner_gives_a_barber_a_phone(client, owner, customer):
    barber = new_barber(client, owner).json()["id"]

    assert (
        client.patch(f"/barbers/{barber}", headers=customer, json={"phone": BARBER_PHONE}).status_code == 403
    )


def test_a_barber_can_still_be_added_with_a_username_and_a_password(client, owner):
    made = new_barber(client, owner, username="tomer.b", password="long-enough")

    assert made.status_code == 201
    signed = client.post("/auth/token", json={"username": "tomer.b", "password": "long-enough"})
    assert signed.status_code == 200 and signed.json()["role"] == "barber"
