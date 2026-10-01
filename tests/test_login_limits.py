from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.login_limits import record_failure, seconds_locked


def sign_in(client, username: str, password: str):
    return client.post("/auth/token", json={"username": username, "password": password})


def test_five_wrong_passwords_lock_the_account_even_against_the_right_one(client, passwords):
    for _ in range(5):
        assert sign_in(client, "customer", "wrong-password").status_code == 401

    refused = sign_in(client, "customer", passwords["customer"])

    assert refused.status_code == 429
    assert refused.json()["code"] == "too_many_attempts"
    assert 0 < int(refused.headers["Retry-After"]) <= 15 * 60
    assert refused.json()["retry_after_seconds"] == int(refused.headers["Retry-After"])


def test_a_locked_account_does_not_lock_another(client, passwords):
    for _ in range(5):
        sign_in(client, "customer", "wrong-password")

    assert sign_in(client, "owner", passwords["owner"]).status_code == 200


def test_a_right_password_before_the_limit_clears_the_count(client, passwords):
    for _ in range(4):
        sign_in(client, "customer", "wrong-password")
    assert sign_in(client, "customer", passwords["customer"]).status_code == 200

    for _ in range(4):
        sign_in(client, "customer", "wrong-password")

    assert sign_in(client, "customer", passwords["customer"]).status_code == 200


def test_an_unknown_username_is_counted_and_refused_like_a_real_one(client):
    for _ in range(5):
        assert sign_in(client, "nobody-here", "whatever").status_code == 401

    assert sign_in(client, "nobody-here", "whatever").status_code == 429


def test_one_password_tried_across_many_usernames_locks_the_address(client, passwords):
    for i in range(20):
        sign_in(client, f"guess-{i}", "summer2026")

    assert sign_in(client, "owner", passwords["owner"]).status_code == 429


def test_the_lock_lifts_when_the_failures_age_out_of_the_window(client):
    config = client.app.state.settings
    start = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    with client.app.state.sessionmaker() as session:
        for minute in range(5):
            record_failure(session, config, "dana", "10.0.0.1", start + timedelta(minutes=minute))
        now = start + timedelta(minutes=5)

        assert (
            seconds_locked(session, config, "dana", "10.0.0.1", now) == 10 * 60
        ), "until the first failure is 15 minutes old"
        assert (
            seconds_locked(session, config, "dana", "10.0.0.1", start + timedelta(minutes=15, seconds=1)) == 0
        )
        assert (
            seconds_locked(session, config, "dana", "10.0.0.2", now) == 0
        ), "the same account, from another address"
        assert (
            seconds_locked(session, config, "yael", "10.0.0.2", now) == 0
        ), "another account from another address"
