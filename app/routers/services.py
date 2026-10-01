from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import write_lock
from app.deps import current_user, db, require
from app.errors import DomainError, not_found
from app.models import Service, User
from app.schemas import ServiceIn, ServicePatch
from app.views import page, service_view

router = APIRouter(tags=["services"])


@router.get("/services")
def list_services(user: User = Depends(current_user), session: Session = Depends(db)):
    query = select(Service).order_by(Service.name)
    if user.role != "owner":
        query = query.where(Service.active.is_(True))
    rows = session.scalars(query).all()
    return page(len(rows), [service_view(s) for s in rows])


@router.post("/services", status_code=201)
def create_service(body: ServiceIn, _: User = Depends(require("owner")), session: Session = Depends(db)):
    # Every write here takes the write lock at BEGIN: a write that reads first and
    # then waits for a booking's lock is refused by SQLite at once - a 500.
    with write_lock(session):
        if session.scalar(select(func.count()).select_from(Service).where(Service.name == body.name)):
            raise DomainError(409, "name_taken", "a service with that name exists")
        service = Service(**body.model_dump())
        session.add(service)
    return service_view(service)


@router.patch("/services/{service_id}")
def update_service(
    service_id: str, body: ServicePatch, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    with write_lock(session):
        service = session.get(Service, service_id)
        if service is None:
            raise not_found("service")
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(service, field, value)
    return service_view(service)
