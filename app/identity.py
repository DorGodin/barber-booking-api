"""The shop's identity on its own page: the brand, the line under it, and the
ways to reach it - WhatsApp, phone, Instagram, TikTok, Waze - with the shop's
own cover and profile pictures. All from the settings; nothing here is the
shop's but the code.

The header is written into the page by the server, escaped, so the name is
there from the first paint and a value can never become markup.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from app.phones import normalize

IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(jpe?g|png|webp)")
IMAGE_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

# Drawn here, not fetched: the page loads nothing from anywhere else. Simple
# shapes, each with a Hebrew name on its link - the drawing is decoration.
ICONS = {
    "whatsapp": '<path d="M4 20l1.3-3.9A8 8 0 1 1 8 18.7z"/><path d="M9.5 9.5c.5 2 2 3.5 4 4l1-1 2 1"/>',
    "phone": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
    "instagram": '<rect x="4" y="4" width="16" height="16" rx="4"/><circle cx="12" cy="12" r="3.5"/><circle cx="16.5" cy="7.5" r=".6"/>',
    "tiktok": '<path d="M14 4v10.5a3.5 3.5 0 1 1-3.5-3.5"/><path d="M14 4a4.5 4.5 0 0 0 4.5 4.5"/>',
    "waze": '<path d="M12 21s-6-5.3-6-10a6 6 0 0 1 12 0c0 4.7-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>',
}
NAMES = {
    "whatsapp": "וואטסאפ",
    "phone": "התקשרות",
    "instagram": "אינסטגרם",
    "tiktok": "טיקטוק",
    "waze": "ניווט ב־Waze",
}


@dataclass(frozen=True)
class Identity:
    brand: str
    tagline: str
    since: str
    address: str
    links: dict[str, str]
    cover: str | None
    profile: str | None


def _https(name: str, value: str) -> str | None:
    if not value:
        return None
    # A link in a button is followed by whoever taps it; javascript: or a
    # plain http page must never get there through a setting.
    if not value.startswith("https://"):
        raise RuntimeError(f"{name} must be an https:// link, not {value!r}")
    return value


def _phone(name: str, value: str) -> str | None:
    if not value:
        return None
    phone = normalize(value) or (value if re.fullmatch(r"0\d{8,9}", value) else None)
    if phone is None:
        raise RuntimeError(f"{name} must be an Israeli phone number, not {value!r}")
    return "972" + phone[1:]


def _image(name: str, value: str) -> str | None:
    if not value:
        return None
    if not IMAGE.fullmatch(value):
        raise RuntimeError(f"{name} must be a file name like cover.jpg in MEDIA_DIR, not {value!r}")
    return value


def identity_from(env: dict[str, str], brand: str) -> Identity:
    """Read and check the identity settings. A bad one stops the server at
    startup, with its name - not a broken button on the page."""
    whatsapp = _phone("SHOP_WHATSAPP", env.get("SHOP_WHATSAPP", ""))
    phone = _phone("SHOP_PHONE", env.get("SHOP_PHONE", ""))
    links = {
        "whatsapp": f"https://wa.me/{whatsapp}" if whatsapp else None,
        "phone": f"tel:+{phone}" if phone else None,
        "instagram": _https("SHOP_INSTAGRAM_URL", env.get("SHOP_INSTAGRAM_URL", "")),
        "tiktok": _https("SHOP_TIKTOK_URL", env.get("SHOP_TIKTOK_URL", "")),
        "waze": _https("SHOP_WAZE_URL", env.get("SHOP_WAZE_URL", "")),
    }
    return Identity(
        brand=brand,
        tagline=env.get("SHOP_TAGLINE", "HAIR DESIGN"),
        since=env.get("SHOP_SINCE", ""),
        address=env.get("SHOP_ADDRESS", ""),
        links={k: v for k, v in links.items() if v},
        cover=_image("SHOP_COVER_IMAGE", env.get("SHOP_COVER_IMAGE", "")),
        profile=_image("SHOP_PROFILE_IMAGE", env.get("SHOP_PROFILE_IMAGE", "")),
    )


def under_brand(identity: Identity) -> str:
    parts = [f"מאז {identity.since}" if identity.since else "", identity.address]
    return " · ".join(p for p in parts if p)


def header_html(identity: Identity) -> str:
    e = html.escape
    cover = (
        f'<img class="cover" src="/media/{e(identity.cover)}" alt="" data-testid="shop-cover">'
        if identity.cover
        else ""
    )
    profile = (
        f'<img class="profile" src="/media/{e(identity.profile)}" alt="" data-testid="shop-profile">'
        if identity.profile
        else ""
    )
    line = under_brand(identity)
    # The slim bar the brand shrinks to once it has scrolled away. A copy of
    # the h1, so a screen reader never meets it.
    mini = f'<div class="mini" lang="en" dir="ltr" aria-hidden="true" data-testid="mini-brand">{e(identity.brand)}</div>'
    return (
        f'{mini}{cover}{profile}<h1 class="brand" lang="en" dir="ltr" data-testid="shop-brand">{e(identity.brand)}</h1>'
        f'<p class="tagline" lang="en" dir="ltr">{e(identity.tagline)}</p>'
        + (f'<p class="since" data-testid="shop-line">{e(line)}</p>' if line else "")
    )


def contact_html(identity: Identity) -> str:
    """The round buttons to reach the shop, for the foot of the page."""
    e = html.escape
    buttons = "".join(
        f'<a class="action" data-testid="shop-{kind}" href="{e(url)}" aria-label="{e(NAMES[kind])}"'
        f'{"" if kind == "phone" else " target=\"_blank\" rel=\"noopener noreferrer\""}>'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[kind]}</svg></a>'
        for kind, url in identity.links.items()
    )
    return f'<nav class="actions" aria-label="יצירת קשר עם המספרה">{buttons}</nav>' if buttons else ""


def media_file(directory: Path, identity: Identity, name: str) -> Path | None:
    """Only the images the settings name - never any other file in the folder,
    never a path out of it."""
    if name not in {identity.cover, identity.profile} - {None}:
        return None
    path = directory / name
    return path if path.is_file() else None
