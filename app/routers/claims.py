"""The citizen's claim, step by step (a helper can do it for a family that allowed it: header X-Acting-For)."""
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as AnyUpload

from app import claims
from app.consent import acting_citizen
from app.db import get_db
from app.deps import require_role
from app.models import Case, User

router = APIRouter(prefix="/claims", tags=["Claim (citizen / helper)"])
CITIZEN = require_role("citizen", "helper")


def _ctx(db: Session, user: User, acting_for: int | None, case_id: int | None = None):
    citizen = acting_citizen(db, user, acting_for)
    if case_id is None:
        return citizen, None
    case = claims.get_case(db, user, case_id)
    if case.citizen_id != citizen.id:
        raise HTTPException(404, "No such claim")
    return citizen, case


def _upload(u) -> UploadFile | None:
    return u if isinstance(u, AnyUpload) and u.filename else None


@router.get("/purposes")
def purposes(user: User = Depends(CITIZEN)):
    """What the claim asks permission for, in English and Urdu."""
    return claims.purposes_text()


@router.get("")
def my_claims(db: Session = Depends(get_db), user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    citizen, _ = _ctx(db, user, x_acting_for)
    rows = db.scalars(select(Case).where(Case.citizen_id == citizen.id).order_by(Case.id.desc())).all()
    return [claims.citizen_view(db, c) for c in rows]


@router.get("/messages")
def my_messages(db: Session = Depends(get_db), user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    """The SMS updates sent to this citizen (mock gateway), newest first: her phone's inbox."""
    from app.models import SmsMessage
    citizen, _ = _ctx(db, user, x_acting_for)
    rows = db.scalars(select(SmsMessage).where(SmsMessage.user_id == citizen.id).order_by(SmsMessage.id.desc())).all()
    return [{"id": m.id, "kind": m.kind, "ur": m.text_ur, "en": m.text_en, "phone": m.phone, "at": m.created_at,
             "case_id": m.case_id} for m in rows]


@router.post("", status_code=201)
def start(db: Session = Depends(get_db), user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    citizen, _ = _ctx(db, user, x_acting_for)
    return claims.citizen_view(db, claims.create(db, user, citizen))


@router.get("/{case_id}")
def one(case_id: int, db: Session = Depends(get_db), user: User = Depends(CITIZEN),
        x_acting_for: int | None = Header(None)):
    _, case = _ctx(db, user, x_acting_for, case_id)
    return claims.citizen_view(db, case)


class ConsentIn(BaseModel):
    purposes: list[str]


@router.post("/{case_id}/consent")
def step_consent(case_id: int, body: ConsentIn, db: Session = Depends(get_db), user: User = Depends(CITIZEN),
                 x_acting_for: int | None = Header(None)):
    """Step 1: what the citizen allows (identity_check and records_check are needed to check a claim)."""
    citizen, case = _ctx(db, user, x_acting_for, case_id)
    return claims.citizen_view(db, claims.give_consent(db, case, user, citizen, body.purposes))


@router.post("/{case_id}/identity")
def step_identity(case_id: int, cnic: str | None = Form(None), photo: UploadFile | None = File(None),
                  db: Session = Depends(get_db), user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    """Step 2: CNIC checked with the identity registry. Optional: a photo of the front of the CNIC (AI reads it)."""
    citizen, case = _ctx(db, user, x_acting_for, case_id)
    return claims.citizen_view(db, claims.identity_step(db, case, user, citizen, cnic, _upload(photo)))


@router.post("/{case_id}/eligibility")
def step_eligibility(case_id: int, deceased_cnic: str | None = Form(None), relation: str | None = Form(None),
                     certificate: UploadFile | None = File(None), db: Session = Depends(get_db),
                     user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    """Step 3: the death record, relation and programme rules. Optional: a death certificate photo."""
    citizen, case = _ctx(db, user, x_acting_for, case_id)
    return claims.citizen_view(db, claims.eligibility_step(db, case, user, citizen, deceased_cnic, relation,
                                                           _upload(certificate)))


class DecideIn(BaseModel):
    message: str | None = None


@router.post("/{case_id}/decide")
def step_decide(case_id: int, body: DecideIn | None = None, db: Session = Depends(get_db),
                user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None),
                idempotency_key: str | None = Header(None, max_length=64)):
    """Step 4 + 5: decision (green pays at once; yellow asks for proof; red goes to an officer)."""
    citizen, case = _ctx(db, user, x_acting_for, case_id)
    claims.decide(db, case, user, citizen, (body.message if body else None), idempotency_key)
    db.refresh(case)
    return claims.citizen_view(db, case)


class AskIn(BaseModel):
    kind: str = "handoff"  # see claims.HANDOFF_KINDS


@router.post("/{case_id}/ask-officer")
def ask_officer(case_id: int, body: AskIn, db: Session = Depends(get_db), user: User = Depends(CITIZEN),
                x_acting_for: int | None = Header(None)):
    if body.kind not in claims.HANDOFF_KINDS:
        raise HTTPException(422, "kind must be one of: " + ", ".join(claims.HANDOFF_KINDS))
    _, case = _ctx(db, user, x_acting_for, case_id)
    claims.citizen_handoff(db, case, user, body.kind)
    return claims.citizen_view(db, case)


@router.post("/{case_id}/withdraw")
def withdraw(case_id: int, db: Session = Depends(get_db), user: User = Depends(CITIZEN),
             x_acting_for: int | None = Header(None)):
    _, case = _ctx(db, user, x_acting_for, case_id)
    claims.withdraw(db, case, user)
    return claims.citizen_view(db, case)
