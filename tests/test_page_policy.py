from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def directives(header: str) -> dict[str, list[str]]:
    return {name: values for name, *values in (part.split() for part in header.split(";") if part.strip())}


def sha256(body: str) -> str:
    return f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"


def test_the_page_allows_exactly_its_own_script_and_style_and_nothing_inline_besides(client):
    page = client.get("/")
    policy = directives(page.headers["Content-Security-Policy"])

    (script,) = re.findall(r"<script>(.*?)</script>", page.text, re.S)
    (style,) = re.findall(r"<style>(.*?)</style>", page.text, re.S)
    assert policy["script-src"] == [sha256(script)]
    assert policy["style-src"] == [sha256(style)]
    assert policy["default-src"] == ["'none'"]
    assert policy["connect-src"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert "'unsafe-inline'" not in page.headers["Content-Security-Policy"]


def test_an_api_answer_is_never_a_page(client):
    assert directives(client.get("/shop").headers["Content-Security-Policy"]) == {
        "default-src": ["'none'"],
        "frame-ancestors": ["'none'"],
    }


def test_the_accessibility_statement_names_the_shops_own_contact_as_text(client):
    page = client.get("/accessibility")
    policy = directives(page.headers["Content-Security-Policy"])

    assert page.status_code == 200
    assert policy["script-src"] == ["'none'"], "the statement runs no script at all"
    assert "accessibility@example.com" in page.text
    assert "{{" not in page.text, "every placeholder was filled"


def test_the_accessibility_contact_is_written_as_text_never_as_markup(tmp_path, monkeypatch, passwords):
    for role, password in passwords.items():
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", password)
    base = Settings(
        database_url=f"sqlite:///{tmp_path / 'statement.db'}",
        secret_key=secrets.token_hex(32),
        shop_tz=ZoneInfo("Asia/Jerusalem"),
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
    )
    config = replace(base, accessibility_contact_name="<script>alert(1)</script>")

    with TestClient(create_app(config)) as client:
        page = client.get("/accessibility").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_apis_own_map_is_served_only_when_asked_for(client, tmp_path, monkeypatch, passwords):
    maps = ("/docs", "/redoc", "/openapi.json")
    assert [client.get(path).status_code for path in maps] == [404, 404, 404]

    for role, password in passwords.items():
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", password)
    config = replace(
        client.app.state.settings, database_url=f"sqlite:///{tmp_path / 'docs.db'}", api_docs=True
    )
    with TestClient(create_app(config)) as developer:
        assert [developer.get(path).status_code for path in maps] == [200, 200, 200]


def test_the_page_for_no_connection_is_the_shops_and_runs_only_its_own_script(client):
    page = client.get("/offline.html")

    assert page.status_code == 200
    assert "TomGoldin" in page.text and "אין חיבור" in page.text
    assert "'unsafe-inline'" not in page.headers["content-security-policy"]


def test_the_worker_keeps_the_page_for_no_connection_and_its_letters(client):
    worker = client.get("/sw.js").text

    for kept in ("/offline.html", "/fonts/rubik-hebrew.woff2", "/fonts/rubik-latin.woff2"):
        assert f'"{kept}"' in worker
        assert client.get(kept).status_code == 200


def test_the_worker_may_fetch_from_this_server_and_nowhere_else(client):
    policy = client.get("/sw.js").headers["content-security-policy"]

    assert "connect-src 'self'" in policy
    assert "default-src 'none'" in policy and "*" not in policy


def test_the_poster_holds_a_code_for_the_shop_and_runs_no_script(client):
    page = client.get("/poster")

    assert page.status_code == 200
    assert "<svg" in page.text and "סרקו וקבעו תור" in page.text
    assert "http://testserver/" in page.text
    assert "script-src 'none'" in page.headers["content-security-policy"]


def test_the_poster_sends_people_to_the_shops_own_address_once_it_has_one(
    client, tmp_path, monkeypatch, passwords
):
    for role, password in passwords.items():
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", password)
    config = replace(
        client.app.state.settings,
        database_url=f"sqlite:///{tmp_path / 'poster.db'}",
        shop_url="https://shop.example/",
    )
    with TestClient(create_app(config)) as shop:
        assert "https://shop.example/" in shop.get("/poster").text


def test_the_shops_address_must_be_https(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 32)
    monkeypatch.setenv("SMS_URL", "console")
    for wrong in ("http://shop.example/", "shop.example", "https://"):
        monkeypatch.setenv("SHOP_URL", wrong)
        with pytest.raises(RuntimeError, match="SHOP_URL"):
            Settings.from_env()
