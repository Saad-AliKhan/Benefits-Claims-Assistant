"""Consent: what a citizen has allowed, checked on the server before every use.

Each permission is one row (see models.Consent). Withdrawing takes effect on the very next request:
every place that uses the data calls require_consent() first.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.models import Consent, User, utcnow

# purpose -> (who receives it, plain English, plain Urdu)
PURPOSES = {
    "identity_check": ("platform", "Check my CNIC with the identity office (mock NADRA) and read my CNIC photo.",
                       "میرا شناختی کارڈ شناختی دفتر (فرضی نادرا) سے چیک کریں اور میرے کارڈ کی تصویر پڑھیں۔"),
    "records_check": ("platform", "Look up the death record and read the death certificate photo.",
                      "وفات کا ریکارڈ دیکھیں اور وفات کے سرٹیفکیٹ کی تصویر پڑھیں۔"),
    "payment": ("platform", "Send the money to my bank account (mock bank).",
                "رقم میرے بینک اکاؤنٹ (فرضی بینک) میں بھیجیں۔"),
    "case_share": ("officer", "Let officers see my claim when a person needs to check it.",
                   "جب کسی انسان کو چیک کرنا ہو تو افسر میرا کلیم دیکھ سکیں۔"),
    "helper_access": ("helper", "Let this helper see my claim and act for me.",
                      "یہ مددگار میرا کلیم دیکھ سکے اور میری طرف سے کام کر سکے۔"),
}
CLAIM_PURPOSES = ("identity_check", "records_check", "payment", "case_share")


def has_consent(db: Session, citizen_id: int, purpose: str, grantee_user_id: int | None = None) -> bool:
    q = select(Consent.id).where(Consent.citizen_id == citizen_id, Consent.purpose == purpose,
                                 Consent.status == "active")
    if grantee_user_id is not None:
        q = q.where(Consent.grantee_user_id == grantee_user_id)
    return db.scalar(q.limit(1)) is not None


def active_purposes(db: Session, citizen_id: int) -> set[str]:
    return set(db.scalars(select(Consent.purpose).where(Consent.citizen_id == citizen_id,
                                                        Consent.status == "active")))


def require_consent(db: Session, citizen_id: int, purpose: str, actor: User, case_id: int | None = None,
                    grantee_user_id: int | None = None) -> None:
    """403 (and an audit entry) when the citizen has not given, or has withdrawn, this permission."""
    if not has_consent(db, citizen_id, purpose, grantee_user_id):
        audit.record(db, "consent.blocked", actor=actor, case_id=case_id,
                     details={"purpose": purpose, "citizen_id": citizen_id}, commit=True)
        raise HTTPException(403, f"No permission for '{purpose}'. The citizen has not given it, or has withdrawn it.")


def grant(db: Session, citizen: User, purpose: str, actor: User, helper: User | None = None) -> Consent:
    """Idempotent: granting what is already active returns the existing row."""
    if purpose not in PURPOSES:
        raise HTTPException(422, f"Unknown purpose. Choose one of: {', '.join(PURPOSES)}")
    if purpose == "helper_access" and (helper is None or helper.role != "helper"):
        raise HTTPException(422, "helper_access needs a helper account")
    q = select(Consent).where(Consent.citizen_id == citizen.id, Consent.purpose == purpose,
                              Consent.status == "active")
    if helper is not None:
        q = q.where(Consent.grantee_user_id == helper.id)
    existing = db.scalar(q)
    if existing:
        return existing
    c = Consent(citizen_id=citizen.id, purpose=purpose, grantee=PURPOSES[purpose][0],
                grantee_user_id=helper.id if helper else None, status="active")
    db.add(c)
    db.flush()
    audit.record(db, "consent.granted", actor=actor,
                 details={"consent_id": c.id, "citizen_id": citizen.id, "purpose": purpose,
                          "helper_id": helper.id if helper else None})
    return c


def withdraw(db: Session, citizen: User, consent_id: int, actor: User) -> Consent:
    c = db.get(Consent, consent_id)
    if c is None or c.citizen_id != citizen.id:
        raise HTTPException(404, "No such permission")
    if c.status == "active":
        c.status, c.withdrawn_at = "withdrawn", utcnow()
        audit.record(db, "consent.withdrawn", actor=actor,
                     details={"consent_id": c.id, "citizen_id": citizen.id, "purpose": c.purpose,
                              "helper_id": c.grantee_user_id})
    return c


def acting_citizen(db: Session, user: User, acting_for: int | None) -> User:
    """The citizen a request is about. A citizen is always herself; a helper needs an ACTIVE helper_access."""
    if user.role == "citizen":
        return user
    if user.role == "helper":
        if acting_for is None:
            raise HTTPException(400, "Choose a family first")
        if not has_consent(db, acting_for, "helper_access", grantee_user_id=user.id):
            audit.record(db, "consent.blocked", actor=user,
                         details={"purpose": "helper_access", "citizen_id": acting_for}, commit=True)
            raise HTTPException(403, "This family has not given you permission, or has withdrawn it")
        return db.get(User, acting_for)
    raise HTTPException(403, "You do not have permission for this")
