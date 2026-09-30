"""First-run data: an owner, one barber, one customer, and the menu.

Passwords come from the environment and are never defaulted - an account whose
password is in the repository is an account anyone can use.
"""

from __future__ import annotations

import json
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BarberHours, Service, User
from app.routers.barbers import DEFAULT_HOURS
from app.security import hash_password

ACCOUNTS = (("owner", "owner", "Shop owner"), ("barber", "barber", "Avi"), ("customer", "customer", "Dana"))
MENU = (("Haircut", 30, 8000), ("Beard trim", 15, 4000), ("Haircut and beard", 45, 11000))


def seed_if_empty(session: Session) -> bool:
    if session.scalar(select(func.count()).select_from(User)):
        return False
    missing = [
        f"SEED_{role.upper()}_PASSWORD"
        for role, _, _ in ACCOUNTS
        if not os.environ.get(f"SEED_{role.upper()}_PASSWORD")
    ]
    if missing:
        raise RuntimeError(
            f"the database is empty and cannot be seeded: set {', '.join(missing)}. See .env.example."
        )

    for role, username, name in ACCOUNTS:
        user = User(
            username=username,
            password_hash=hash_password(os.environ[f"SEED_{role.upper()}_PASSWORD"]),
            role=role,
            display_name=name,
        )
        session.add(user)
        session.flush()
        if role == "barber":
            session.add(BarberHours(barber_id=user.id, hours_json=json.dumps(DEFAULT_HOURS)))
    for name, minutes, price in MENU:
        session.add(Service(name=name, duration_minutes=minutes, price_minor=price))
    session.commit()
    return True
