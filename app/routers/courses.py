from __future__ import annotations

import base64
import binascii
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, media_dir, require, settings
from app.errors import DomainError, not_found
from app.identity import IMAGE_TYPES
from app.models import Course, User
from app.schemas import CourseIn, CoursePatch, ImageIn
from app.views import course_view, page

router = APIRouter(tags=["courses"])

MAX_IMAGE_BYTES = 3_000_000


def _extension(raw: bytes) -> str | None:
    """What the bytes are, by their first bytes - never by a name the client gave."""
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _view(course: Course, config: Settings) -> dict:
    whatsapp = config.identity.links.get("whatsapp") if config.identity else None
    return course_view(course, whatsapp)


def _course_or_404(session: Session, course_id: str) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise not_found("course")
    return course


def _forget_image(directory: Path, course: Course) -> None:
    if course.image:
        (directory / course.image).unlink(missing_ok=True)
        course.image = None


@router.get("/courses")
def list_courses(
    user: User = Depends(current_user), session: Session = Depends(db), config: Settings = Depends(settings)
):
    query = select(Course).order_by(Course.starts_on.is_(None), Course.starts_on, Course.title)
    if user.role != "owner":
        query = query.where(Course.active.is_(True))
    rows = session.scalars(query).all()
    return page(len(rows), [_view(c, config) for c in rows])


@router.post("/courses", status_code=201)
def create_course(
    body: CourseIn,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    with write_lock(session):
        course = Course(
            title=body.title,
            subtitle=body.subtitle,
            starts_on=body.starts_on.isoformat() if body.starts_on else None,
            price_minor=body.price_minor,
        )
        session.add(course)
        session.flush()
        return _view(course, config)


@router.patch("/courses/{course_id}")
def update_course(
    course_id: str,
    body: CoursePatch,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
):
    with write_lock(session):
        course = _course_or_404(session, course_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            if field == "starts_on" and value is not None:
                value = value.isoformat()
            if value is None and field in {"title", "subtitle", "active"}:
                continue
            setattr(course, field, value)
        return _view(course, config)


@router.put("/courses/{course_id}/image")
def set_course_image(
    course_id: str,
    body: ImageIn,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
    directory: Path = Depends(media_dir),
):
    """The owner's picture for a course. What is accepted is decided by the bytes:
    a JPEG, a PNG or a WebP of at most 3 MB. The file name is the server's own."""
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise DomainError(422, "invalid_image", "the picture is not valid base64") from None
    if len(raw) > MAX_IMAGE_BYTES:
        raise DomainError(422, "image_too_large", "a picture may be at most 3 MB")
    extension = _extension(raw)
    if extension is None or extension not in IMAGE_TYPES:
        raise DomainError(422, "invalid_image", "a picture must be a JPEG, PNG or WebP")
    with write_lock(session):
        course = _course_or_404(session, course_id)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"course-{course.id}-{secrets.token_hex(4)}.{extension}"
        (directory / name).write_bytes(raw)
        _forget_image(directory, course)
        course.image = name
        return _view(course, config)


@router.delete("/courses/{course_id}/image")
def remove_course_image(
    course_id: str,
    _: User = Depends(require("owner")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
    directory: Path = Depends(media_dir),
):
    with write_lock(session):
        course = _course_or_404(session, course_id)
        _forget_image(directory, course)
        return _view(course, config)
