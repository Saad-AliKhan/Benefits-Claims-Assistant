"""Officer queue: claims the system sent to a person, sorted by priority and confidence.
Officers only see a claim while the citizen shares it (consent 'case_share')."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, claims, documents
from app.consent import has_consent
from app.db import get_db
from app.deps import require_role
from app.models import Case, Consent, Document, User

router = APIRouter(prefix="/officer", tags=["Officer"])
STAFF = require_role("officer", "admin")
QUEUE = ("escalated", "assigned", "payment_failed", "waiting_citizen")
HOW_SORTED = {
    "priority": "Priority, highest first: red 70, payment problem 60, waiting for the citizen 30; up to +20 for low "
                "confidence and +10 for a large amount. Ties: oldest first.",
    "confidence": "Lowest confidence first (the claims the system is least sure about).",
    "oldest": "Waiting longest first.",
}


def _mask(cnic: str | None) -> str | None:
    return f"{cnic[:5]}-*******-{cnic[-1]}" if cnic and len(cnic) >= 13 else None


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def priority(case: Case, max_auto: int) -> int:
    base = {"escalated": 70, "assigned": 70, "payment_failed": 60}.get(case.status, 30)
    conf = case.confidence if case.confidence is not None else 0.0
    return round(base + (1 - max(0.0, min(1.0, conf))) * 20 + (min(case.amount / max_auto, 1.0) * 10 if max_auto else 0))


@router.get("/queue")
def queue(sort: str = Query("priority", pattern="^(priority|confidence|oldest)$"),
          mine: bool = False, include_waiting: bool = True,
          db: Session = Depends(get_db), user: User = Depends(STAFF)):
    shared = select(Consent.citizen_id).where(Consent.purpose == "case_share", Consent.status == "active")
    statuses = QUEUE if include_waiting else QUEUE[:-1]
    q = select(Case, User).join(User, User.id == Case.citizen_id).where(Case.status.in_(statuses))
    if user.role == "officer":
        q = q.where(Case.citizen_id.in_(shared))
    rows = db.execute(q).all()
    now = datetime.now(timezone.utc)
    items = []
    for case, citizen in rows:
        if mine and case.assigned_officer_id != user.id:
            continue
        d = claims.latest_decision(db, case.id)
        max_auto = ((d.trace if d else {}).get("thresholds_used") or {}).get("max_auto_amount", 50000)
        problems = [c for c in (d.trace["checks"] if d else []) if c["severity"] != "green"]
        problems.sort(key=lambda c: (0 if c["severity"] == "red" else 1))
        items.append({
            "case_id": case.id, "status": case.status, "outcome": case.outcome, "confidence": case.confidence,
            "amount": case.amount, "priority": priority(case, max_auto), "citizen_name": citizen.full_name,
            "citizen_cnic": _mask(citizen.cnic), "assigned_to_me": case.assigned_officer_id == user.id,
            "assigned": case.assigned_officer_id is not None, "rule_version": d.rule_version if d else None,
            "waiting_on": "citizen" if case.status == "waiting_citizen" else "officer",
            "age_minutes": int((now - _aware(case.updated_at)).total_seconds() // 60),
            "headline": problems[0]["detail"] if problems else ("Payment failed" if case.status == "payment_failed" else ""),
        })
    keys = {"priority": lambda i: (-i["priority"], i["confidence"] or 0, -i["age_minutes"]),
            "confidence": lambda i: (i["confidence"] if i["confidence"] is not None else -1, -i["priority"]),
            "oldest": lambda i: (-i["age_minutes"], -i["priority"])}
    items.sort(key=keys[sort])
    counts = {s: sum(i["status"] == s for i in items) for s in QUEUE}
    return {"items": items, "counts": counts, "sort": sort, "how_sorted": HOW_SORTED[sort]}


@router.get("/cases/{case_id}")
def case_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(STAFF)):
    case = claims.get_case(db, user, case_id)
    citizen = db.get(User, case.citizen_id)
    d = claims.latest_decision(db, case.id)
    docs = db.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.id.desc())).all()
    audit.record(db, "case.viewed", actor=user, case_id=case.id, commit=True)
    return {
        "case": {"id": case.id, "status": case.status, "step": case.step, "amount": case.amount, "benefit": case.benefit,
                 "outcome": case.outcome, "confidence": case.confidence, "assigned_officer_id": case.assigned_officer_id,
                 "assigned_to_me": case.assigned_officer_id == user.id, "payment_ref": case.payment_ref,
                 "created_at": case.created_at, "data": case.data},
        "citizen": {"name": citizen.full_name, "cnic": _mask(citizen.cnic)},
        "decision": None if d is None else {"id": d.id, "outcome": d.outcome, "confidence": d.confidence,
                                            "rule_version": d.rule_version, "reason_user": d.reason_user,
                                            "created_at": d.created_at, "trace": d.trace},
        "documents": [{"id": x.id, "doc_type": x.doc_type, "source": x.source, "outcome": x.outcome,
                       "action": x.action, "overall_confidence": x.overall_confidence,
                       "flags": (x.ocr_json or {}).get("flags", []),
                       "fields": (x.ocr_json or {}).get("fields") or ((x.ocr_json or {}).get("ocr") or {}).get("fields"),
                       "photo_url": f"/officer/documents/{x.id}/photo", "created_at": x.created_at} for x in docs],
        "notes": claims.notes(db, case.id),
        "shared_with_officers": has_consent(db, case.citizen_id, "case_share"),
    }


@router.post("/cases/{case_id}/assign")
def take(case_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("officer"))):
    """Take the claim: it becomes mine."""
    claims.officer_assign(db, claims.get_case(db, user, case_id, "assign"), user)
    return {"ok": True}


class DecisionIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.post("/cases/{case_id}/decision")
def officer_decision(case_id: int, body: DecisionIn, db: Session = Depends(get_db),
                     user: User = Depends(require_role("officer"))):
    """Approve (then the payment is sent) or reject (a note is required). Only an officer can do this."""
    case = claims.get_case(db, user, case_id, "decide")
    claims.officer_decide(db, case, user, body.approve, body.note)
    db.refresh(case)
    return {"case_id": case.id, "status": case.status, "payment_ref": case.payment_ref}


@router.post("/cases/{case_id}/retry-payment")
def retry_payment(case_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("officer"))):
    case = claims.get_case(db, user, case_id, "pay")
    if case.status not in ("approved", "payment_failed"):
        raise HTTPException(409, "Only an approved claim, or one whose payment failed, can be paid")
    claims.pay(db, case, user)
    db.commit()
    return {"case_id": case.id, "status": case.status, "payment_ref": case.payment_ref}


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=500)


@router.post("/cases/{case_id}/notes")
def add_note(case_id: int, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(STAFF)):
    case = claims.get_case(db, user, case_id, "note")
    claims._note(db, case, body.note.strip(), user)
    db.commit()
    return claims.notes(db, case.id)[-1]


@router.get("/documents/{document_id}/photo")
def document_photo(document_id: int, db: Session = Depends(get_db), user: User = Depends(STAFF)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Photo not found")
    claims.get_case(db, user, doc.case_id, "view_photo")
    path = documents.photo_path(doc)
    if path is None:
        raise HTTPException(404, "Photo not found")
    audit.record(db, "document.photo_viewed", actor=user, case_id=doc.case_id, details={"document_id": doc.id},
                 commit=True)
    return FileResponse(path)
