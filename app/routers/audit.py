"""Auditor (read-only): the full audit log, consent records, decision traces, evaluation numbers."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import AuditLog, Case, Consent, Decision, User

router = APIRouter(prefix="/audit", tags=["Auditor (read-only)"])
AUDITOR = require_role("auditor", "admin")
EVALUATION = Path(__file__).resolve().parents[2] / "data" / "evaluation.json"


@router.get("/log")
def audit_log(action: str | None = Query(None, description="Action name or its start, e.g. 'claim.'"),
              actor_role: str | None = None, case_id: int | None = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), user: User = Depends(AUDITOR)):
    """Every recorded action, newest first. There is no way to edit or delete an entry."""
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if actor_role:
        q = q.where(AuditLog.actor_role == actor_role)
    if case_id is not None:
        q = q.where(AuditLog.case_id == case_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.limit(limit).offset(offset)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.actor_id for r in rows if r.actor_id})))}
    return {"total": total, "items": [{"id": r.id, "at": r.created_at, "actor": names.get(r.actor_id),
                                       "actor_role": r.actor_role, "action": r.action, "case_id": r.case_id,
                                       "details": r.details} for r in rows]}


@router.get("/consents")
def consents(citizen_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(AUDITOR)):
    q = select(Consent).order_by(Consent.id.desc())
    if citizen_id is not None:
        q = q.where(Consent.citizen_id == citizen_id)
    return [{"id": c.id, "citizen_id": c.citizen_id, "purpose": c.purpose, "grantee": c.grantee,
             "helper_id": c.grantee_user_id, "status": c.status, "granted_at": c.granted_at,
             "withdrawn_at": c.withdrawn_at} for c in db.scalars(q)]


@router.get("/decisions")
def decisions(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(AUDITOR)):
    """Recent decisions with the FULL trace: inputs, every check, thresholds and rule version."""
    rows = db.scalars(select(Decision).order_by(Decision.id.desc()).limit(limit)).all()
    return [{"id": d.id, "case_id": d.case_id, "outcome": d.outcome, "confidence": d.confidence,
             "rule_version": d.rule_version, "reason_user": d.reason_user, "created_at": d.created_at,
             "trace": d.trace} for d in rows]


@router.get("/cases/{case_id}")
def case_trace(case_id: int, db: Session = Depends(get_db), user: User = Depends(AUDITOR)):
    """Everything about one claim: its data, every decision and every logged action, in order."""
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "No such claim")
    ds = db.scalars(select(Decision).where(Decision.case_id == case_id).order_by(Decision.id)).all()
    log = db.scalars(select(AuditLog).where(AuditLog.case_id == case_id).order_by(AuditLog.id)).all()
    return {"case": {"id": case.id, "status": case.status, "amount": case.amount, "outcome": case.outcome,
                     "confidence": case.confidence, "payment_ref": case.payment_ref, "data": case.data},
            "decisions": [{"id": d.id, "outcome": d.outcome, "confidence": d.confidence, "rule_version": d.rule_version,
                           "created_at": d.created_at, "trace": d.trace} for d in ds],
            "timeline": [{"at": a.created_at, "actor_role": a.actor_role, "action": a.action, "details": a.details}
                         for a in log]}


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(AUDITOR)):
    by_status = dict(db.execute(select(Case.status, func.count()).group_by(Case.status)).all())
    by_outcome = dict(db.execute(select(Decision.outcome, func.count()).group_by(Decision.outcome)).all())
    return {"cases_by_status": by_status, "decisions_by_outcome": by_outcome,
            "audit_entries": db.scalar(select(func.count(AuditLog.id)))}


@router.get("/evaluation")
def evaluation(user: User = Depends(AUDITOR)):
    """The latest evaluation run (python -m tools.evaluate_claims)."""
    if not EVALUATION.exists():
        raise HTTPException(404, "No evaluation yet. Run: python -m tools.evaluate_claims")
    return json.loads(EVALUATION.read_text(encoding="utf-8"))
