"""A person's name as people type it: letters in any script, with what names hold between them - a space, a
hyphen, an apostrophe or a geresh (ג'ורג', ז׳אן), gershayim, a dot. Never a digit or a symbol. Asked of a
sign-up's full name and of the second person in a booking for two."""

from __future__ import annotations

import unicodedata

from app.errors import DomainError

MARKS = frozenset(" -'.\"\u05f3\u05f4")


def name_or_error(name: str) -> str:
    if not all(ch.isalpha() or ch in MARKS or unicodedata.category(ch).startswith("M") for ch in name):
        raise DomainError(422, "name_not_letters", "a name: letters, with spaces, hyphens and apostrophes only")
    return name
