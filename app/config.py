from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    shop_tz: ZoneInfo
    booking_window_days: int
    cancel_cutoff_hours: int
    token_hours: int
    login_max_failures: int = 5
    login_max_failures_per_ip: int = 20
    login_lock_minutes: int = 15

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.environ.get("SECRET_KEY")
        if not secret or len(secret) < 32:
            # No default. A default signing key is a key everyone who has read
            # this repository knows.
            raise RuntimeError("SECRET_KEY must be set to at least 32 characters. See .env.example.")
        return cls(
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./barber.db"),
            secret_key=secret,
            shop_tz=ZoneInfo(os.environ.get("SHOP_TZ", "Asia/Jerusalem")),
            booking_window_days=int(os.environ.get("BOOKING_WINDOW_DAYS", "60")),
            cancel_cutoff_hours=int(os.environ.get("CANCEL_CUTOFF_HOURS", "24")),
            token_hours=int(os.environ.get("TOKEN_HOURS", "12")),
            login_max_failures=int(os.environ.get("LOGIN_MAX_FAILURES", "5")),
            login_max_failures_per_ip=int(os.environ.get("LOGIN_MAX_FAILURES_PER_IP", "20")),
            login_lock_minutes=int(os.environ.get("LOGIN_LOCK_MINUTES", "15")),
        )
