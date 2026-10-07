from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.deps import current_user, db, push_hub, settings
from app.errors import DomainError
from app.models import PushNotice, PushSubscription, User, now_utc
from app.push import PushHub, endpoint_allowed

router = APIRouter(tags=["push"])


class EndpointIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=500)


def _extra_hosts(config: Settings) -> tuple[str, ...]:
    return tuple(h.strip() for h in config.push_extra_hosts.split(",") if h.strip())


@router.get("/push/key")
def push_key(
    _: User = Depends(current_user), hub: PushHub = Depends(push_hub), config: Settings = Depends(settings)
):
    """The public key a browser subscribes with. None set: no push, and the page does not offer it."""
    if not hub.available:
        raise DomainError(404, "push_unavailable", "this shop does not send notifications")
    return {"key": config.vapid_public_key}


@router.post("/push/subscribe", status_code=201)
def subscribe(
    body: EndpointIn,
    user: User = Depends(current_user),
    session: Session = Depends(db),
    hub: PushHub = Depends(push_hub),
    config: Settings = Depends(settings),
):
    if not hub.available:
        raise DomainError(404, "push_unavailable", "this shop does not send notifications")
    if not endpoint_allowed(body.endpoint, _extra_hosts(config)):
        raise DomainError(422, "push_endpoint_refused", "that is not a push service's address")
    with write_lock(session):
        row = session.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
        if row is None:
            session.add(PushSubscription(user_id=user.id, endpoint=body.endpoint))
        else:
            # The same browser, signed in as someone else now: the news follows the person.
            row.user_id = user.id
    return {"subscribed": True}


@router.post("/push/notice")
def notice(body: EndpointIn, session: Session = Depends(db)):
    """The words for the notification a browser has just been woken for: the oldest not yet given to
    it. Asked by the service worker, which has no sign-in - its own address, a secret only that
    browser holds, is what it presents. Given once; none waiting, it shows its fixed wording."""
    with write_lock(session):
        row = session.scalar(
            select(PushNotice)
            .join(PushSubscription, PushSubscription.id == PushNotice.subscription_id)
            .where(PushSubscription.endpoint == body.endpoint, PushNotice.delivered_at.is_(None))
            .order_by(PushNotice.id)
            .limit(1)
        )
        if row is None:
            return {"title": None, "body": None}
        row.delivered_at = now_utc()
        return {"title": row.title, "body": row.body}


@router.post("/push/unsubscribe")
def unsubscribe(body: EndpointIn, user: User = Depends(current_user), session: Session = Depends(db)):
    with write_lock(session):
        session.execute(
            delete(PushSubscription).where(
                PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id
            )
        )
    return {"subscribed": False}
