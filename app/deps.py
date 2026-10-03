from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import DomainError
from app.models import RevokedToken, User
from app.security import read_token
from app.sms import SmsSender


def settings(request: Request) -> Settings:
    return request.app.state.settings


def sms(request: Request) -> SmsSender:
    return request.app.state.sms


def db(request: Request) -> Iterator[Session]:
    session = request.app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


def current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
) -> User:
    # One answer for every way a credential can be wrong. Telling "expired"
    # from "forged" from "missing" helps nobody but an attacker.
    unauthorized = DomainError(401, "unauthorized", "missing or invalid bearer token")
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized
    claims = read_token(authorization.removeprefix("Bearer "), config.secret_key)
    if claims is None or session.get(RevokedToken, claims["jti"]) is not None:
        raise unauthorized
    user = session.get(User, claims["sub"])
    # A barber who left stops being signed in at once, not when the token expires.
    if user is None or not user.active:
        raise unauthorized
    return user


def require(*roles: str):
    def _check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise DomainError(403, "forbidden", f"requires role: {' or '.join(roles)}")
        return user

    return _check
