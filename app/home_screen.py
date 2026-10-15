"""What a phone shows of the shop once it is on the home screen: the icons, and an iPhone's splash -
all drawn here from the shop's own profile picture, so a shop sets one picture and nothing else.

An iPhone takes its splash only as a picture of the exact screen it opens on (apple-touch-startup-image),
one per size; Android draws its own from the manifest's colour and its maskable icon. Drawn when first
asked for and kept in memory: a few pictures, the same for every visitor."""

from __future__ import annotations

import io
import re
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "static" / "fonts"
BLACK, WHITE, MUTED, FOOT = (17, 17, 17), (255, 255, 255), (189, 183, 172), (141, 135, 124)

# The iPhones a splash is drawn for, by their screens in points and how many pixels to a point.
SCREENS = [
    (440, 956, 3),
    (430, 932, 3),
    (428, 926, 3),
    (414, 896, 3),
    (414, 896, 2),
    (414, 736, 3),
    (402, 874, 3),
    (393, 852, 3),
    (390, 844, 3),
    (375, 812, 3),
    (375, 667, 2),
]
# Android shows the middle two thirds of a maskable icon, as a circle: a logo of under half its width fits whole.
ICONS = {"180": (180, 0.08), "192": (192, 0.08), "512": (512, 0.08), "maskable-512": (512, 0.27)}


def splash_links() -> str:
    """The <link>s an iPhone chooses its splash from, one for each screen it may open on."""
    return "".join(
        f'<link rel="apple-touch-startup-image" href="/splash/{w * r}x{h * r}.png" media="(device-width: {w}px) '
        f'and (device-height: {h}px) and (-webkit-device-pixel-ratio: {r}) and (orientation: portrait)">'
        for w, h, r in SCREENS
    )


def splash_sizes() -> set[str]:
    return {f"{w * r}x{h * r}" for w, h, r in SCREENS}


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def _logo(picture: Path) -> Image.Image:
    with Image.open(picture) as raw:
        return raw.convert("RGBA")


def _on_white(logo: Image.Image, size: int, margin: float) -> Image.Image:
    """The logo whole, centred on a white square - a maskable icon keeps it inside the circle Android cuts."""
    canvas = Image.new("RGB", (size, size), WHITE)
    room = round(size * (1 - 2 * margin))
    # Up or down to fill the room - a small picture is enlarged too, never left small in the square.
    ratio = min(room / logo.width, room / logo.height)
    fitted = logo.resize(
        (max(1, round(logo.width * ratio)), max(1, round(logo.height * ratio))), Image.LANCZOS
    )
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2), fitted)
    return canvas


def _font(weight: int, size: int, hebrew: bool = False) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / ("rubik-hebrew.woff2" if hebrew else "rubik-latin.woff2")), size)
    font.set_variation_by_axes([weight])
    return font


def _visual(text: str) -> str:
    """Hebrew in the order it is drawn, left to right, for a drawing library that does not reorder it:
    the line reversed, and every run of digits or Latin letters put back the right way round."""
    return re.sub(r"[0-9A-Za-z.:/\-]+", lambda m: m.group(0)[::-1], text[::-1])


def _centred(draw: ImageDraw.ImageDraw, width: int, y: int, text: str, font, fill, spacing: int = 0) -> None:
    if spacing:
        total = sum(draw.textlength(c, font=font) for c in text) + spacing * (len(text) - 1)
        x = (width - total) / 2
        for c in text:
            draw.text((x, y), c, font=font, fill=fill)
            x += draw.textlength(c, font=font) + spacing
    else:
        draw.text(((width - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def _mixed(draw: ImageDraw.ImageDraw, width: int, y: int, text: str, hebrew, latin, fill) -> None:
    """A line in both scripts, centred: the Hebrew file holds only Hebrew, so each run takes its own font."""
    runs = [
        (run, hebrew if "\u0590" <= run[0] <= "\u05ff" else latin)
        for run in re.findall(r"[\u0590-\u05ff]+|[^\u0590-\u05ff]+", text)
    ]
    x = (width - sum(draw.textlength(run, font=font) for run, font in runs)) / 2
    for run, font in runs:
        draw.text((x, y), run, font=font, fill=fill)
        x += draw.textlength(run, font=font)


@cache
def icon(picture: Path, name: str) -> bytes:
    size, margin = ICONS[name]
    return _png(_on_white(_logo(picture), size, margin))


@cache
def splash(picture: Path, size: str, brand: str, tagline: str, address: str) -> bytes:
    """The shop's black, its logo on a rounded white square, its name and line, and its address at the foot."""
    width, height = (int(n) for n in size.split("x"))
    scale = width / 390
    canvas = Image.new("RGB", (width, height), BLACK)
    draw = ImageDraw.Draw(canvas)
    tile = round(120 * scale)
    square = Image.new("L", (tile, tile), 0)
    ImageDraw.Draw(square).rounded_rectangle((0, 0, tile - 1, tile - 1), radius=round(28 * scale), fill=255)
    top = round(height / 2 - 100 * scale)
    canvas.paste(_on_white(_logo(picture), tile, 0.05), ((width - tile) // 2, top), square)
    y = top + tile + round(18 * scale)
    _centred(draw, width, y, brand, _font(800, round(30 * scale)), WHITE)
    y += round(42 * scale)
    _centred(draw, width, y, tagline.upper(), _font(500, round(12 * scale)), MUTED, spacing=round(4 * scale))
    if address:
        size = round(13 * scale)
        _mixed(
            draw,
            width,
            height - round(62 * scale),
            _visual(address),
            _font(400, size, True),
            _font(400, size),
            FOOT,
        )
    return _png(canvas)
