"""A customer deletes their own account - in the app, as both stores require of an app one can sign up in.

What is theirs goes: the name, the phone, the staff's note about them, their notifications and any code
still waiting for their phone. What the shop needs stays, without them: the bookings that are over keep
their place in the diary and the counts, under no name, and the reviews they wrote keep their stars and
words. Bookings still ahead are cancelled, and the staff are told as of any customer's cancellation.
The row itself stays, emptied and closed, so nothing that pointed at it breaks."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import write_lock
from app.deps import db, push_hub, require, settings
from app.models import Booking, OtpCode, PushNotice, PushSubscription, User
from app.push import PushHub
from app.routers.bookings import _tell_staff, _who_and_when

router = APIRouter(tags=["accounts"])


@router.delete("/me", status_code=204)
def delete_my_account(
    background: BackgroundTasks,
    user: User = Depends(require("customer")),
    session: Session = Depends(db),
    config: Settings = Depends(settings),
    hub: PushHub = Depends(push_hub),
):
    now = datetime.now(UTC)
    with write_lock(session):
        ahead = session.scalars(
            select(Booking).where(
                Booking.customer_id == user.id, Booking.status == "confirmed", Booking.end_utc > now
            )
        ).all()
        for booking in ahead:
            # Told while the name is still there to tell.
            _tell_staff(
                session, background, hub, booking, "ביטול תור", _who_and_when(session, booking, config)
            )
            booking.status, booking.cancelled_at, booking.cancelled_by = "cancelled", now, user.id
        subscriptions = select(PushSubscription.id).where(PushSubscription.user_id == user.id)
        session.execute(delete(PushNotice).where(PushNotice.subscription_id.in_(subscriptions)))
        session.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id))
        if user.phone:
            session.execute(delete(OtpCode).where(OtpCode.phone == user.phone))
        user.display_name, user.phone, user.staff_note = "", None, None
        # No name to sign in with and no password that matches: closed, as a barber who left is.
        user.username, user.password_hash = f"deleted-{user.id}", "!"
        user.active, user.deleted_at = False, now
    return Response(status_code=204)
