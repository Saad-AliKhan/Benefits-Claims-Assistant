"""Consent page (citizen): SEE every permission, CHANGE (give again), WITHDRAW. Withdrawing blocks the
very next request that needs it. Helper Mode: a citizen names a helper; the helper picks a family."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, consent as consent_service
from app.db import get_db
from app.deps import require_role
from app.models import Consent, User

router = APIRouter(tags=["Consent and Helper Mode"])


def _out(c: Consent, helper: User | None) -> dict:
    grantee, en, ur = consent_service.PURPOSES[c.purpose]
    return {"id": c.id, "purpose": c.purpose, "shared_with": grantee, "en": en, "ur": ur, "status": c.status,
            "helper_name": helper.full_name if helper else None, "helper_email": helper.email if helper else None,
            "granted_at": c.granted_at, "withdrawn_at": c.withdrawn_at}


@router.get("/consents")
def my_consents(db: Session = Depends(get_db), citizen: User = Depends(require_role("citizen"))):
    """SEE: everything I have allowed, and everything I have taken back (newest first)."""
    rows = db.scalars(select(Consent).where(Consent.citizen_id == citizen.id).order_by(Consent.id.desc())).all()
    helpers = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.grantee_user_id for r in rows if r.grantee_user_id})))}
    return {"purposes": [{"purpose": k, "shared_with": v[0], "en": v[1], "ur": v[2]}
                         for k, v in consent_service.PURPOSES.items()],
            "records": [_out(c, helpers.get(c.grantee_user_id)) for c in rows]}


class GrantIn(BaseModel):
    purpose: str
    helper_email: str | None = Field(None, max_length=255)


@router.post("/consents", status_code=201)
def give(body: GrantIn, db: Session = Depends(get_db), citizen: User = Depends(require_role("citizen"))):
    """CHANGE: give (or give again) one permission. helper_access needs the helper's email."""
    helper = None
    if body.purpose == "helper_access":
        helper = db.scalar(select(User).where(User.email == (body.helper_email or "").strip().lower(),
                                              User.role == "helper"))
        if helper is None:
            raise HTTPException(404, "No helper with that email")
    c = consent_service.grant(db, citizen, body.purpose, actor=citizen, helper=helper)
    db.commit()
    return _out(c, helper)


@router.post("/consents/{consent_id}/withdraw")
def take_back(consent_id: int, db: Session = Depends(get_db), citizen: User = Depends(require_role("citizen"))):
    """WITHDRAW: access stops with the next request."""
    c = consent_service.withdraw(db, citizen, consent_id, actor=citizen)
    db.commit()
    return _out(c, db.get(User, c.grantee_user_id) if c.grantee_user_id else None)


@router.get("/helper/families")
def families(db: Session = Depends(get_db), user: User = Depends(require_role("helper"))):
    """Families that allow me to help them right now."""
    rows = db.execute(select(User).join(Consent, Consent.citizen_id == User.id)
                      .where(Consent.purpose == "helper_access", Consent.grantee_user_id == user.id,
                             Consent.status == "active").order_by(User.full_name)).scalars().all()
    return [{"citizen_id": u.id, "name": u.full_name} for u in rows]


@router.post("/helper/families/{citizen_id}/select")
def select_family(citizen_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("helper"))):
    consent_service.acting_citizen(db, user, citizen_id)  # 403 unless the family allows it
    audit.record(db, "helper.acting_for", actor=user, details={"citizen_id": citizen_id}, commit=True)
    return {"ok": True}
