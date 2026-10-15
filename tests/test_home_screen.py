"""The pictures a phone shows of the shop from its home screen, drawn from its profile picture."""

from __future__ import annotations

import io
import math

from PIL import Image

from app import home_screen


def test_androids_circle_keeps_the_whole_logo_of_the_maskable_icon(tmp_path):
    # A logo that fills its picture to the corners: the hardest one to keep whole.
    picture = tmp_path / "logo.png"
    Image.new("RGB", (400, 300), "black").save(picture)

    icon = Image.open(io.BytesIO(home_screen.icon(picture, "maskable-512"))).convert("L")

    size = icon.width
    # Android shows the middle two thirds of a maskable icon, as a circle.
    radius = size / 3
    centre = size / 2
    outside = [
        (x, y)
        for y in range(size)
        for x in range(size)
        if icon.getpixel((x, y)) < 250 and math.dist((x + 0.5, y + 0.5), (centre, centre)) > radius
    ]
    assert (
        outside == []
    ), f"{len(outside)} pixels of the logo fall outside the circle, the first at {outside[0]}"


def test_the_plain_icons_give_the_logo_most_of_the_square(tmp_path):
    picture = tmp_path / "logo.png"
    Image.new("RGB", (400, 400), "black").save(picture)

    icon = Image.open(io.BytesIO(home_screen.icon(picture, "512"))).convert("L")

    left, top, right, bottom = Image.eval(icon, lambda v: 255 - v).getbbox()
    assert right - left >= 0.8 * icon.width and bottom - top >= 0.8 * icon.height
