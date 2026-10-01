from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

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
}


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
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    for router in (auth.router, services.router, barbers.router, bookings.router):
        app.include_router(router)
    return app
