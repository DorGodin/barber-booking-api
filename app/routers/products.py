"""The shop's shelf: what it sells, kept by the owner, and what a customer asked
to be kept for a booking. Nothing is paid or counted here - a kept product waits
at the shop, and the customer pays for it there."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booking_rules import approval_state, visible_booking_or_404
from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, media_dir, require, settings
from app.errors import DomainError, not_found
from app.models import Booking, BookingProduct, Product, User, now_utc
from app.routers.bookings import _view as booking_view_of
from app.routers.courses import picture
from app.schemas import ImageIn, ProductIn, ProductPatch
from app.views import page, product_view

router = APIRouter(tags=["products"])


def _product_or_404(session: Session, product_id: str) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise not_found("product")
    return product


def _forget_image(directory: Path, product: Product) -> None:
    if product.image:
        (directory / product.image).unlink(missing_ok=True)
        product.image = None


@router.get("/products")
def list_products(user: User = Depends(current_user), session: Session = Depends(db)):
    query = select(Product).order_by(Product.created_at, Product.id)
    if user.role != "owner":
        query = query.where(Product.active.is_(True))
    rows = session.scalars(query).all()
    return page(len(rows), [product_view(p) for p in rows])


@router.post("/products", status_code=201)
def create_product(body: ProductIn, _: User = Depends(require("owner")), session: Session = Depends(db)):
    with write_lock(session):
        product = Product(name=body.name, line=body.line, price_minor=body.price_minor)
        session.add(product)
        session.flush()
        return product_view(product)


@router.patch("/products/{product_id}")
def update_product(
    product_id: str,
    body: ProductPatch,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
):
    with write_lock(session):
        product = _product_or_404(session, product_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(product, field, value)
        return product_view(product)


@router.put("/products/{product_id}/image")
def set_product_image(
    product_id: str,
    body: ImageIn,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    directory: Path = Depends(media_dir),
):
    raw, extension = picture(body)
    with write_lock(session):
        product = _product_or_404(session, product_id)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"product-{product.id}-{secrets.token_hex(4)}.{extension}"
        (directory / name).write_bytes(raw)
        _forget_image(directory, product)
        product.image = name
        return product_view(product)


@router.delete("/products/{product_id}/image")
def remove_product_image(
    product_id: str,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    directory: Path = Depends(media_dir),
):
    with write_lock(session):
        product = _product_or_404(session, product_id)
        _forget_image(directory, product)
        return product_view(product)


def _kept(session: Session, booking: Booking, product: Product) -> BookingProduct | None:
    return session.scalar(
        select(BookingProduct).where(
            BookingProduct.booking_id == booking.id, BookingProduct.product_id == product.id
        )
    )


@router.put("/bookings/{booking_id}/products/{product_id}")
def keep_product(
    booking_id: str,
    product_id: str,
    user: User = Depends(require("customer", "owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    """Keep a product for a booking that is still ahead and stands. Asked twice,
    it is kept once."""
    with write_lock(session):
        booking = visible_booking_or_404(session, booking_id, user)
        product = _product_or_404(session, product_id)
        now = now_utc()
        if (
            booking.status != "confirmed"
            or booking.end_utc <= now
            or approval_state(booking, now) == "declined"
        ):
            raise DomainError(409, "booking_closed", "a product is kept only for a booking still ahead")
        if not product.active or not product.in_stock:
            raise DomainError(422, "product_unavailable", "that product cannot be kept right now")
        if _kept(session, booking, product) is None:
            session.add(BookingProduct(booking_id=booking.id, product_id=product.id))
            session.flush()
        return booking_view_of(session, booking, config)


@router.delete("/bookings/{booking_id}/products/{product_id}")
def release_product(
    booking_id: str,
    product_id: str,
    user: User = Depends(require("customer", "owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    with write_lock(session):
        booking = visible_booking_or_404(session, booking_id, user)
        kept = _kept(session, booking, _product_or_404(session, product_id))
        if kept is not None:
            session.delete(kept)
            session.flush()
        return booking_view_of(session, booking, config)
