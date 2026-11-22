"""Public API for partners: needs an X-API-Key (made by an admin on /admin). Totals and claim status
only; never names, CNICs or documents."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.apikeys import require_api_key
from app.db import get_db
from app.models import ApiKey, Case, Decision

router = APIRouter(prefix="/api/v1", tags=["Public API (X-API-Key)"])
EVALUATION = Path(__file__).resolve().parents[2] / "data" / "evaluation.json"


def _log(db: Session, key: ApiKey, what: str):
    audit.record(db, f"api.{what}", actor_role=audit.ACTOR_API_KEY, details={"key_id": key.id, "key": key.prefix},
                 commit=True)


@router.get("/ping")
def ping(key: ApiKey = Depends(require_api_key)):
    """Check that your key works."""
    return {"status": "ok", "key_name": key.name, "prototype": True}


@router.get("/stats")
def stats(key: ApiKey = Depends(require_api_key), db: Session = Depends(get_db)):
    """Claims by status and decisions by outcome. Totals only."""
    _log(db, key, "stats")
    return {"claims_by_status": dict(db.execute(select(Case.status, func.count()).group_by(Case.status)).all()),
            "decisions_by_outcome": dict(db.execute(select(Decision.outcome, func.count()).group_by(Decision.outcome)).all())}


@router.get("/claims/{case_id}/status")
def claim_status(case_id: int, key: ApiKey = Depends(require_api_key), db: Session = Depends(get_db)):
    """Where one claim is (no personal data)."""
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "No such claim")
    _log(db, key, "claim_status")
    return {"case_id": case.id, "status": case.status, "outcome": case.outcome, "paid": case.paid_at is not None}


@router.get("/evaluation")
def evaluation(key: ApiKey = Depends(require_api_key), db: Session = Depends(get_db)):
    """The latest evaluation numbers (auto-approved / asked for proof / sent to a person / wrongly blocked)."""
    if not EVALUATION.exists():
        raise HTTPException(404, "No evaluation yet")
    _log(db, key, "evaluation")
    return json.loads(EVALUATION.read_text(encoding="utf-8"))["summary"]
