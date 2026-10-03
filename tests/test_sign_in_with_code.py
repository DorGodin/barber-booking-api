"""Signing in with a code sent by SMS: the phone is who you are, the code is the
password, and the first sign-in opens the account."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.models import OtpCode, User
from app.phones import normalize

PHONE = "0501234567"


def ask(client, phone=PHONE, name="דנה כהן", address=None):
    headers = {"X-Forwarded-For": address} if address else {}
    return client.post("/auth/otp", json={"full_name": name, "phone": phone}, headers=headers)


def verify(client, code, phone=PHONE):
    return client.post("/auth/otp/verify", json={"phone": phone, "code": code})


def sign_in(client, texts, phone=PHONE, name="דנה כהן") -> dict:
    assert ask(client, phone, name).status_code == 202
    resp = verify(client, texts.code_for(normalize(phone)), phone)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10_000:04d}"


def age_codes(client, minutes: int, phone=PHONE) -> None:
    """As if the codes for this phone were sent that many minutes ago."""
    with client.app.state.sessionmaker() as session:
        for record in session.query(OtpCode).filter(OtpCode.phone == phone):
            record.created_at -= timedelta(minutes=minutes)
            record.expires_at -= timedelta(minutes=minutes)
        session.commit()


def test_the_first_sign_in_opens_an_account_under_the_name_given(client, texts):
    asked = ask(client)

    assert asked.status_code == 202
    assert asked.json() == {"phone_last4": "4567", "expires_in_seconds": 300, "resend_after_seconds": 60}
    [(to, text)] = texts.messages
    assert to == PHONE and "TomGoldin" in text and texts.code_for(PHONE) in text
    signed_in = verify(client, texts.code_for(PHONE))
    assert signed_in.status_code == 200 and signed_in.json()["role"] == "customer"
    me = client.get("/me", headers={"Authorization": f"Bearer {signed_in.json()['access_token']}"}).json()
    assert me["display_name"] == "דנה כהן" and me["role"] == "customer"


def test_the_code_is_never_in_an_answer_or_in_the_database(client, texts):
    asked = ask(client)
    code = texts.code_for(PHONE)

    assert code not in asked.text
    with client.app.state.sessionmaker() as session:
        stored = session.query(OtpCode).one()
        assert code not in stored.code_hash and len(stored.code_hash) == 64


def test_the_same_phone_comes_back_to_the_same_account_however_it_is_written(client, texts):
    first = client.get("/me", headers=sign_in(client, texts, "0501234567")).json()
    age_codes(client, 2)

    again = client.get("/me", headers=sign_in(client, texts, "+972 50-123-4567", name="שם אחר")).json()

    assert again["id"] == first["id"]
    assert again["display_name"] == "דנה כהן", "the name only names a new account"


def test_a_wrong_code_counts_down_and_the_third_uses_the_code_up(client, texts):
    ask(client)
    code = texts.code_for(PHONE)

    lefts = [verify(client, wrong(code)).json()["attempts_left"] for _ in range(3)]
    after = verify(client, code)

    assert lefts == [2, 1, 0]
    assert after.status_code == 409 and after.json()["code"] == "code_used_up"


def test_an_expired_code_does_not_sign_in(client, texts):
    ask(client)
    age_codes(client, 6)

    late = verify(client, texts.code_for(PHONE))

    assert late.status_code == 409 and late.json()["code"] == "code_expired"


def test_a_code_signs_in_once(client, texts):
    ask(client)
    code = texts.code_for(PHONE)

    assert verify(client, code).status_code == 200
    again = verify(client, code)

    assert again.status_code == 409 and again.json()["code"] == "no_code"


def test_a_new_code_waits_a_minute_and_replaces_the_old_one(client, texts):
    ask(client)
    old = texts.code_for(PHONE)

    too_soon = ask(client)
    age_codes(client, 2)
    assert ask(client).status_code == 202
    new = texts.code_for(PHONE)

    assert too_soon.status_code == 429 and too_soon.json()["code"] == "code_too_soon"
    assert 0 < too_soon.json()["retry_after_seconds"] <= 60
    if new != old:
        assert verify(client, old).json()["code"] == "wrong_code", "the replaced code still worked"
    assert verify(client, new).status_code == 200


def test_one_phone_gets_only_so_many_codes_an_hour(client, texts):
    codes = []
    for _ in range(6):
        codes.append(ask(client).status_code)
        age_codes(client, 2)

    assert codes[:5] == [202] * 5
    assert codes[5] == 429


def test_one_address_asks_for_only_so_many_codes_an_hour(client, texts):
    phones = [f"05{n:08d}" for n in range(21)]

    answers = [ask(client, phone, address="203.0.113.7") for phone in phones]

    assert [a.status_code for a in answers[:20]] == [202] * 20
    assert answers[20].status_code == 429 and answers[20].json()["code"] == "too_many_codes"


@pytest.mark.parametrize("phone", ["12345", "0721234567", "05012345678", "abc"])
def test_only_a_mobile_number_gets_a_code(client, texts, phone):
    refused = ask(client, phone)

    assert refused.status_code == 422 and refused.json()["code"] == "bad_phone"
    assert texts.messages == []


@pytest.mark.parametrize("name", ["", " ", "א", "א" * 81])
def test_a_new_account_needs_a_real_full_name(client, texts, name):
    assert ask(client, name=name).status_code == 422


def test_a_code_the_provider_could_not_send_does_not_hold_the_phone_back(client, texts):
    texts.failing = True
    failed = ask(client)
    texts.failing = False

    assert failed.status_code == 502 and failed.json()["code"] == "sms_failed"
    assert ask(client).status_code == 202, "a code that never went out still blocked the next one"


def test_a_barber_who_left_is_refused_after_the_right_code(client, texts, owner):
    barber_id = client.post(
        "/barbers", headers=owner, json={"username": "b-left", "password": "long-enough", "display_name": "B"}
    ).json()["id"]
    with client.app.state.sessionmaker() as session:
        session.execute(update(User).where(User.id == barber_id).values(phone="0529876543", active=False))
        session.commit()
    ask(client, "0529876543")

    refused = verify(client, texts.code_for("0529876543"), "0529876543")

    assert refused.status_code == 403 and refused.json()["code"] == "account_inactive"


def test_the_wrong_tries_are_kept_even_though_each_request_fails(client, texts):
    ask(client)
    verify(client, wrong(texts.code_for(PHONE)))

    with client.app.state.sessionmaker() as session:
        assert session.query(OtpCode).one().attempts == 1, "a refused try was rolled back with its request"


def test_codes_older_than_a_day_are_cleared(client, texts):
    ask(client, "0500000001")
    with client.app.state.sessionmaker() as session:
        session.execute(update(OtpCode).values(created_at=datetime.now(UTC) - timedelta(days=2)))
        session.commit()

    ask(client, "0500000002")

    with client.app.state.sessionmaker() as session:
        assert [r.phone for r in session.query(OtpCode)] == ["0500000002"]
