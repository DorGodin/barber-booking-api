from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.identity import Identity, identity_from


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    shop_tz: ZoneInfo
    booking_window_days: int
    cancel_cutoff_hours: int
    token_hours: int
    # The same 12 hours as the cancellation cutoff, by the owner's decision
    # (2026-10-06): inside it, a customer asks the shop on WhatsApp.
    move_cutoff_hours: int = 12
    login_max_failures: int = 5
    login_max_failures_per_ip: int = 20
    login_lock_minutes: int = 15
    max_future_bookings: int = 2
    # A customer's booking that starts from approval_from up to (not including)
    # approval_until, shop time, waits for its barber to say yes. No answer in
    # approval_wait_minutes: it stands, as if said yes.
    approval_from: str = "14:00"
    approval_until: str = "16:00"
    approval_wait_minutes: int = 120
    # A customer who moved a booking flag_moves times, or cancelled flag_cancels,
    # in the last flag_window_days has every booking wait for the barber's answer
    # - with no time after which silence is a yes. Never told to the customer.
    flag_moves: int = 3
    flag_cancels: int = 3
    flag_window_days: int = 90
    # How many people one customer may book for in one go, back to back with one barber.
    group_max: int = 2
    # A reminder to a customer this many minutes before their booking - by push, so only when push
    # is set up. The shop looks every reminder_check_seconds; 0 minutes turns reminders off.
    reminder_minutes: int = 120
    reminder_check_seconds: int = 60
    # Web Push: the shop's VAPID key pair (`python -m app.push_keys` makes one), who is asking, and
    # extra hosts a developer lets the server post to - the push services' own hosts are built in.
    # No pair: no push, and the page does not offer it.
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:owner@example.com"
    push_extra_hosts: str = ""
    signups_per_address: int = 5
    signup_window_minutes: int = 60
    # Where a text message is posted: a provider's URL, or "console" to print it
    # (development only). No default - a server that cannot send codes cannot
    # sign anyone in, and must say so at startup, not at the first sign-in.
    sms_url: str = "console"
    sms_token: str = ""
    shop_brand: str = "TomGoldin"
    # The shop's tagline, address, links and pictures (app/identity.py). None:
    # the brand alone, as in the tests that do not need the rest.
    identity: Identity | None = None
    # Empty: a media folder next to the database, for the shop's pictures.
    media_dir: str = ""
    otp_ttl_seconds: int = 300
    otp_attempts: int = 3
    otp_resend_seconds: int = 60
    otp_per_phone_per_hour: int = 5
    otp_per_address_per_hour: int = 20
    # Empty: a backups folder next to the database.
    backup_dir: str = ""
    backups_kept: int = 10
    accessibility_contact_name: str = "רכז/ת הנגישות של המספרה (לדוגמה)"
    accessibility_contact_phone: str = "03-0000000"
    accessibility_contact_email: str = "accessibility@example.com"
    accessibility_premises: str = "(לדוגמה) הכניסה למספרה במפלס הרחוב, בלי מדרגות."
    accessibility_updated: str = "1 באוקטובר 2026"
    privacy_contact_phone: str = "03-0000000"
    privacy_contact_email: str = "privacy@example.com"
    privacy_updated: str = "3 באוקטובר 2026"

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.environ.get("SECRET_KEY")
        if not secret or len(secret) < 32:
            # No default. A default signing key is a key everyone who has read
            # this repository knows.
            raise RuntimeError("SECRET_KEY must be set to at least 32 characters. See .env.example.")
        sms_url = os.environ.get("SMS_URL", "")
        if not sms_url:
            raise RuntimeError(
                "SMS_URL must be set: a provider's URL, or console for development. See .env.example."
            )
        return cls(
            sms_url=sms_url,
            sms_token=os.environ.get("SMS_TOKEN", ""),
            shop_brand=os.environ.get("SHOP_BRAND", "TomGoldin"),
            identity=identity_from(dict(os.environ), os.environ.get("SHOP_BRAND", "TomGoldin")),
            media_dir=os.environ.get("MEDIA_DIR", ""),
            otp_ttl_seconds=int(os.environ.get("OTP_TTL_SECONDS", "300")),
            otp_attempts=int(os.environ.get("OTP_ATTEMPTS", "3")),
            otp_resend_seconds=int(os.environ.get("OTP_RESEND_SECONDS", "60")),
            otp_per_phone_per_hour=int(os.environ.get("OTP_PER_PHONE_PER_HOUR", "5")),
            otp_per_address_per_hour=int(os.environ.get("OTP_PER_ADDRESS_PER_HOUR", "20")),
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./barber.db"),
            secret_key=secret,
            shop_tz=ZoneInfo(os.environ.get("SHOP_TZ", "Asia/Jerusalem")),
            booking_window_days=int(os.environ.get("BOOKING_WINDOW_DAYS", "30")),
            cancel_cutoff_hours=int(os.environ.get("CANCEL_CUTOFF_HOURS", "12")),
            move_cutoff_hours=int(os.environ.get("MOVE_CUTOFF_HOURS", "12")),
            token_hours=int(os.environ.get("TOKEN_HOURS", "12")),
            login_max_failures=int(os.environ.get("LOGIN_MAX_FAILURES", "5")),
            login_max_failures_per_ip=int(os.environ.get("LOGIN_MAX_FAILURES_PER_IP", "20")),
            login_lock_minutes=int(os.environ.get("LOGIN_LOCK_MINUTES", "15")),
            max_future_bookings=int(os.environ.get("MAX_FUTURE_BOOKINGS", "2")),
            approval_from=os.environ.get("APPROVAL_FROM", "14:00"),
            approval_until=os.environ.get("APPROVAL_UNTIL", "16:00"),
            approval_wait_minutes=int(os.environ.get("APPROVAL_WAIT_MINUTES", "120")),
            flag_moves=int(os.environ.get("FLAG_MOVES", "3")),
            flag_cancels=int(os.environ.get("FLAG_CANCELS", "3")),
            flag_window_days=int(os.environ.get("FLAG_WINDOW_DAYS", "90")),
            group_max=int(os.environ.get("GROUP_MAX", "2")),
            reminder_minutes=int(os.environ.get("REMINDER_MINUTES", "120")),
            reminder_check_seconds=int(os.environ.get("REMINDER_CHECK_SECONDS", "60")),
            vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
            vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", ""),
            vapid_subject=os.environ.get("VAPID_SUBJECT", "mailto:owner@example.com"),
            push_extra_hosts=os.environ.get("PUSH_EXTRA_HOSTS", ""),
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
                    ("privacy_contact_phone", "PRIVACY_CONTACT_PHONE"),
                    ("privacy_contact_email", "PRIVACY_CONTACT_EMAIL"),
                    ("privacy_updated", "PRIVACY_UPDATED"),
                )
                if os.environ.get(name)
            },
        )
