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
    max_future_bookings: int = 2
    signups_per_address: int = 5
    signup_window_minutes: int = 60
    # Empty: a backups folder next to the database.
    backup_dir: str = ""
    backups_kept: int = 10
    accessibility_contact_name: str = "רכז/ת הנגישות של המספרה (לדוגמה)"
    accessibility_contact_phone: str = "03-0000000"
    accessibility_contact_email: str = "accessibility@example.com"
    accessibility_premises: str = "(לדוגמה) הכניסה למספרה במפלס הרחוב, בלי מדרגות."
    accessibility_updated: str = "1 באוקטובר 2026"

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
            max_future_bookings=int(os.environ.get("MAX_FUTURE_BOOKINGS", "2")),
            signups_per_address=int(os.environ.get("SIGNUPS_PER_ADDRESS", "5")),
            signup_window_minutes=int(os.environ.get("SIGNUP_WINDOW_MINUTES", "60")),
            backup_dir=os.environ.get("BACKUP_DIR", ""),
            backups_kept=int(os.environ.get("BACKUPS_KEPT", "10")),
            **{
                field: os.environ[name]
                for field, name in (
                    ("accessibility_contact_name", "ACCESSIBILITY_CONTACT_NAME"),
                    ("accessibility_contact_phone", "ACCESSIBILITY_CONTACT_PHONE"),
                    ("accessibility_contact_email", "ACCESSIBILITY_CONTACT_EMAIL"),
                    ("accessibility_premises", "ACCESSIBILITY_PREMISES"),
                    ("accessibility_updated", "ACCESSIBILITY_UPDATED"),
                )
                if os.environ.get(name)
            },
        )
