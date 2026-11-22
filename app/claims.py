# -*- coding: utf-8 -*-
"""The claim, step by step. Every step is saved on the server as soon as it is done, so a dropped
connection never loses work (Case.step says where to continue).

    steps:   consent -> identity -> eligibility -> decide -> done
    status:  draft -> approved -> paid                         (green: the system acts alone)
                   -> waiting_citizen -> (more proof) -> ...   (yellow: ask for proof)
                   -> escalated -> assigned -> approved -> paid / rejected   (red: a person decides)
             payment_failed -> (officer) -> paid;  withdrawn (citizen, any time before a decision is final)

The checks use only fake services (app/mock_services) and the AI in this app. Photos are optional
evidence on top of the typed details: a claim can be completed with plain buttons and no AI.
"""
from datetime import date

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, decision_engine, documents, rules, scam_classifier, sms
from app.config import settings
from app.consent import CLAIM_PURPOSES, PURPOSES, active_purposes, grant, has_consent, require_consent
from app.mock_services import api as mock
from app.models import AuditLog, Case, Decision, User, utcnow
from app.name_match import match_name

OPEN = ("draft", "waiting_citizen", "escalated", "assigned", "approved", "payment_failed")
FINAL = ("paid", "rejected", "withdrawn")
OFFICER_STATUSES = ("escalated", "assigned", "payment_failed", "approved", "paid", "rejected")
ELIGIBLE_RELATIONS = ("Wife", "Widow", "Husband", "Widower")
REQUIRED_REGISTRY_FIELDS = ("full_name", "dob", "father_or_husband_name", "gender")
PER_DEPENDANT_PKR, MAX_DEPENDANTS = 10000, 5


# ---------------------------------------------------------------- access
def can_see(db: Session, user: User, case: Case) -> bool:
    if user.role in ("admin", "auditor"):
        return True
    if user.role == "citizen":
        return case.citizen_id == user.id
    if user.role == "helper":
        return has_consent(db, case.citizen_id, "helper_access", grantee_user_id=user.id)
    if user.role == "officer":  # only claims a person must look at, and only while the citizen shares them
        return case.status in OFFICER_STATUSES + ("waiting_citizen",) and has_consent(db, case.citizen_id, "case_share")
    return False


def get_case(db: Session, user: User, case_id: int, action: str = "read") -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "No such claim")
    if not can_see(db, user, case):
        audit.record(db, "case.access_denied", actor=user, case_id=case.id, details={"attempted": action}, commit=True)
        # citizens and helpers get 404 (no probing of other people's claims); staff get the real reason
        if user.role in ("citizen", "helper"):
            raise HTTPException(404, "No such claim")
        raise HTTPException(403, "The citizen has not shared this claim with officers, or has withdrawn it")
    return case


def _citizen_of(db: Session, case: Case) -> User:
    return db.get(User, case.citizen_id)


def _need_step(case: Case, *allowed: str):
    if case.status in FINAL:
        raise HTTPException(409, f"This claim is {case.status}")
    if case.status in ("escalated", "assigned", "approved", "payment_failed"):
        raise HTTPException(409, "An officer or the payment step has this claim now")
    if case.step not in allowed:
        raise HTTPException(409, f"Finish the '{case.step}' step first")


def _save(db: Session, case: Case, key: str, value: dict, next_step: str):
    data = dict(case.data or {})
    data[key] = value
    case.data = data  # new dict so SQLAlchemy sees the change
    if case.step not in ("decide", "proof") or next_step == "decide":
        case.step = next_step


# ---------------------------------------------------------------- create + consent
def create(db: Session, user: User, citizen: User) -> Case:
    open_case = db.scalar(select(Case.id).where(Case.citizen_id == citizen.id, Case.status.in_(OPEN)))
    if open_case is not None:
        raise HTTPException(409, f"You already have an open claim (number {open_case})")
    case = Case(citizen_id=citizen.id, created_by_id=user.id, benefit=settings.benefit_name,
                amount=settings.benefit_amount, status="draft", step="consent", data={})
    db.add(case)
    db.flush()
    audit.record(db, "claim.created", actor=user, case_id=case.id,
                 details={"citizen_id": citizen.id, "on_behalf": user.id != citizen.id})
    db.commit()
    db.refresh(case)
    return case


