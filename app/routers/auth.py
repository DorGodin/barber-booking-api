from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import current_user, db, settings
from app.errors import DomainError
from app.models import User
from app.schemas import AccountIn, LoginIn
from app.security import hash_password, issue_token, verify_password
from app.views import user_view

router = APIRouter(tags=["auth"])


@router.post("/auth/token")
def login(body: LoginIn, session: Session = Depends(db), config: Settings = Depends(settings)):
    user = session.scalar(select(User).where(User.username == body.username))
    if not verify_password(body.password, user.password_hash if user else None):
        # The same answer for an unknown user and a wrong password.
        raise DomainError(401, "bad_credentials", "wrong username or password")
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
