"""Real pictures, a pixel each, made by Pillow: the shop decodes what it is sent, so a file's first bytes
alone are not a picture any more."""

from __future__ import annotations

import io

from PIL import Image


def _made(kind: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1, 1), (200, 160, 60)).save(out, kind)
    return out.getvalue()


JPEG = _made("JPEG")
PNG = _made("PNG")
WEBP = _made("WEBP")
