from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.booking_rules import APPROVAL_KEY, approval_rules
from app.config import Settings
from app.db import write_lock
from app.deps import db, require, settings
from app.models import ShopSetting, User
from app.schemas import ApprovalRulesIn

router = APIRouter(tags=["settings"])


@router.get("/approval-rules")
def read_approval_rules(
    _: User = Depends(require("owner")), session: Session = Depends(db), config: Settings = Depends(settings)
):
    return approval_rules(session, config)


@router.put("/approval-rules")
def save_approval_rules(
    body: ApprovalRulesIn, _: User = Depends(require("owner")), session: Session = Depends(db)
):
    """The owner turns the barber's yes on or off and says on which days and
    hours it is asked. Bookings already waiting keep their wait; only the ones
    made after this follow it."""
    rules = {"enabled": body.enabled, "hours": body.hours}
    with write_lock(session):
        row = session.get(ShopSetting, APPROVAL_KEY)
        if row is None:
            session.add(ShopSetting(key=APPROVAL_KEY, value_json=json.dumps(rules)))
        else:
            row.value_json = json.dumps(rules)
    return rules