def give_consent(db: Session, case: Case, user: User, citizen: User, purposes: list[str]) -> Case:
    _need_step(case, "consent", "identity", "eligibility", "decide", "proof")
    unknown = set(purposes) - set(CLAIM_PURPOSES)
    if unknown:
        raise HTTPException(422, f"Unknown purposes: {sorted(unknown)}")
    for p in purposes:
        grant(db, citizen, p, actor=user)
    missing = [p for p in ("identity_check", "records_check") if p not in purposes and not has_consent(db, citizen.id, p)]
    if missing:
        raise HTTPException(422, "To check the claim we need at least: " + ", ".join(missing))
    _save(db, case, "consent", {"purposes": sorted(active_purposes(db, citizen.id) & set(CLAIM_PURPOSES)),
                                "at": utcnow().isoformat()}, "identity")
    audit.record(db, "claim.step_done", actor=user, case_id=case.id, details={"step": "consent", "purposes": purposes})
    db.commit()
    db.refresh(case)
    return case


# ---------------------------------------------------------------- identity
def check_identity(cnic: str, account_name: str, photo: dict | None, cfg: dict, version, phone: str | None = None) -> dict:
    """Registry check of the claimant (+ CNIC photo, + who her SIM is registered to). auto | ask_more | human."""
    out = _check_identity(cnic, account_name, photo, cfg, version)
    if phone:
        owner = mock.sim_owner(phone)
        out["sim"] = "unknown" if owner is None else ("hers" if owner["cnic"] == cnic else "someone_else")
        if out["sim"] == "someone_else" and out["action"] != "ask_more":
            out.update(action="human", code="id_human", confidence=min(out["confidence"], 0.4),
                       detail=out["detail"] + " The mobile number she uses is registered to another person's CNIC.")
        elif out["sim"] == "hers":
            out["detail"] += " Her mobile number is registered to her own CNIC."
    return out


def _check_identity(cnic: str, account_name: str, photo: dict | None, cfg: dict, version) -> dict:
    rec = mock.identity(cnic)
    out = {"cnic": cnic, "registry_found": rec is not None, "photo_used": photo is not None}
    photo_ok = bool(photo and photo["action"] == "auto"
                    and mock.norm_cnic((photo.get("ocr") or {}).get("fields", {}).get("cnic")) == cnic)
    out["photo_confirms_cnic"] = photo_ok
    if rec is None:
        if photo_ok:
            return {**out, "action": "human", "code": "id_human", "confidence": 0.5,
                    "detail": "The CNIC photo was read, but this number is not in the identity registry."}
        return {**out, "action": "ask_more", "code": "id_not_found", "confidence": 0.0,
                "detail": "This CNIC is not in the identity registry."}
    out["registry"] = {"full_name": rec["full_name"], "life_status": rec["life_status"],
                       "missing_fields": [f for f in REQUIRED_REGISTRY_FIELDS if not rec.get(f)]}
    if rec["life_status"] != "alive":
        return {**out, "action": "human", "code": "id_human", "confidence": 0.3,
                "detail": "The identity registry records this CNIC holder as deceased."}
    nm = match_name(account_name, cnic, [{"name": rec["full_name"], "cnic": cnic}], cfg, version)
    out["name_match"] = {"status": nm["status"], "confidence": nm["confidence"], "action": nm["action"]}
    conf = float(nm["confidence"])
    if nm["action"] != "auto":
        return {**out, "action": "human", "code": "id_human", "confidence": conf,
                "detail": f"Name on the account ('{account_name}') vs the registry ('{rec['full_name']}'): {nm['status']}."}
    if out["registry"]["missing_fields"]:
        if photo_ok:
            conf = min(conf, float(photo["confidence"]))
            return {**out, "action": "auto", "code": None, "confidence": round(conf, 4),
                    "detail": "Registry record is incomplete (" + ", ".join(out["registry"]["missing_fields"])
                              + "); the CNIC photo confirms the number."}
        return {**out, "action": "ask_more", "code": "id_incomplete", "confidence": conf,
                "detail": "Registry record is missing: " + ", ".join(out["registry"]["missing_fields"]) + "."}
    if photo_ok:
        conf = min(conf, float(photo["confidence"]))
    return {**out, "action": "auto", "code": None, "confidence": round(conf, 4),
            "detail": f"CNIC found; name matches the registry ({nm['status']}, {nm['confidence']:.2f})."}


