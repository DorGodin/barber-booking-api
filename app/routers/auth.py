from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, settings, sms
from app.errors import DomainError
from app.login_limits import forget_failures, record_failure, seconds_locked
from app.models import OtpCode, RevokedToken, Signup, User
from app.phones import normalize
from app.schemas import AccountIn, CodeRequestIn, CodeVerifyIn, LoginIn
from app.security import hash_password, issue_token, read_token, verify_password
from app.sms import SmsFailed, SmsSender
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
    # Told only to someone who knew the password - it confirms the account.
    if not user.active:
        raise DomainError(403, "account_inactive", "this account is no longer active")
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


def _phone_or_error(raw: str) -> str:
    phone = normalize(raw)
    if phone is None:
        raise DomainError(422, "bad_phone", "a mobile number: 05 and eight more digits")
    return phone


def _code_hash(secret: str, phone: str, code: str) -> str:
    # Keyed, so a copy of the database alone does not reveal a live code -
    # four digits would fall to a plain hash at once.
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _wait_until(oldest: datetime, window: timedelta, now: datetime) -> int:
    return max(1, math.ceil((oldest + window - now).total_seconds()))


@router.post("/auth/otp", status_code=202)
def request_code(
    body: CodeRequestIn,
    request: Request,
    session: Session = Depends(db),
    config: Settings = Depends(settings),
    sender: SmsSender = Depends(sms),
):
    """Send a sign-in code to a mobile. Every SMS costs the shop money and
    reaches a real person's phone, so a phone gets a new code at most once a
    minute and a few an hour, and one address only so many codes an hour."""
    phone = _phone_or_error(body.phone)
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(UTC)
    hour = timedelta(hours=1)
    code = f"{secrets.randbelow(10_000):04d}"
    with write_lock(session):
        by_phone = session.scalars(
            select(OtpCode.created_at)
            .where(OtpCode.phone == phone, OtpCode.created_at > now - hour)
            .order_by(OtpCode.created_at)
        ).all()
        if by_phone and now - by_phone[-1] < timedelta(seconds=config.otp_resend_seconds):
            wait = _wait_until(by_phone[-1], timedelta(seconds=config.otp_resend_seconds), now)
            raise DomainError(
                429,
                "code_too_soon",
                "a new code can be sent in a moment",
                extra={"retry_after_seconds": wait},
                headers={"Retry-After": str(wait)},
            )
        by_address = session.scalars(
            select(OtpCode.created_at)
            .where(OtpCode.ip == ip, OtpCode.created_at > now - hour)
            .order_by(OtpCode.created_at)
        ).all()
        for sent, cap in (
            (by_phone, config.otp_per_phone_per_hour),
            (by_address, config.otp_per_address_per_hour),
        ):
            if len(sent) >= cap:
                wait = _wait_until(sent[len(sent) - cap], hour, now)
                raise DomainError(
                    429,
                    "too_many_codes",
                    "too many codes; try again later",
                    extra={"retry_after_seconds": wait},
                    headers={"Retry-After": str(wait)},
                )
        # A new code replaces any earlier one: only the latest can sign in.
        for earlier in session.scalars(
            select(OtpCode).where(OtpCode.phone == phone, OtpCode.used_at.is_(None))
        ):
            earlier.used_at = now
        session.execute(delete(OtpCode).where(OtpCode.created_at <= now - timedelta(days=1)))
        record = OtpCode(
            phone=phone,
            full_name=body.full_name,
            code_hash=_code_hash(config.secret_key, phone, code),
            ip=ip,
            created_at=now,
            expires_at=now + timedelta(seconds=config.otp_ttl_seconds),
        )
        session.add(record)
    # Sent after the lock is released: an SMS provider can take seconds, and the
    # whole shop waits while the write lock is held.
    try:
        sender.send(
            phone,
            f"קוד הכניסה שלך ל־{config.shop_brand}: {code}. בתוקף ל־{config.otp_ttl_seconds // 60} דקות.",
        )
    except SmsFailed as exc:
        with write_lock(session):
            session.execute(delete(OtpCode).where(OtpCode.id == record.id))
        raise DomainError(502, "sms_failed", "the code could not be sent; try again") from exc
    return {
        "phone_last4": phone[-4:],
        "expires_in_seconds": config.otp_ttl_seconds,
        "resend_after_seconds": config.otp_resend_seconds,
    }


@router.post("/auth/otp/verify")
def verify_code(body: CodeVerifyIn, session: Session = Depends(db), config: Settings = Depends(settings)):
    """Sign in with the code. The first time a phone signs in, its account is
    opened, under the full name given with the code. A wrong try is counted and
    kept even though the request fails - which is why the refusals are raised
    after the lock commits, not inside it, where they would roll it back."""
    phone = _phone_or_error(body.phone)
    now = datetime.now(UTC)
    refusal: DomainError | None = None
    user: User | None = None
    with write_lock(session):
        record = session.scalars(
            select(OtpCode)
            .where(OtpCode.phone == phone, OtpCode.used_at.is_(None))
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        ).first()
        if record is None:
            refusal = DomainError(409, "no_code", "ask for a code first")
        elif record.expires_at <= now:
            refusal = DomainError(409, "code_expired", "that code has expired; ask for a new one")
        elif record.attempts >= config.otp_attempts:
            refusal = DomainError(409, "code_used_up", "too many wrong codes; ask for a new one")
        elif not hmac.compare_digest(record.code_hash, _code_hash(config.secret_key, phone, body.code)):
            record.attempts += 1
            left = config.otp_attempts - record.attempts
            refusal = DomainError(401, "wrong_code", "that code is not right", extra={"attempts_left": left})
        else:
            record.used_at = now
            user = session.scalar(select(User).where(User.phone == phone))
            if user is None:
                user = User(
                    username=f"c-{secrets.token_hex(6)}",
                    # No password: this account signs in with codes only. A
                    # random one, unknown to anyone, keeps the column honest.
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    role="customer",
                    display_name=record.full_name,
                    phone=phone,
                )
                session.add(user)
                session.flush()
    if refusal is not None:
        raise refusal
    if not user.active:
        raise DomainError(403, "account_inactive", "this account is no longer active")
    token = issue_token(user.id, user.role, config.secret_key, config.token_hours)
    return {"access_token": token, "token_type": "bearer", "role": user.role}
