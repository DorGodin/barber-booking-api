from __future__ import annotations

import base64
import hashlib
import re


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
