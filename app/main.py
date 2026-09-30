from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import Settings
from app.db import Base, make_engine, make_sessionmaker
from app.errors import DomainError, domain_error_handler
from app.routers import auth, barbers, bookings, services
from app.seed import seed_if_empty

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or Settings.from_env()
    engine = make_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        with app.state.sessionmaker() as session:
            seed_if_empty(session, config)
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