def identity_step(db: Session, case: Case, user: User, citizen: User, cnic: str | None,
                  photo: UploadFile | None) -> Case:
    _need_step(case, "identity", "eligibility", "decide", "proof")
    require_consent(db, citizen.id, "identity_check", user, case.id)
    cnic = mock.norm_cnic(cnic or citizen.cnic)
    if cnic is None:
        raise HTTPException(422, "Enter the 13-digit CNIC number")
    if citizen.cnic and mock.norm_cnic(citizen.cnic) != cnic:
        raise HTTPException(409, "This is not the CNIC on your account. To change it, ask an officer.")
    if not citizen.cnic:
        citizen.cnic = cnic
    active = rules.get_active(db)
    doc = None
    if photo is not None and photo.filename:
        doc, _ = documents.read_and_store(db, case, user, "cnic", photo, active.config, active.version, cnic)
    else:
        doc = documents.latest(db, case.id, "cnic")
    result = check_identity(cnic, citizen.full_name, doc, active.config, active.version, citizen.phone)
    _save(db, case, "identity", {"input": {"cnic": cnic}, "result": result}, "eligibility")
    audit.record(db, "claim.step_done", actor=user, case_id=case.id,
                 details={"step": "identity", "action": result["action"], "registry_found": result["registry_found"],
                          "photo": result["photo_used"]})
    db.commit()
    db.refresh(case)
    return case


