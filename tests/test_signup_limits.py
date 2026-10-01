from __future__ import annotations

import secrets
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def strict(client):
    """A shop with the real limit: five accounts an hour from one address. The
    ordinary test client raises it, because its tests make many customers."""
    config = replace(client.app.state.settings, signups_per_address=5)
    with TestClient(create_app(config)) as strict_client:
        yield strict_client


def sign_up(client, username: str | None = None):
    username = username or f"c-{secrets.token_hex(4)}"
    return client.post(
        "/customers", json={"username": username, "password": "long-enough", "display_name": "C"}
    )


def test_five_accounts_from_one_address_and_the_sixth_is_refused(strict):
    for _ in range(5):
        assert sign_up(strict).status_code == 201

    refused = sign_up(strict)

    assert refused.status_code == 429
    assert refused.json()["code"] == "too_many_signups"
    assert 0 < int(refused.headers["Retry-After"]) <= 60 * 60


def test_a_username_already_taken_does_not_use_up_the_address(strict):
    taken = f"c-{secrets.token_hex(4)}"
    assert sign_up(strict, taken).status_code == 201
    for _ in range(5):
        assert sign_up(strict, taken).status_code == 409

    for _ in range(4):
        assert sign_up(strict).status_code == 201
