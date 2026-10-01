from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import current_user, db, settings
from app.errors import DomainError
from app.login_limits import forget_failures, record_failure, seconds_locked
from app.models import User
from app.schemas import AccountIn, LoginIn
from app.security import hash_password, issue_token, verify_password
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
def sign_up(body: AccountIn, session: Session = Depends(db)):
    if session.scalar(select(User).where(User.username == body.username)):
        raise DomainError(409, "username_taken", "that username is taken")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="customer",
        display_name=body.display_name,
    )
    session.add(user)
    session.commit()
    return user_view(user)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_view(user)