# ---------------------------------------------------------------- eligibility
def _days(a: str | None, b: str | None) -> int | None:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def check_eligibility(db: Session, case: Case, claimant_cnic: str, deceased_cnic: str, relation: str,
                      certificate: dict | None, cfg: dict) -> dict:
    problems = []

    def problem(code, action, detail):
        problems.append({"code": code, "action": action, "detail": detail,
                         "user_code": "record_missing" if action == "ask_more" else "elig_human"})

    record = mock.death_record(deceased_cnic)
    person = mock.identity(deceased_cnic)
    prog = mock.programme(claimant_cnic)
    out = {"deceased_cnic": deceased_cnic, "relation": relation, "record_found": record is not None,
           "certificate_photo": certificate is not None}
    if person is None:
        problem("deceased_unknown", "human", "The deceased person's CNIC is not in the identity registry.")
    elif person["life_status"] == "alive":
        problem("deceased_alive", "human", "The identity registry records this person as alive.")

    cert_ok = bool(certificate and certificate["action"] == "auto"
                   and mock.norm_cnic((certificate.get("fields") or {}).get("deceased.cnic")) == deceased_cnic)
    if record is None:
        if cert_ok:
            problem("certificate_not_in_records", "human",
                    "The certificate photo reads well, but this death is not in the records yet: a person verifies it.")
        else:
            problem("record_missing", "ask_more", "No death record for this CNIC.")
        applicant, rec_relation = None, None
    else:
        out["record"] = {k: record[k] for k in ("tracking_id", "deceased_name", "date_of_death", "entry_date",
                                                "applicant_name", "applicant_relation")}
        applicant, rec_relation = record["applicant_cnic"], record["applicant_relation"]
        late = _days(record["date_of_death"], record["entry_date"])
        if late is not None and late > cfg["late_registration_days"]:
            problem("late_registration", "human", f"The death was entered {late} days after it happened "
                                                  f"(limit {cfg['late_registration_days']}).")
    if applicant and applicant != claimant_cnic:
        problem("applicant_mismatch", "human", "The death record names a different applicant (CNIC differs).")
    use_relation = rec_relation or relation
    if use_relation not in ELIGIBLE_RELATIONS:
        problem("relation_not_eligible", "human", f"Relation '{use_relation}' is not eligible for {settings.benefit_name}.")
    elif rec_relation and relation != rec_relation:
        problem("relation_differs", "human", f"Relation given as '{relation}', but the record says '{rec_relation}'.")

    if prog is None:
        problem("no_programme_record", "human", "The claimant is not on the programme list.")
    else:
        out["programme"] = {k: prog[k] for k in ("monthly_income", "dependants", "already_paid")}
        if prog["already_paid"]:
            problem("already_paid", "human", f"The programme already paid this claimant (on {prog['last_paid_on']}).")
        if prog["monthly_income"] > cfg["max_monthly_income"]:
            problem("income_over_limit", "human", f"Household income PKR {prog['monthly_income']:,} is above the "
                                                  f"limit of PKR {cfg['max_monthly_income']:,}.")
    others = db.scalars(select(Case).where(Case.id != case.id, Case.status.in_(
        ("approved", "paid", "escalated", "assigned", "payment_failed")))).all()
    dup = [c.id for c in others if ((c.data or {}).get("eligibility") or {}).get("input", {}).get("deceased_cnic") == deceased_cnic]
    if dup:
        problem("duplicate_claim", "human", f"Another claim for the same death exists (claim {dup[0]}).")

    dependants = min((prog or {}).get("dependants", 0), MAX_DEPENDANTS)
    out["amount"] = settings.benefit_amount + PER_DEPENDANT_PKR * dependants
    worst = max((["auto", "ask_more", "human"].index(p["action"]) for p in problems), default=0)
    action = ["auto", "ask_more", "human"][worst]
    conf = 0.99 if not problems else (0.0 if action == "ask_more" else 0.4)
    if record is None and cert_ok:
        conf = min(conf, float(certificate["confidence"]))
    return {**out, "action": action, "confidence": conf, "problems": problems,
            "detail": "Death record found; the claimant, relation and programme rules all agree." if not problems
            else "; ".join(p["detail"] for p in problems)}


def eligibility_step(db: Session, case: Case, user: User, citizen: User, deceased_cnic: str | None,
                     relation: str | None, photo: UploadFile | None) -> Case:
    _need_step(case, "eligibility", "decide", "proof")
    require_consent(db, citizen.id, "records_check", user, case.id)
    claimant = mock.norm_cnic(citizen.cnic)
    if claimant is None:
        raise HTTPException(409, "Do the identity step first")
    active = rules.get_active(db)
    cert = None
    if photo is not None and photo.filename:
        cert, _ = documents.read_and_store(db, case, user, "death_certificate", photo, active.config,
                                           active.version, claimant)
        if not deceased_cnic:  # a photo can fill in what was not typed
            deceased_cnic = (cert.get("fields") or {}).get("deceased.cnic")
            relation = relation or (cert.get("fields") or {}).get("applicant.relation")
    else:
        cert = documents.latest(db, case.id, "death_certificate")
    deceased = mock.norm_cnic(deceased_cnic)
    if deceased is None:
        raise HTTPException(422, "Enter the CNIC of the person who died")
    if deceased == claimant:
        raise HTTPException(422, "The CNIC of the person who died cannot be your own")
    relation = (relation or "").strip().title()
    if not relation:
        raise HTTPException(422, "Choose your relation to the person who died")
    result = check_eligibility(db, case, claimant, deceased, relation, cert, active.config)
    case.amount = result["amount"]
    _save(db, case, "eligibility", {"input": {"deceased_cnic": deceased, "relation": relation}, "result": result},
          "decide")
    audit.record(db, "claim.step_done", actor=user, case_id=case.id,
                 details={"step": "eligibility", "action": result["action"],
                          "problems": [p["code"] for p in result["problems"]], "amount": case.amount})
    db.commit()
    db.refresh(case)
    return case


