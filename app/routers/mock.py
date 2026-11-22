"""The three fake external APIs over HTTP (for /docs and for staff). The claim flow calls the same
functions directly (app/mock_services/api.py). All data is invented."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.mock_services import api
from app.models import User

router = APIRouter(prefix="/mock", tags=["Mock services (fake NADRA / records / bank)"])
STAFF = require_role("officer", "admin", "auditor")
CNIC = r"^\d{5}-\d{7}-\d$"
NOTICE = "MOCK: fake data for a prototype"


def _found(x, what):
    if x is None:
        raise HTTPException(404, f"No {what} (mock)")
    return {"notice": NOTICE, **x} if isinstance(x, dict) else x


@router.get("/identity/{cnic}")
def identity(cnic: str = Path(..., pattern=CNIC), user: User = Depends(STAFF)):
    """Identity registry (pretends to be NADRA): one person by CNIC."""
    return _found(api.identity(cnic), "identity record for this CNIC")


@router.get("/identity")
def identity_search(name: str = Query(..., min_length=2), user: User = Depends(STAFF)):
    """Search by name: shows why the CNIC matters (duplicate names, spelling variants)."""
    return {"notice": NOTICE, "results": api.identity_search(name)}


@router.get("/records/death/{deceased_cnic}")
def death_record(deceased_cnic: str = Path(..., pattern=CNIC), user: User = Depends(STAFF)):
    """Records (pretends to be CRMS): the death record of a person."""
    return _found(api.death_record(deceased_cnic), "death record")


@router.get("/records/certificate/{tracking_id}")
def certificate(tracking_id: str, user: User = Depends(STAFF)):
    """Records: a death certificate by its tracking id (printed on the certificate)."""
    return _found(api.certificate(tracking_id), "certificate with this tracking id")


@router.get("/programme/{cnic}")
def programme(cnic: str = Path(..., pattern=CNIC), user: User = Depends(STAFF)):
    return _found(api.programme(cnic), "programme record")


@router.get("/payment/account/{cnic}")
def account(cnic: str = Path(..., pattern=CNIC), user: User = Depends(STAFF)):
    """Payment (pretends to be a bank): the account for a CNIC."""
    return _found(api.account(cnic), "bank account")


class TransferIn(BaseModel):
    cnic: str = Field(..., pattern=CNIC)
    amount: int = Field(..., gt=0, le=1_000_000)
    idempotency_key: str = Field(..., min_length=8, max_length=80)


@router.post("/payment/transfer")
def transfer(body: TransferIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Pretend to send money (admin only, for testing). The same key never pays twice."""
    try:
        t = api.transfer(db, body.cnic, body.amount, body.idempotency_key)
    except api.PaymentRefused as e:
        raise HTTPException(422, str(e))
    db.commit()
    return t
