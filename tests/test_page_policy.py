from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import replace
from zoneinfo import ZoneInfo

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