# ---------------------------------------------------------------- decision, handoff, payment
def _note(db: Session, case: Case, text: str, actor: User | None = None, role: str = audit.ACTOR_AI):
    audit.record(db, "case.note", actor=actor, actor_role=None if actor else role, case_id=case.id,
                 details={"note": text})


def decide(db: Session, case: Case, user: User, citizen: User, message: str | None, idem_key: str | None) -> Decision:
    if idem_key:  # the same request sent twice (weak signal) returns the first decision
        prior = db.scalar(select(Decision).where(Decision.case_id == case.id, Decision.idem_key == idem_key))
        if prior is not None:
            return prior
    _need_step(case, "decide", "proof")
    data = case.data or {}
    active = rules.get_active(db)
    cfg = active.config
    scam = None
    if message and message.strip():
        try:
            scam = scam_classifier.classify(message, cfg, active.version)
        except scam_classifier.ModelMissing as e:
            raise HTTPException(503, str(e))
    doc = documents.latest(db, case.id, "cnic")
    death = documents.latest(db, case.id, "death_certificate")
    result = decision_engine.decide(case.amount, data["identity"]["result"], data["eligibility"]["result"], scam,
                                    doc, cfg, active.version, death=death)
    row = Decision(case_id=case.id, rule_version=active.version, outcome=result["outcome"],
                   confidence=result["confidence"], reason_user=result["reason_user"], trace=result["trace"],
                   idem_key=idem_key)
    db.add(row)
    case.outcome, case.confidence = result["outcome"], result["confidence"]
    audit.record(db, "ai.decision", actor_role=audit.ACTOR_AI, case_id=case.id,
                 details={"outcome": result["outcome"], "confidence": result["confidence"], "rule_version": active.version,
                          "requested_by": user.id, "checks": [(c["step"], c["severity"], c["code"]) for c in result["trace"]["checks"]]})

    if result["outcome"] == "green":
        case.status, case.step = "approved", "done"
        audit.record(db, "claim.auto_approved", actor_role=audit.ACTOR_AI, case_id=case.id,
                     details={"confidence": result["confidence"], "rule_version": active.version})
        db.flush()
        pay(db, case, None)
    elif result["outcome"] == "yellow":
        case.status, case.step = "waiting_citizen", "proof"
        audit.record(db, "claim.asked_for_proof", actor_role=audit.ACTOR_AI, case_id=case.id,
                     details={"asks_for": result["asks_for"]})
        sms.send(db, citizen, "asked_for_proof", case.id)
    else:
        handoff(db, case, result, user)
    db.commit()
    db.refresh(row)
    return row


def handoff(db: Session, case: Case, result: dict, user: User):
    """'I am not sure': the claim goes to the officer queue with notes saying exactly what to check."""
    case.status, case.step, case.assigned_officer_id = "escalated", "done", None
    problems = [c for c in result["trace"]["checks"] if c["severity"] != "green"]
    lines = [f"- [{c['severity']}] {c['step']}: {c['detail']}" for c in problems]
    _note(db, case, f"Sent to a person (confidence {result['confidence']:.2f}). Please check:\n" + "\n".join(lines))
    audit.record(db, "case.escalated", actor_role=audit.ACTOR_AI, case_id=case.id,
                 details={"reason": "decision_red", "problems": [c["code"] for c in problems]})
    if not has_consent(db, case.citizen_id, "case_share"):
        _note(db, case, "The citizen has not shared this claim with officers: it stays hidden until she does.")
    sms.send(db, _citizen_of(db, case), "with_officer", case.id)


