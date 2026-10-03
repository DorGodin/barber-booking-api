"""Sending a text message. The product only ever posts to an address from its
settings, as it would to any real provider; which provider that is - or a fake
one, in development and in the outside test suites - is the settings' business,
never the code's."""

from __future__ import annotations

from typing import Protocol

import httpx


class SmsFailed(RuntimeError):
    pass


class SmsSender(Protocol):
    def send(self, phone: str, text: str) -> None: ...


class HttpSms:
    def __init__(self, url: str, token: str = "") -> None:
        self.url, self.token = url, token

    def send(self, phone: str, text: str) -> None:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            resp = httpx.post(self.url, json={"to": phone, "text": text}, headers=headers, timeout=10)
        except httpx.HTTPError as exc:
            raise SmsFailed(f"the SMS service did not answer: {exc}") from exc
        if resp.status_code >= 300:
            raise SmsFailed(f"the SMS service refused: {resp.status_code}")


class ConsoleSms:
    """Development only: the message is printed to the server's own output.
    Chosen by SMS_URL=console, never by default."""

    def send(self, phone: str, text: str) -> None:
        print(f"[sms to {phone}] {text}", flush=True)


def sender_from(url: str, token: str = "") -> SmsSender:
    return ConsoleSms() if url == "console" else HttpSms(url, token)
