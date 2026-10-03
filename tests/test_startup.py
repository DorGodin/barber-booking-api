"""Several worker processes starting at once on an empty database.

Each runs the startup: create the tables, seed the shop if it is empty. That is
check-then-write across processes - the same shape as two customers booking
one time - and it fails the same way: a worker that loses dies on "database is
locked", or two that both saw an empty database both seed it.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.conftest import login

WORKERS = 4


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_workers_starting_together_on_an_empty_database_seed_it_once_and_none_dies(tmp_path: Path):
    passwords = {role: secrets.token_urlsafe(12) for role in ("owner", "barber", "customer")}
    port, log = free_port(), tmp_path / "server.log"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'fresh.db'}",
        "SECRET_KEY": secrets.token_hex(32),
        "SMS_URL": "console",
        **{f"SEED_{role.upper()}_PASSWORD": pw for role, pw in passwords.items()},
    }
    with log.open("w") as out:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--port",
                str(port),
                "--workers",
                str(WORKERS),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(20):
                try:
                    if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(1)
            else:
                # Fail now, with the reason, rather than wait on a server that
                # will never answer.
                out.flush()
                pytest.fail("the server did not start:\n" + log.read_text()[-1500:])
            time.sleep(2)  # let every worker finish its startup, or fail it
            owners = httpx.get(
                f"{base}/barbers", headers=login(httpx.Client(base_url=base), "owner", passwords["owner"])
            ).status_code
        finally:
            proc.terminate()
            proc.wait(timeout=15)

    text = log.read_text()
    assert "Application startup failed" not in text and "database is locked" not in text, (
        "a worker crashed during startup:\n"
        + "\n".join(line for line in text.splitlines() if "rror" in line)[:1500]
    )
    assert text.count("Application startup complete.") == WORKERS
    assert owners == 200


def test_the_shop_is_seeded_exactly_once(client, passwords):
    owner = login(client, "owner", passwords["owner"])

    assert [b["display_name"] for b in client.get("/barbers", headers=owner).json()["content"]].count(
        "אבי"
    ) == 1
