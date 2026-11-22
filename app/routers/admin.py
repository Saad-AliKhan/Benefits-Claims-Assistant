"""Admin: the rule editor (every change is a new version; the next decision uses it), API keys, users."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import rules
from app.apikeys import create_key, revoke_key
from app.db import get_db
from app.deps import require_role
from app.models import ApiKey, User

router = APIRouter(prefix="/admin", tags=["Admin"])
ADMIN = require_role("admin")

RULE_HELP = {
    "auto_approve_min_confidence": "At or above: the system may act alone (green).",
    "human_review_below_confidence": "Below: a person decides (red). Between the two: ask for proof (yellow).",
    "max_auto_amount": "PKR. Above this, a person must approve whatever the confidence.",
    "name_match_auto_min": "Name similarity for a confident match.",
    "name_match_review_min": "Name similarity for a near match (a person checks).",
    "scam_block_min": "Scam probability at or above: warn the citizen, a person checks.",
    "doc_blur_min": "Fallback reader only: sharpness below this asks for a new photo.",
    "ocr_min_confidence": "Document reader confidence below this asks for a new photo.",
    "max_monthly_income": "PKR per month. Above this the household is not eligible (a person confirms).",
    "late_registration_days": "A death entered this many days late goes to a person.",
}


def _out(row) -> dict:
    return {"version": row.version, "config": row.config, "note": row.note, "created_by_id": row.created_by_id,
            "created_at": row.created_at}


@router.get("/rules")
def active_rules(db: Session = Depends(get_db), user: User = Depends(require_role("admin", "auditor", "officer"))):
    active = rules.get_active(db)
    return {**_out(active), "limits": rules.LIMITS, "help": RULE_HELP}


@router.get("/rules/history")
def rule_history(db: Session = Depends(get_db), user: User = Depends(require_role("admin", "auditor"))):
    return [_out(r) for r in rules.list_versions(db)]


class RuleChange(BaseModel):
    changes: dict[str, float]
    note: str = Field(default="", max_length=300)


@router.post("/rules")
def change_rules(body: RuleChange, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Save a NEW version. Old versions are never edited; decisions record the version they used."""
    if not body.changes:
        raise HTTPException(422, "Nothing to change")
    try:
        changes = {k: int(v) if float(v).is_integer() and abs(v) >= 2 else v for k, v in body.changes.items()}
        row = rules.create_version(db, changes, user.id, user.role, body.note)
    except rules.RuleError as e:
        raise HTTPException(422, str(e))
    return _out(row)


@router.post("/rules/rollback/{version}")
def rollback(version: int, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Go back to an old version (saved as a new version, so history is never lost)."""
    old = rules.get_version(db, version)
    if old is None:
        raise HTTPException(404, "No such version")
    try:
        row = rules.create_version(db, dict(old.config), user.id, user.role, f"rollback to version {version}")
    except rules.RuleError as e:
        raise HTTPException(422, str(e))
    return _out(row)


class KeyCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@router.post("/api-keys", status_code=201)
def new_key(data: KeyCreate, admin: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """Create a key for the public API. Copy `api_key` now: it is never shown again."""
    record, plaintext = create_key(db, data.name, admin)
    return {**KeyOut.model_validate(record).model_dump(), "api_key": plaintext}


@router.get("/api-keys", response_model=list[KeyOut])
def list_keys(admin: User = Depends(ADMIN), db: Session = Depends(get_db)):
    return db.scalars(select(ApiKey).order_by(ApiKey.id.desc())).all()


@router.post("/api-keys/{key_id}/revoke", response_model=KeyOut)
def revoke(key_id: int, admin: User = Depends(ADMIN), db: Session = Depends(get_db)):
    record = revoke_key(db, key_id, admin)
    if record is None:
        raise HTTPException(404, "No such API key")
    return record


@router.get("/users")
def users(admin: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.full_name, "email": u.email, "role": u.role, "active": u.is_active}
            for u in db.scalars(select(User).order_by(User.role, User.id))]
