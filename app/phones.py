"""An Israeli mobile number, in the one form it is stored and compared in."""

from __future__ import annotations

import re

MOBILE = re.compile(r"05\d{8}")


def normalize(raw: str) -> str | None:
    """0501234567 - whatever the person typed around it: spaces, dashes,
    brackets, or the country code. None when it is not a mobile number, which
    is the only kind an SMS reaches."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if digits.startswith("+972"):
        digits = "0" + digits[4:]
    elif digits.startswith("972") and len(digits) == 12:
        digits = "0" + digits[3:]
    return digits if MOBILE.fullmatch(digits) else None
