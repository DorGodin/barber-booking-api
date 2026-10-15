"""Notifications to the shop's app on a phone, through Firebase Cloud Messaging - on Android, and on an
iPhone too: Firebase hands an iPhone's message to Apple's APNs with the key the shop gave Firebase, so the
server speaks to one service for both.

As with Web Push, nothing about a booking travels through the service - not a name, not a time. A phone
shows the fixed words of the person's role, and the app shows the rest once it is opened.

The server signs in to Firebase as the shop's service account: a JWT signed with its private key buys an
access token for an hour. The address posted to is fixed - only the device's token comes from the phone,
and it travels in the body, never in the URL."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import jwt

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
# What a phone shows, by role: the same words as the page's service worker, and no more.
WORDS = {
    "customer": ("עדכון על התור שלך", "פתחו את האפליקציה לפרטים."),
    "staff": ("עדכון ביומן", "תור חדש, בקשה או ביטול - פתחו את היומן."),
}


def words_for(role: str) -> tuple[str, str]:
    return WORDS["customer" if role == "customer" else "staff"]


class NativeSender(Protocol):
    def send(self, token: str, title: str, body: str) -> bool:
        """Delivered to the service - or False when the service says this device is gone."""
        ...


@dataclass
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: str
    token_uri: str

    @classmethod
    def from_file(cls, path: str, project_id: str = "") -> ServiceAccount:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            project_id=project_id or raw["project_id"],
            client_email=raw["client_email"],
            private_key=raw["private_key"],
            token_uri=raw.get("token_uri", "https://oauth2.googleapis.com/token"),
        )


class FcmSender:
    def __init__(self, account: ServiceAccount, base_url: str = "https://fcm.googleapis.com") -> None:
        self.account, self.base_url = account, base_url.rstrip("/")
        self._token, self._until, self._lock = "", 0.0, threading.Lock()

    def _access_token(self) -> str:
        """An hour's access, bought with a signed assertion and kept until five minutes before it ends."""
        with self._lock:
            now = time.time()
            if self._token and now < self._until:
                return self._token
            assertion = jwt.encode(
                {
                    "iss": self.account.client_email,
                    "scope": SCOPE,
                    "aud": self.account.token_uri,
                    "iat": int(now),
                    "exp": int(now) + 3600,
                },
                self.account.private_key,
                algorithm="RS256",
            )
            answer = httpx.post(
                self.account.token_uri,
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                timeout=10,
            )
            answer.raise_for_status()
            granted = answer.json()
            self._token, self._until = (
                granted["access_token"],
                now + int(granted.get("expires_in", 3600)) - 300,
            )
            return self._token

    def send(self, token: str, title: str, body: str) -> bool:
        message = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "android": {"priority": "high"},
                "apns": {"payload": {"aps": {"sound": "default"}}},
            }
        }
        answer = httpx.post(
            f"{self.base_url}/v1/projects/{self.account.project_id}/messages:send",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json=message,
            timeout=10,
        )
        if answer.status_code == 404:
            return False
        if answer.status_code == 400 and "UNREGISTERED" in answer.text:
            return False
        return True


def native_sender_from(credentials: str, project_id: str = "", base_url: str = "") -> FcmSender | None:
    """FCM_CREDENTIALS, the service account's JSON file. None set: no phone notifications."""
    if not credentials:
        return None
    return FcmSender(
        ServiceAccount.from_file(credentials, project_id), base_url or "https://fcm.googleapis.com"
    )
