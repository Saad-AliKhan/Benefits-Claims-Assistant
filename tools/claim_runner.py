# -*- coding: utf-8 -*-
"""Runs one fake claim scenario (data/scenarios.json) through the REAL claim flow (app/claims.py), as the
citizen would with plain buttons, optionally with SPECIMEN photos read by the OCR engine.
Used by the demo seed (scripts/seed.py), the evaluation (tools/evaluate_claims.py) and the tests."""
import io
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app import claims
from app.consent import CLAIM_PURPOSES
from app.models import Case, User
from app.security import hash_password

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data" / "scenarios.json"
SPECIMENS = ROOT / "data" / "specimens"
DEMO_PASSWORD = "demo1234"
_HASH = {}


def scenarios() -> list[dict]:
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))


def password_hash() -> str:
    if "h" not in _HASH:  # bcrypt is slow on purpose: hash once per run
        _HASH["h"] = hash_password(DEMO_PASSWORD)
    return _HASH["h"]


def ensure_user(db: Session, email: str, name: str, role: str, cnic: str | None = None) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, full_name=name, role=role, cnic=cnic, password_hash=password_hash())
        db.add(u)
        db.commit()
    return u


def claimant(db: Session, s: dict) -> User:
    u = ensure_user(db, s["email"], s["claimant"]["name"], "citizen", s["claimant"]["cnic"])
    if s["claimant"].get("phone") and not u.phone:
        u.phone = s["claimant"]["phone"]
        db.commit()
    return u


def _photo(path: Path | None):
    if path is None or not path.exists():
        return None
    return UploadFile(io.BytesIO(path.read_bytes()), filename=path.name, headers=Headers({"content-type": "image/jpeg"}))


def run(db: Session, s: dict, documents: bool = False, decide: bool = True) -> Case:
    """One claim, start to finish (or until a person must act). documents=True adds the SPECIMEN photos
    from data/specimens/ (python -m tools.specimen_documents)."""
    citizen = claimant(db, s)
    case = claims.create(db, citizen, citizen)
    claims.give_consent(db, case, citizen, citizen, list(CLAIM_PURPOSES))
    cnic_photo = _photo(SPECIMENS / f"{s['id']}_cnic.jpg") if documents else None
    cert_photo = _photo(SPECIMENS / f"{s['id']}_certificate.jpg") if documents else None
    claims.identity_step(db, case, citizen, citizen, s["claimant"]["cnic"], cnic_photo)
    claims.eligibility_step(db, case, citizen, citizen, s["deceased_cnic"], s["relation"], cert_photo)
    if decide:
        claims.decide(db, case, citizen, citizen, s.get("message"), None)
    db.refresh(case)
    return case
