"""AI tools on their own (outside a claim): scam check, document reading, name match."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import ai_engines, audit, documents, rules, scam_classifier
from app.db import get_db
from app.deps import require_role
from app.models import User
from app.name_match import match_name

router = APIRouter(prefix="/ai", tags=["AI tools"])


class ScamCheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/scam-check")
def scam_check(body: ScamCheckIn, db: Session = Depends(get_db),
               user: User = Depends(require_role("citizen", "helper", "officer", "admin", "auditor"))):
    """Urdu / Roman Urdu message -> scam | safe | unsure, with a probability (ACTIVE rule version)."""
    active = rules.get_active(db)
    try:
        result = scam_classifier.classify(body.text, active.config, active.version)
    except scam_classifier.ModelMissing as e:
        raise HTTPException(503, str(e))
    audit.record(db, "ai.scam_check", actor=user,
                 details={"label": result["label"], "action": result["action"],
                          "scam_probability": result["scam_probability"], "rule_version": active.version,
                          "text_length": len(body.text)}, commit=True)  # the message itself is not stored
    return result


@router.get("/scam-metrics")
def scam_metrics(user: User = Depends(require_role("auditor", "admin", "officer"))):
    m = scam_classifier.load_metrics()
    if m is None:
        raise HTTPException(404, "No metrics yet. Run: python -m scripts.train_scam")
    return m


@router.post("/doc-check")
def doc_check(file: UploadFile = File(...), claimed_cnic: str | None = Form(None),
              doc_type: str = Form("cnic", pattern="^(cnic|death_certificate)$"),
              db: Session = Depends(get_db), user: User = Depends(require_role("citizen", "helper", "officer", "admin"))):
    """Read one document photo (not attached to a claim; nothing stored)."""
    data = documents.read_upload(file)
    active = rules.get_active(db)
    rid = ai_engines.new_request_id(f"check-{doc_type}")
    result = documents.read(doc_type, data, file, active.config, active.version, claimed_cnic, rid)
    documents.audit_ocr(db, user, doc_type, result, rid, active.version)
    db.commit()
    return result


class Candidate(BaseModel):
    name: str
    cnic: str | None = None


class NameMatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cnic: str | None = None
    candidates: list[Candidate] = Field(max_length=200)


@router.post("/name-match")
def name_match(body: NameMatchIn, db: Session = Depends(get_db),
               user: User = Depends(require_role("officer", "admin", "auditor"))):
    active = rules.get_active(db)
    result = match_name(body.name, body.cnic, [c.model_dump() for c in body.candidates], active.config, active.version)
    audit.record(db, "ai.name_match", actor=user, details={"status": result["status"], "action": result["action"],
                                                           "confidence": result["confidence"]}, commit=True)
    return result
