"""The mock services as plain functions (what an API client for NADRA / CRMS / a bank would offer)."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mock_services import store
from app.models import MockTransfer

CNIC_RX = re.compile(r"^\d{5}-\d{7}-\d$")


def norm_cnic(value: str | None) -> str | None:
    d = re.sub(r"\D", "", value or "")
    return f"{d[:5]}-{d[5:12]}-{d[12]}" if len(d) == 13 else None


# ---------------- identity (NADRA, mock)
def identity(cnic: str) -> dict | None:
    return store.public(store.identity_by_cnic().get(norm_cnic(cnic) or ""))


def identity_search(name: str, limit: int = 10) -> list[dict]:
    words = name.lower().split()
    out = []
    for rec in store.identity_by_cnic().values():
        if all(w in rec["full_name"].lower() for w in words):
            out.append(store.public(rec))
        if len(out) >= limit:
            break
    return out


# ---------------- records (CRMS, mock)
def death_record(deceased_cnic: str) -> dict | None:
    return store.public(store.death_records().get(norm_cnic(deceased_cnic) or ""))


def certificate(tracking_id: str) -> dict | None:
    for r in store.death_records().values():
        if r["tracking_id"] == str(tracking_id).strip():
            return store.public(r)
    return None


def deaths_for_applicant(cnic: str) -> list[dict]:
    """Death records where this person is the applicant (or the spouse): lets a widow with no
    certificate in hand be found by her OWN CNIC, without typing her husband's."""
    c = norm_cnic(cnic)
    return [store.public(r) for r in store.death_records().values() if r.get("applicant_cnic") == c]


# ---------------- telecom (mock PTA / operator: who a SIM is registered to)
def norm_phone(value: str | None) -> str | None:
    d = re.sub(r"\D", "", value or "")
    if d.startswith("92"):
        d = "0" + d[2:]
    return f"{d[:4]}-{d[4:]}" if len(d) == 11 and d.startswith("03") else None


def sim_owner(phone: str) -> dict | None:
    return store.telco_by_phone().get(norm_phone(phone) or "")


# ---------------- programme
def programme(cnic: str) -> dict | None:
    return store.programme_by_cnic().get(norm_cnic(cnic) or "")


# ---------------- payment (bank / Raast, mock)
def account(cnic: str) -> dict | None:
    return store.accounts_by_cnic().get(norm_cnic(cnic) or "")


class PaymentRefused(Exception):
    pass


def transfer(db: Session, cnic: str, amount: int, idempotency_key: str) -> dict:
    """Pretend to send money. The same idempotency key never pays twice (retries on a weak connection)."""
    prior = db.scalar(select(MockTransfer).where(MockTransfer.idempotency_key == idempotency_key))
    if prior is not None:
        return {"transfer_id": prior.transfer_id, "cnic": prior.cnic, "amount": prior.amount,
                "status": prior.status, "replayed": True}
    acc = account(cnic)
    if acc is None:
        raise PaymentRefused("no bank account for this CNIC")
    if acc.get("status") != "active":
        raise PaymentRefused(f"bank account is {acc.get('status')}")
    count = db.scalar(select(MockTransfer.id).order_by(MockTransfer.id.desc()).limit(1)) or 0
    t = MockTransfer(transfer_id=f"MOCKPAY-{count + 1:06d}", cnic=norm_cnic(cnic), amount=amount,
                     idempotency_key=idempotency_key, status="simulated_success")
    db.add(t)
    db.flush()
    return {"transfer_id": t.transfer_id, "cnic": t.cnic, "amount": amount, "status": t.status, "replayed": False,
            "note": "Simulated. No real money moved."}
