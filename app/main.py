from __future__ import annotations

import base64
import hashlib
import html as html_text
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.db import IMMEDIATE, Base, make_engine, make_sessionmaker
from app.errors import DomainError, domain_error_handler
from app.routers import auth, barbers, bookings, services
from app.seed import seed_if_empty

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # A JSON answer is never a page: nothing in it may run or be framed.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

PAGE = Path(__file__).parent / "static" / "index.html"
STATEMENT = Path(__file__).parent / "static" / "accessibility.html"


def page_policy(html: str) -> str:
    """The booking page's Content-Security-Policy: its own inline script and
    style, by hash, and nothing else - no other script, no inline handler, no
    request to another site.

    The page keeps the sign-in in sessionStorage, which any script running in
    it can read. Escaping every name with textContent is the first defence;
    this is the second, for the day one is missed. Hashes, not 'unsafe-inline':
    with 'unsafe-inline' an injected <script> or onerror= runs as well.
    """

    def hashes(tag: str) -> str:
        bodies = re.findall(rf"<{tag}>(.*?)</{tag}>", html, re.S)
        return (
            " ".join(
                f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
                for body in bodies
            )
            or "'none'"
        )

    return (
        "default-src 'none'; "
        f"script-src {hashes('script')}; "
        f"style-src {hashes('style')}; "
        # The select's arrow is an inline SVG.
        "img-src data:; "
        "connect-src 'self'; "
        "form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
    )


def prepare_database(engine, make_session, config: Settings) -> None:
    """Create the tables and seed an empty shop - safely from several workers.

    Every worker runs this at startup, at the same moment. Unlocked, it is
    check-then-write across processes, the same shape as two customers booking
    one time: one worker died on "database is locked" on every fresh start, and
    the supervisor's restart hid it. Both steps now take the write lock at BEGIN;
    a worker that waits finds the work done and moves on.
    """
    with engine.connect() as connection:
        connection.execution_options(**{IMMEDIATE: True})
        with connection.begin():
            Base.metadata.create_all(connection)
    with make_session() as session:
        seed_if_empty(session, config)


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or Settings.from_env()
    engine = make_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_database(engine, app.state.sessionmaker, config)
        yield
        engine.dispose()

    app = FastAPI(title="Barber Booking API", version="1.0.0", lifespan=lifespan)
    app.state.settings = config
    app.state.sessionmaker = make_sessionmaker(engine)
    app.add_exception_handler(DomainError, domain_error_handler)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    @app.get("/shop", tags=["shop"])
    def shop():
        """The shop's own clock and rules, for a client that must not guess them.
        A browser in another time zone would otherwise compute a different today."""
        return {
            "timezone": config.shop_tz.key,
            "today": datetime.now(UTC).astimezone(config.shop_tz).date().isoformat(),
            "booking_window_days": config.booking_window_days,
            "cancel_cutoff_hours": config.cancel_cutoff_hours,
        }

    @app.get("/", include_in_schema=False)
    def booking_page():
        # Read on every request, and hashed from the same bytes it serves: a
        # policy computed once at startup would block the page the moment the
        # file changed under a running server.
        html = PAGE.read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Content-Security-Policy": page_policy(html)})

    @app.get("/accessibility", include_in_schema=False)
    def accessibility_statement():
        """The accessibility statement Israeli law asks of a public site, with the
        shop's own contact and premises from its settings - escaped, they are text."""
        values = {
            "contact_name": config.accessibility_contact_name,
            "contact_phone": config.accessibility_contact_phone,
            "contact_email": config.accessibility_contact_email,
            "premises": config.accessibility_premises,
            "updated": config.accessibility_updated,
        }
        html = STATEMENT.read_text(encoding="utf-8")
        for name, value in values.items():
            html = html.replace("{{" + name + "}}", html_text.escape(value))
        return HTMLResponse(html, headers={"Content-Security-Policy": page_policy(html)})

    for router in (auth.router, services.router, barbers.router, bookings.router):
        app.include_router(router)
    return app
