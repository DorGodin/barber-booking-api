from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_text
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy import select

from app import backup, home_screen
from app.config import Settings
from app.db import IMMEDIATE, make_engine, make_sessionmaker
from app.errors import DomainError, domain_error_handler, not_found
from app.identity import (
    IMAGE_TYPES,
    contact_html,
    head_html,
    header_html,
    identity_from,
    media_file,
    under_brand,
)
from app.migrate import migrate
from app.models import Course, Product, User
from app.native_push import NativeSender, native_sender_from
from app.push import PushHub, PushSender
from app.push import sender_from as push_sender_from
from app.reminders import reminders
from app.routers import (
    accounts,
    auth,
    barbers,
    bookings,
    courses,
    customer_cards,
    products,
    push,
    services,
    standing,
)
from app.routers import settings as shop_settings
from app.seed import give_owner_phone, seed_if_empty
from app.sms import SmsSender, sender_from
from app.standing import standing as standing_bookings

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # A JSON answer is never a page: nothing in it may run or be framed.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

PAGE = Path(__file__).parent / "static" / "index.html"
SERVICE_WORKER = Path(__file__).parent / "static" / "sw.js"
FONTS = Path(__file__).parent / "static" / "fonts"
FONT_FILES = frozenset({"rubik-hebrew.woff2", "rubik-latin.woff2"})
STATEMENT = Path(__file__).parent / "static" / "accessibility.html"
PRIVACY = Path(__file__).parent / "static" / "privacy.html"


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
        # The shop's own pictures, served by this server under /media.
        "img-src 'self' data:; "
        # The page's own letters, served by this server under /fonts.
        "font-src 'self'; "
        "connect-src 'self'; "
        "worker-src 'self'; manifest-src 'self'; "
        "form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
    )


def backup_first(config: Settings):
    """A migration changes a running shop's tables. If it goes wrong there must
    be something to go back to - so the database is copied first, and a copy
    that cannot be made stops the migration."""

    def take(target: str) -> None:
        database = backup.database_path(config.database_url)
        backup.create(
            database, backup.backup_dir(database, config.backup_dir), config.backups_kept, f"before-{target}"
        )

    return take


def prepare_database(engine, make_session, config: Settings) -> None:
    """Migrate the tables and seed an empty shop - safely from several workers.

    Every worker runs this at startup, at the same moment. Unlocked, it is
    check-then-write across processes, the same shape as two customers booking
    one time: one worker died on "database is locked" on every fresh start, and
    the supervisor's restart hid it. Both steps now take the write lock at BEGIN;
    a worker that waits finds the work done and moves on.
    """
    with engine.connect() as connection:
        sqlite = engine.dialect.name == "sqlite"
        # SQLite changes a column by copying the table and dropping the old
        # one, and with foreign keys on, dropping it deletes every row that
        # points at it. They are off for the migration - set on the driver's
        # connection, because inside a transaction the setting is ignored -
        # checked before it commits, and on again before the connection goes
        # back to the pool for requests.
        if sqlite:
            connection.connection.driver_connection.execute("PRAGMA foreign_keys=OFF")
        try:
            connection.execution_options(**{IMMEDIATE: True})
            with connection.begin():
                migrate(connection, before_changes=backup_first(config) if sqlite else None)
        finally:
            if sqlite:
                connection.connection.driver_connection.execute("PRAGMA foreign_keys=ON")
    with make_session() as session:
        seed_if_empty(session, config)
        give_owner_phone(session, config)


def _media_next_to(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).parent / "media"
    return Path("media")


