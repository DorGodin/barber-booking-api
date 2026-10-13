"""The page's letters are the shop's own: two font files it serves itself, and a policy that lets
the page load them and nothing from anywhere else."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("name", ["rubik-hebrew.woff2", "rubik-latin.woff2"])
def test_the_two_font_files_are_served_as_fonts_and_kept_by_the_browser(client, name):
    served = client.get(f"/fonts/{name}")

    assert served.status_code == 200
    assert served.headers["content-type"] == "font/woff2" and served.content[:4] == b"wOF2"
    assert "max-age" in served.headers["cache-control"]


@pytest.mark.parametrize("name", ["rubik-bold.woff2", "sw.js", "..%2Fsw.js", "..%2Findex.html", "x"])
def test_nothing_else_is_served_from_the_fonts_folder(client, name):
    refused = client.get(f"/fonts/{name}")

    assert refused.status_code == 404


@pytest.mark.parametrize("path", ["/", "/privacy", "/accessibility"])
def test_every_page_uses_the_shops_letters_and_asks_no_other_site_for_them(client, path):
    page = client.get(path)

    assert 'font-family:"Rubik"' in page.text and '"/fonts/rubik-hebrew.woff2"' in page.text
    assert "fonts.googleapis" not in page.text and "fonts.gstatic" not in page.text
    assert "font-src 'self'" in page.headers["content-security-policy"]