def pay(db: Session, case: Case, actor: User | None):
    """Send the money (mock bank). Needs the citizen's 'payment' permission; never pays twice."""
    citizen = _citizen_of(db, case)
    if not has_consent(db, citizen.id, "payment"):
        audit.record(db, "consent.blocked", actor=actor, actor_role=None if actor else audit.ACTOR_SYSTEM,
                     case_id=case.id, details={"purpose": "payment", "citizen_id": citizen.id})
        _note(db, case, "Approved, but the citizen has not allowed payment: waiting for her permission.", actor)
        return
    acc = mock.account(citizen.cnic)
    registry_name = (((case.data or {}).get("identity") or {}).get("result") or {}).get("registry", {}).get("full_name")
    if acc and acc.get("holder_name"):
        active = rules.get_active(db)
        nm = match_name(acc["holder_name"], None, [{"name": registry_name or citizen.full_name}], active.config, active.version)
        if nm["action"] != "auto":
            case.status = "payment_failed"
            audit.record(db, "payment.held", actor=actor, actor_role=None if actor else audit.ACTOR_SYSTEM,
                         case_id=case.id, details={"reason": "account_name_mismatch", "name_match": nm["status"]})
            _note(db, case, f"Payment held: the bank account is in the name '{acc['holder_name']}', not the "
                            f"claimant's. A person must confirm or get her own account.", actor)
            sms.send(db, citizen, "payment_problem", case.id)
            return
    try:
        t = mock.transfer(db, citizen.cnic, case.amount, f"claim-{case.id}")
    except mock.PaymentRefused as e:
        case.status = "payment_failed"
        audit.record(db, "payment.failed", actor=actor, actor_role=None if actor else audit.ACTOR_SYSTEM,
                     case_id=case.id, details={"reason": str(e)})
        _note(db, case, f"Payment failed: {e}. A person needs to sort out the account.", actor)
        sms.send(db, citizen, "payment_problem", case.id)
        return
    case.status, case.payment_ref, case.paid_at, case.step = "paid", t["transfer_id"], utcnow(), "done"
    audit.record(db, "payment.sent", actor=actor, actor_role=None if actor else audit.ACTOR_SYSTEM, case_id=case.id,
                 details={"transfer_id": t["transfer_id"], "amount": case.amount, "replayed": t["replayed"]})
    if not t["replayed"]:
        sms.send(db, citizen, "paid", case.id, amount=f"{case.amount:,}", ref=t["transfer_id"],
                 days=settings.payment_settlement_days)


HANDOFF_KINDS = {  # kind -> (note for the officer, SMS kind, moves the claim into the officer queue?)
    "handoff": ("The citizen asked to talk to an officer. Please call her back.", "officer_callback", True),
    "complaint": ("The citizen wants to make a complaint. Please call her back.", "officer_callback", True),
    "appeal": ("The citizen does not agree with the decision and asks for a review.", "officer_callback", True),
    "payment_problem": ("The citizen says the money has not reached her account.", "officer_callback", True),
    "correction": ("The citizen says some of her details are written wrong.", "officer_callback", True),
    "household": ("The citizen says her household changed (children / income). Please update and re-check.",
                  "officer_callback", True),
    "helper_visit": ("The citizen asks for a helper to visit her at home.", "helper_visit", False),
    "fraud_report": ("The citizen reports someone asking her for money or a PIN. She was told never to pay anyone.",
                     "officer_callback", True),
    "urgent": ("URGENT: the citizen asked for urgent help (safety / no food / illness). Call her now.", "urgent", True),
    "photo_unreadable": ("The assistant could not read her document photo twice. Please check her documents by "
                         "phone or a helper visit.", "with_officer", True),
    "name_disputed": ("The citizen said the name read from her CNIC is wrong. Please check her identity.",
                      "with_officer", True),
}


def citizen_handoff(db: Session, case: Case, user: User, kind: str):
    """The citizen asks for a person (officer call, complaint, appeal, urgent help...): a note the officer
    sees, an SMS to her, and, where it needs an officer, the claim goes into the officer queue."""
    note, sms_kind, to_queue = HANDOFF_KINDS[kind]
    _note(db, case, note + " (via the assistant)", user)
    audit.record(db, "citizen.request", actor=user, case_id=case.id, details={"kind": kind})
    if to_queue and case.status in ("draft", "waiting_citizen", "paid", "rejected", "approved"):
        if case.status in ("draft", "waiting_citizen"):
            case.status, case.assigned_officer_id = "escalated", None
            audit.record(db, "case.escalated", actor=user, case_id=case.id, details={"reason": f"citizen_{kind}"})
    sms.send(db, _citizen_of(db, case), sms_kind, case.id)
    db.commit()


