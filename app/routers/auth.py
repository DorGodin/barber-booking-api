from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, settings
from app.errors import DomainError
from app.login_limits import forget_failures, record_failure, seconds_locked
from app.models import RevokedToken, Signup, User
from app.schemas import AccountIn, LoginIn
from app.security import hash_password, issue_token, read_token, verify_password
from app.views import user_view

router = APIRouter(tags=["auth"])


@router.post("/auth/token")
def login(
    body: LoginIn, request: Request, session: Session = Depends(db), config: Settings = Depends(settings)
):
    # The client's address as the server that faces it saw it. Behind a proxy
    # uvicorn takes it from X-Forwarded-For, but only from the addresses in
    # FORWARDED_ALLOW_IPS - a header anyone can send is trusted from nowhere else.
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(UTC)
    wait = seconds_locked(session, config, body.username, ip, now)
    if wait:
        raise DomainError(
            429,
            "too_many_attempts",
            "too many failed sign-ins; try again later",
            extra={"retry_after_seconds": wait},
            headers={"Retry-After": str(wait)},
        )
    user = session.scalar(select(User).where(User.username == body.username))
    if not verify_password(body.password, user.password_hash if user else None):
        record_failure(session, config, body.username, ip, now)
        # The same answer for an unknown user and a wrong password.
        raise DomainError(401, "bad_credentials", "wrong username or password")
    forget_failures(session, body.username, ip)
    token = issue_token(user.id, user.role, config.secret_key, config.token_hours)
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@router.post("/customers", status_code=201)
def sign_up(
    body: AccountIn, request: Request, session: Session = Depends(db), config: Settings = Depends(settings)
):
    # Each account may hold only a couple of bookings, so the way around that is
    # more accounts. One address may make only so many an hour. Only accounts
    # actually made count: a username already taken or a bad password does not.
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(UTC)
    window = timedelta(minutes=config.signup_window_minutes)
    password_hash = hash_password(body.password)
    with write_lock(session):
        recent = session.scalars(
            select(Signup.at).where(Signup.ip == ip, Signup.at > now - window).order_by(Signup.at)
        ).all()
        if len(recent) >= config.signups_per_address:
            wait = math.ceil(
                (recent[len(recent) - config.signups_per_address] + window - now).total_seconds()
            )
            raise DomainError(
                429,
                "too_many_signups",
                "too many accounts from this address; try again later",
                extra={"retry_after_seconds": wait},
                headers={"Retry-After": str(wait)},
            )
        if session.scalar(select(func.count()).select_from(User).where(User.username == body.username)):
            raise DomainError(409, "username_taken", "that username is taken")
        user = User(
            username=body.username,
            password_hash=password_hash,
            role="customer",
            display_name=body.display_name,
        )
        session.add(user)
        session.execute(delete(Signup).where(Signup.at <= now - window))
        session.add(Signup(ip=ip, at=now))
    return user_view(user)


@router.post("/auth/logout", status_code=204)
def logout(
    authorization: str = Header(),
    _: User = Depends(current_user),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """Ends this sign-in on the server, not only in the browser: a token copied
    before the sign-out stops working at once instead of in twelve hours. Other
    sign-ins of the same person - another phone - are untouched."""
    claims = read_token(authorization.removeprefix("Bearer "), config.secret_key)
    now = datetime.now(UTC)
    with write_lock(session):
        session.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
        session.merge(RevokedToken(jti=claims["jti"], expires_at=datetime.fromtimestamp(claims["exp"], UTC)))


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_view(user)