def create_app(
    config: Settings | None = None,
    sms: SmsSender | None = None,
    push_sender: PushSender | None = None,
    native_sender: NativeSender | None = None,
) -> FastAPI:
    config = config or Settings.from_env()
    engine = make_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_database(engine, app.state.sessionmaker, config)
        watching = []
        if app.state.push.available and config.reminder_minutes > 0:
            watching.append(asyncio.create_task(reminders(app.state.sessionmaker, app.state.push, config)))
        # Standing bookings are made whether or not anyone can be told.
        watching.append(
            asyncio.create_task(standing_bookings(app.state.sessionmaker, app.state.push, config))
        )
        yield
        for task in watching:
            task.cancel()
        engine.dispose()

    app = FastAPI(title="Barber Booking API", version="1.0.0", lifespan=lifespan)
    app.state.settings = config
    identity = config.identity or identity_from({}, config.shop_brand)
    media_dir = Path(config.media_dir) if config.media_dir else _media_next_to(config.database_url)
    app.state.media_dir = media_dir
    app.state.sms = sms or sender_from(config.sms_url, config.sms_token)
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.push = PushHub(
        app.state.sessionmaker,
        push_sender
        or push_sender_from(
            config.vapid_private_key, config.vapid_public_key, config.vapid_subject, config.push_extra_hosts
        ),
        native_sender or native_sender_from(config.fcm_credentials, config.fcm_project_id, config.fcm_url),
    )
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
            "brand": identity.brand,
            "under_brand": under_brand(identity),
            "links": identity.links,
            "timezone": config.shop_tz.key,
            "today": datetime.now(UTC).astimezone(config.shop_tz).date().isoformat(),
            "booking_window_days": config.booking_window_days,
            "bookings_ahead_limit": config.max_future_bookings,
            "cancel_cutoff_hours": config.cancel_cutoff_hours,
            "move_cutoff_hours": config.move_cutoff_hours,
        }

    @app.get("/", include_in_schema=False)
    def booking_page():
        # Read on every request, and hashed from the same bytes it serves: a
        # policy computed once at startup would block the page the moment the
        # file changed under a running server.
        html = (
            PAGE.read_text(encoding="utf-8")
            .replace("{{shop_header}}", header_html(identity))
            .replace("{{shop_contact}}", contact_html(identity))
            .replace("{{shop_head}}", head_html(identity))
            .replace("{{shop_title}}", html_text.escape(f"{identity.brand} {identity.tagline.title()}"))
        )
        return HTMLResponse(html, headers={"Content-Security-Policy": page_policy(html)})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        """At the root, so its scope is the whole page. Never cached: a browser checks it afresh."""
        return FileResponse(
            SERVICE_WORKER,
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/fonts/{name}", include_in_schema=False)
    def font(name: str):
        """The page's letters - these two files and nothing else in the folder."""
        if name not in FONT_FILES:
            raise not_found("font")
        return FileResponse(
            FONTS / name, media_type="font/woff2", headers={"Cache-Control": "public, max-age=2592000"}
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        """What lets the page be put on a phone's home screen - on an iPhone, the only way it can
        be sent notifications."""
        icons = []
        if identity.profile:
            icons = [
                {"src": "/icons/192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icons/512.png", "sizes": "512x512", "type": "image/png"},
                {
                    "src": "/icons/maskable-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ]
        return JSONResponse(
            {
                "name": f"{identity.brand} {identity.tagline.title()}",
                "short_name": identity.brand,
                "lang": "he",
                "dir": "rtl",
                "start_url": "/",
                "display": "standalone",
                # The splash a phone draws while the page opens: the shop's black, its logo and name.
                "background_color": "#111111",
                "theme_color": "#111111",
                "icons": icons,
            },
            media_type="application/manifest+json",
        )

    def profile_picture() -> Path:
        path = media_dir / identity.profile if identity.profile else None
        if path is None or not path.is_file():
            raise not_found("picture")
        return path

    @app.get("/icons/{name}.png", include_in_schema=False)
    def home_icon(name: str):
        """The shop's icon for a home screen, drawn from its profile picture."""
        if name not in home_screen.ICONS:
            raise not_found("picture")
        body = home_screen.icon(profile_picture(), name)
        return Response(body, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/splash/{size}.png", include_in_schema=False)
    def home_splash(size: str):
        """What an iPhone shows while the shop opens from its home screen, one picture per screen."""
        if size not in home_screen.splash_sizes():
            raise not_found("picture")
        body = home_screen.splash(profile_picture(), size, identity.brand, identity.tagline, identity.address)
        return Response(body, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/media/{name}", include_in_schema=False)
    def media(name: str):
        """The shop's cover and profile pictures, and the pictures of its courses, its products
        and its barbers - nothing else."""
        with app.state.sessionmaker() as session:
            course_images = set(session.scalars(select(Course.image).where(Course.image.is_not(None))))
            course_images |= set(session.scalars(select(Product.image).where(Product.image.is_not(None))))
            course_images |= set(session.scalars(select(User.photo).where(User.photo.is_not(None))))
        path = media_file(media_dir, identity, name, course_images)
        if path is None:
            raise not_found("picture")
        return FileResponse(
            path,
            media_type=IMAGE_TYPES[path.suffix.lstrip(".").lower()],
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/accessibility", include_in_schema=False)
    def accessibility_statement():
        """The accessibility statement Israeli law asks of a public site, with the
        shop's own contact and premises from its settings - escaped, they are text."""
        values = {
            "shop_brand": identity.brand,
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

    @app.get("/privacy", include_in_schema=False)
    def privacy_policy():
        """What the shop keeps about a customer, why, for how long, and how to ask
        for it to be shown, corrected or deleted - with the shop's own details
        from its settings, escaped."""
        address = identity.address
        values = {
            "shop_brand": identity.brand,
            "shop_address_line": f" · {address}" if address else "",
            "contact_phone": config.privacy_contact_phone,
            "contact_email": config.privacy_contact_email,
            "updated": config.privacy_updated,
        }
        html = PRIVACY.read_text(encoding="utf-8")
        for name, value in values.items():
            html = html.replace("{{" + name + "}}", html_text.escape(value))
        return HTMLResponse(html, headers={"Content-Security-Policy": page_policy(html)})

    for router in (
        auth.router,
        services.router,
        barbers.router,
        bookings.router,
        courses.router,
        products.router,
        customer_cards.router,
        accounts.router,
        push.router,
        shop_settings.router,
        standing.router,
    ):
        app.include_router(router)
    return app
