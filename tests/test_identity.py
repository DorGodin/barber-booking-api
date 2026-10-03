"""The shop's identity on its page: the brand, the line under it, the buttons to
reach it and its pictures - all from settings, all checked, all escaped."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.identity import identity_from
from app.main import create_app
from tests.conftest import TZ, SentTexts

FULL = {
    "SHOP_SINCE": "1991",
    "SHOP_ADDRESS": "שביט 8, נס ציונה",
    "SHOP_WHATSAPP": "050-123-4567",
    "SHOP_PHONE": "0501234567",
    "SHOP_INSTAGRAM_URL": "https://www.instagram.com/example",
    "SHOP_TIKTOK_URL": "https://www.tiktok.com/@example",
    "SHOP_WAZE_URL": "https://waze.com/ul?q=example",
    "SHOP_COVER_IMAGE": "cover.png",
    "SHOP_PROFILE_IMAGE": "profile.png",
}


def shop(tmp_path: Path, monkeypatch, env: dict, brand: str = "TomGoldin") -> TestClient:
    for role in ("owner", "barber", "customer"):
        monkeypatch.setenv(f"SEED_{role.upper()}_PASSWORD", secrets.token_urlsafe(12))
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    (media / "cover.png").write_bytes(b"\x89PNG cover")
    (media / "profile.png").write_bytes(b"\x89PNG profile")
    (media / "secret.txt").write_text("not a picture")
    config = Settings(
        database_url=f"sqlite:///{tmp_path / 'shop.db'}",
        secret_key=secrets.token_hex(32),
        shop_tz=TZ,
        booking_window_days=60,
        cancel_cutoff_hours=24,
        token_hours=1,
        shop_brand=brand,
        identity=identity_from(env, brand),
        media_dir=str(media),
    )
    return TestClient(create_app(config, sms=SentTexts()))


def test_the_page_carries_the_brand_the_line_and_a_named_button_for_each_way_to_reach_the_shop(
    tmp_path, monkeypatch
):
    with shop(tmp_path, monkeypatch, FULL) as client:
        page = client.get("/").text

    assert "<title>TomGoldin Hair Design</title>" in page
    assert 'data-testid="shop-brand">TomGoldin</h1>' in page
    assert "מאז 1991 · שביט 8, נס ציונה" in page
    for href, name in (
        ("https://wa.me/972501234567", "וואטסאפ"),
        ("tel:+972501234567", "התקשרות"),
        ("https://www.instagram.com/example", "אינסטגרם"),
        ("https://www.tiktok.com/@example", "טיקטוק"),
        ("https://waze.com/ul?q=example", "ניווט ב־Waze"),
    ):
        assert f'href="{href}" aria-label="{name}"' in page
    assert "{{" not in page, "a placeholder was left on the page"


def test_a_way_to_reach_the_shop_that_is_not_set_has_no_button(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, {"SHOP_PHONE": "0501234567"}) as client:
        page = client.get("/").text

    assert 'data-testid="shop-phone"' in page
    for kind in ("whatsapp", "instagram", "tiktok", "waze"):
        assert f'data-testid="shop-{kind}"' not in page
    assert 'data-testid="shop-cover"' not in page


def test_a_brand_that_looks_like_markup_is_written_as_text(tmp_path, monkeypatch):
    with shop(
        tmp_path, monkeypatch, {"SHOP_ADDRESS": '<img src=x onerror="alert(1)">'}, brand="<script>x</script>"
    ) as client:
        page = client.get("/").text

    assert "<script>x</script>" not in page
    assert "&lt;script&gt;x&lt;/script&gt;" in page
    assert '<img src=x onerror="alert(1)">' not in page


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SHOP_INSTAGRAM_URL", "javascript:alert(1)"),
        ("SHOP_TIKTOK_URL", "http://www.tiktok.com/@example"),
        ("SHOP_WAZE_URL", "waze.com/ul"),
        ("SHOP_WHATSAPP", "12345"),
        ("SHOP_PHONE", "not a phone"),
        ("SHOP_COVER_IMAGE", "../barber.db"),
        ("SHOP_PROFILE_IMAGE", "profile.svg"),
    ],
)
def test_a_bad_setting_stops_the_server_with_its_name(name, value):
    with pytest.raises(RuntimeError, match=name):
        identity_from({name: value}, "TomGoldin")


def test_only_the_two_pictures_named_in_the_settings_are_served(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, FULL) as client:
        cover = client.get("/media/cover.png")
        others = [
            client.get(f"/media/{name}").status_code for name in ("secret.txt", "shop.db", "..%2Fshop.db")
        ]

    assert cover.status_code == 200 and cover.headers["content-type"] == "image/png"
    assert cover.content == b"\x89PNG cover"
    assert others == [404, 404, 404]


def test_a_picture_named_but_missing_is_not_found_and_the_page_still_loads(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, {**FULL, "SHOP_COVER_IMAGE": "gone.png"}) as client:
        assert client.get("/media/gone.png").status_code == 404
        assert client.get("/").status_code == 200


def test_the_page_may_show_the_shops_own_pictures_and_no_one_elses(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, FULL) as client:
        policy = client.get("/").headers["content-security-policy"]

    assert "img-src 'self' data:;" in policy


def test_the_shop_endpoint_tells_a_client_how_to_reach_the_shop(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, FULL) as client:
        info = client.get("/shop").json()

    assert info["brand"] == "TomGoldin"
    assert info["under_brand"] == "מאז 1991 · שביט 8, נס ציונה"
    assert info["links"]["phone"] == "tel:+972501234567"


def test_the_slim_bar_carries_the_brand_and_is_hidden_from_a_screen_reader(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, {}, brand="Tom & Goldin") as client:
        page = client.get("/").text

    assert 'aria-hidden="true" data-testid="mini-brand">Tom &amp; Goldin</div>' in page
    assert page.count('data-testid="mini-brand"') == 1


def test_the_tests_default_settings_still_build_a_page(client):
    page = client.get("/").text

    assert 'data-testid="shop-brand">TomGoldin</h1>' in page


def test_the_privacy_policy_is_a_page_of_its_own_with_the_shops_details_escaped(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, {"SHOP_ADDRESS": "<b>שביט 8</b>"}, brand="TomGoldin") as client:
        page = client.get("/privacy")
        booking_page = client.get("/").text

    assert page.status_code == 200
    assert "מדיניות פרטיות" in page.text and "חוק הגנת הפרטיות" in page.text
    assert "<b>שביט 8</b>" not in page.text and "&lt;b&gt;שביט 8&lt;/b&gt;" in page.text
    assert "{{" not in page.text, "a placeholder was left on the privacy page"
    assert "script-src" in page.headers["content-security-policy"]
    assert 'href="/privacy"' in booking_page and 'href="/accessibility"' in booking_page


def test_the_ways_to_reach_the_shop_stand_at_the_foot_of_the_page(tmp_path, monkeypatch):
    with shop(tmp_path, monkeypatch, FULL) as client:
        page = client.get("/").text

    footer = page[page.index("<footer>") :]
    assert 'data-testid="shop-whatsapp"' in footer
    assert footer.index('data-testid="shop-whatsapp"') < footer.index('data-testid="privacy-link"')
    assert 'data-testid="shop-whatsapp"' not in page[: page.index("<footer>")]
