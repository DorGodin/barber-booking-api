from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.identity import Identity, identity_from
from app.phones import normalize


def _owner_phone(raw: str) -> str:
    """Stored the way every phone is, or the server does not start: a mistyped number
    here would leave the owner locked out, or hand the shop to whoever has that number."""
    if not raw.strip():
        return ""
    phone = normalize(raw)
    if phone is None:
        raise RuntimeError("OWNER_PHONE must be a mobile number: 05 and eight more digits. See .env.example.")
    return phone


def _review_sign_in(raw_phone: str, raw_code: str, owner_phone: str) -> tuple[str, str]:
    """The App Store's and Google Play's reviewers cannot receive an SMS: one mobile, set here, signs in
    with a fixed code and is sent nothing. Both or neither, a mobile and four digits, and never the
    owner's phone - or the server does not start."""
    if not raw_phone.strip() and not raw_code.strip():
        return "", ""
    phone = normalize(raw_phone)
    if phone is None or not (len(raw_code) == 4 and raw_code.isdigit()):
        problem = "REVIEW_PHONE and REVIEW_CODE go together: a mobile and four digits. See .env.example."
        raise RuntimeError(problem)
    if phone == owner_phone:
        raise RuntimeError("REVIEW_PHONE must not be the owner's phone: the reviewers sign in as a customer.")
    return phone, raw_code


def local_sms(url: str) -> bool:
    """The codes stay on this machine: printed, or posted to a server here - the fake provider of the tests."""
    host = urlsplit(url).hostname or ""
    return url == "console" or host in ("127.0.0.1", "localhost", "::1")


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
    max_future_bookings: int = 5
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
    # The shop's app on a phone, through Firebase: its service account's JSON file, and (for tests and
    # development) another address for Firebase. No file: no phone notifications.
    fcm_credentials: str = ""
    fcm_project_id: str = ""
    fcm_url: str = ""
    signups_per_address: int = 5
    signup_window_minutes: int = 60
    # Where a text message is posted: a provider's URL, or "console" to print it
    # (development only). No default - a server that cannot send codes cannot
    # sign anyone in, and must say so at startup, not at the first sign-in.
    sms_url: str = "console"
    sms_token: str = ""
    # Development only, while the app is being tried out: the code comes back in the answer and the page signs
    # in at once. Refused at start unless the codes go to the console or a server on this machine - never a
    # provider that reaches real phones.
    dev_skip_code: bool = False
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
    # The owner's own mobile: signing in with it, by a code, opens the owner's screen.
    # Empty: the owner has no phone on record and cannot sign in on the page.
    owner_phone: str = ""
    # The stores' reviewers: this mobile signs in with this code, and no SMS is sent to it (_review_sign_in).
    review_phone: str = ""
    review_code: str = ""
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
        owner_phone = _owner_phone(os.environ.get("OWNER_PHONE", ""))
        review_phone, review_code = _review_sign_in(
            os.environ.get("REVIEW_PHONE", ""), os.environ.get("REVIEW_CODE", ""), owner_phone
        )
        dev_skip_code = os.environ.get("DEV_SKIP_CODE", "") == "1"
        if dev_skip_code and not local_sms(sms_url):
            raise RuntimeError(
                "DEV_SKIP_CODE is for development only: SMS_URL must be console or a server on this machine."
            )
        return cls(
            sms_url=sms_url,
            sms_token=os.environ.get("SMS_TOKEN", ""),
            dev_skip_code=dev_skip_code,
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
            max_future_bookings=int(os.environ.get("MAX_FUTURE_BOOKINGS", "5")),
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
            fcm_credentials=os.environ.get("FCM_CREDENTIALS", ""),
            fcm_project_id=os.environ.get("FCM_PROJECT_ID", ""),
            fcm_url=os.environ.get("FCM_URL", ""),
            signups_per_address=int(os.environ.get("SIGNUPS_PER_ADDRESS", "5")),
            signup_window_minutes=int(os.environ.get("SIGNUP_WINDOW_MINUTES", "60")),
            backup_dir=os.environ.get("BACKUP_DIR", ""),
            backups_kept=int(os.environ.get("BACKUPS_KEPT", "10")),
            owner_phone=owner_phone,
            review_phone=review_phone,
            review_code=review_code,
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
