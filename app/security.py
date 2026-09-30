"""Passwords and tokens. The standard library's scrypt for the first, PyJWT for the second."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

_N, _R, _P = 2**14, 8, 1
# Verified against when the username does not exist, so an unknown user takes
# as long to refuse as a wrong password. Otherwise response time tells an
# attacker which usernames are real.
_DUMMY = None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    global _DUMMY
    if stored is None:
        _DUMMY = _DUMMY or hash_password(secrets.token_hex(8))
        stored, real = _DUMMY, False
    else:
        real = True
    _, salt_hex, digest_hex = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P)
    return real and hmac.compare_digest(candidate.hex(), digest_hex)


def issue_token(user_id: str, role: str, secret: str, hours: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": user_id, "role": role, "iat": now, "exp": now + timedelta(hours=hours)}, secret, "HS256"
    )


def read_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "exp"]})
    except jwt.PyJWTError:
        return None
