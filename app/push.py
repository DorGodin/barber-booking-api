"""Web Push, without a payload: the server tells a browser's push service "there is news" and the
page's service worker shows a notification of its own wording. Nothing about a booking travels through
the push service - not a name, not a time - which is also why there is no message encryption to carry.

The only thing signed is who is asking: a VAPID token (RFC 8292), made with the shop's own key pair. The
endpoint a browser hands over is a URL a customer chose, so the server only posts to the push services'
own hosts, and to the extra hosts a developer lists in PUSH_EXTRA_HOSTS - never to an address a customer
typed."""

from __future__ import annotations

import base64
import time
from typing import Protocol
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

# The push services browsers use: Chrome and Android, Safari, Firefox, Edge.
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "push.apple.com",
    "updates.push.services.mozilla.com",
    "notify.windows.com",
)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_keys() -> tuple[str, str]:
    """A new VAPID pair: the private scalar, and the public point a browser subscribes with."""
    private = ec.generate_private_key(ec.SECP256R1())
    scalar = private.private_numbers().private_value.to_bytes(32, "big")
    point = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64(scalar), b64(point)


def endpoint_allowed(endpoint: str, extra_hosts: tuple[str, ...] = ()) -> bool:
    """https to a push service's own host; an extra host (development, tests) may be http."""
    parts = urlparse(endpoint)
    host = parts.hostname or ""
    if parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
        return True
    return parts.scheme in ("http", "https") and host in extra_hosts


def vapid_token(endpoint: str, private: str, subject: str, now: float | None = None) -> str:
    parts = urlparse(endpoint)
    key = ec.derive_private_key(int.from_bytes(unb64(private), "big"), ec.SECP256R1())
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(now or time.time()) + 12 * 3600,
        "sub": subject,
    }
    return jwt.encode(claims, key, algorithm="ES256")


class PushSender(Protocol):
    def send(self, endpoint: str) -> int: ...


class VapidSender:
    def __init__(self, private: str, public: str, subject: str, extra_hosts: tuple[str, ...] = ()) -> None:
        self.private, self.public, self.subject, self.extra_hosts = private, public, subject, extra_hosts

    def send(self, endpoint: str) -> int:
        """The push service's answer: 201 delivered to it, 404 or 410 the subscription is gone."""
        if not endpoint_allowed(endpoint, self.extra_hosts):
            return 400
        token = vapid_token(endpoint, self.private, self.subject)
        headers = {
            "Authorization": f"vapid t={token}, k={self.public}",
            "TTL": "3600",
            "Urgency": "normal",
            "Content-Length": "0",
        }
        return httpx.post(endpoint, headers=headers, timeout=10).status_code


class PushHub:
    """Sends the news after the answer to the request has gone out. Nothing here may
    break a booking: a push that fails is forgotten, one the service says is gone removes
    the subscription."""

    def __init__(self, maker: sessionmaker[Session], sender: PushSender | None) -> None:
        self.maker, self.sender = maker, sender

    @property
    def available(self) -> bool:
        return self.sender is not None

    def tell(self, user_ids: list[str], notice: tuple[str, str] | None = None) -> None:
        """Wake each of these people's browsers. With a `notice` - a title and words - each browser is
        also left the words to fetch when it wakes; without one it shows its fixed wording."""
        if self.sender is None:
            return
        from app.models import PushNotice, PushSubscription

        with self.maker() as session:
            rows = session.scalars(
                select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
            ).all()
            if notice is not None:
                session.add_all(
                    PushNotice(subscription_id=r.id, title=notice[0], body=notice[1]) for r in rows
                )
                session.commit()
            gone = []
            for row in rows:
                try:
                    if self.sender.send(row.endpoint) in (404, 410):
                        gone.append(row.id)
                except Exception:  # noqa: BLE001 - a push must never break what it reports
                    continue
            if gone:
                session.execute(delete(PushNotice).where(PushNotice.subscription_id.in_(gone)))
                session.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
                session.commit()


def sender_from(private: str, public: str, subject: str, extra_hosts: str = "") -> VapidSender | None:
    if not (private and public):
        return None
    return VapidSender(
        private, public, subject, tuple(h.strip() for h in extra_hosts.split(",") if h.strip())
    )