def withdraw(db: Session, case: Case, user: User):
    if case.status not in ("draft", "waiting_citizen", "escalated", "assigned"):
        raise HTTPException(409, f"A claim that is '{case.status}' cannot be withdrawn")
    case.status, case.step = "withdrawn", "done"
    audit.record(db, "claim.withdrawn", actor=user, case_id=case.id)
    db.commit()


# ---------------------------------------------------------------- officer actions
def officer_assign(db: Session, case: Case, officer: User):
    if case.status not in ("escalated", "payment_failed", "waiting_citizen"):
        raise HTTPException(409, f"A claim that is '{case.status}' cannot be taken")
    prev = case.status
    case.status, case.assigned_officer_id = "assigned", officer.id
    audit.record(db, "case.assigned", actor=officer, case_id=case.id, details={"from": prev})
    db.commit()


def officer_decide(db: Session, case: Case, officer: User, approve: bool, note: str):
    if case.status != "assigned" or case.assigned_officer_id != officer.id:
        raise HTTPException(409, "Take the claim first (it must be assigned to you)")
    note = (note or "").strip()
    if not approve and len(note) < 3:
        raise HTTPException(422, "A rejection needs a note that explains why")
    case.resolution_note = note or None
    if note:
        _note(db, case, note, officer)
    if approve:
        case.status = "approved"
        audit.record(db, "claim.officer_approved", actor=officer, case_id=case.id,
                     details={"ai_outcome": case.outcome, "ai_confidence": case.confidence})
        db.flush()
        pay(db, case, officer)
    else:
        case.status = "rejected"
        audit.record(db, "claim.officer_rejected", actor=officer, case_id=case.id,
                     details={"ai_outcome": case.outcome, "ai_confidence": case.confidence})
        sms.send(db, _citizen_of(db, case), "rejected", case.id)
    db.commit()


def notes(db: Session, case_id: int) -> list[dict]:
    rows = db.scalars(select(AuditLog).where(AuditLog.case_id == case_id, AuditLog.action == "case.note")
                      .order_by(AuditLog.id)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.actor_id for r in rows if r.actor_id})))}
    return [{"id": r.id, "by": names.get(r.actor_id, "system" if r.actor_role in ("ai", "system") else "?"),
             "role": r.actor_role, "at": r.created_at, "note": r.details.get("note", "")} for r in rows]


# ---------------------------------------------------------------- views
STEP_ORDER = ("consent", "identity", "eligibility", "decide", "proof", "done")


def latest_decision(db: Session, case_id: int) -> Decision | None:
    return db.scalar(select(Decision).where(Decision.case_id == case_id).order_by(Decision.id.desc()).limit(1))


def citizen_view(db: Session, case: Case) -> dict:
    d = latest_decision(db, case.id)
    data = case.data or {}
    ident = (data.get("identity") or {})
    elig = (data.get("eligibility") or {})
    return {
        "case_id": case.id, "benefit": case.benefit, "amount": case.amount, "status": case.status, "step": case.step,
        "consent": (data.get("consent") or {}).get("purposes", []),
        "identity": ident.get("input"), "identity_ok": (ident.get("result") or {}).get("action"),
        "eligibility": elig.get("input"), "eligibility_ok": (elig.get("result") or {}).get("action"),
        "decision": None if d is None else {"outcome": d.outcome, "reason": d.reason_user,
                                            "reason_ur": d.trace.get("reason_user_ur", ""),
                                            "next_step": decision_engine.NEXT_STEP[d.outcome],
                                            "asks_for": d.trace.get("asks_for", [])},
        "payment_ref": case.payment_ref, "paid_at": case.paid_at, "created_at": case.created_at, "prototype": True,
    }


def purposes_text() -> list[dict]:
    return [{"purpose": k, "shared_with": v[0], "en": v[1], "ur": v[2]} for k, v in PURPOSES.items()
            if k in CLAIM_PURPOSES]
