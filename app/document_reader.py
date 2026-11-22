# -*- coding: utf-8 -*-
"""Reads a document photo with the OCR engine and turns the answer into what the decision engine uses.

    read_cnic(...)               -> `doc`   dict (same shape doc_check.check_document() always returned)
    read_death_certificate(...)  -> `death` dict

Order of preference, so the demo never depends on one engine being up:
  1. the OCR engine (ocr_core/, inside this app): per-field confidence, flags, retake reasons;
  2. CNIC only: the built-in Tesseract reader (app/doc_check.py), if LOCAL_OCR_FALLBACK is on;
  3. nothing could read it: action "human", an officer reads the photo.

On top of the OCR engine, the photo still gets this app's own edit checks (editing-software tag,
error-level analysis) and, for a CNIC, the QR checks. The OCR engine never decides; the rules here
turn its confidence and flags into  auto | ask_more | human, and the decision engine does the rest.
"""
from __future__ import annotations

import io
import re

from PIL import Image, ImageOps, UnidentifiedImageError

from app import ai_engines as ai_clients, doc_check
from app.config import settings

# OCR service flags that a NEW PHOTO can fix. Every other warning/critical flag goes to a human;
# 'info' flags (QR_NOT_READ, URDU_ONLY_FIELDS) are only noted.
ASK_MORE_FLAGS = {"MISSING_KEY_FIELD"}
# Our own checks
_HUMAN_LOCAL = {"qr_cnic_mismatch", "qr_account_mismatch", "edited_software", "ela_suspicious"}
_ASK_LOCAL = {"qr_unreadable_payload"}

CNIC_FIELDS_SHOWN = ("cnic", "name", "date_of_birth", "father_or_husband_name", "gender", "card.type",
                     "date_of_expiry")
DEATH_FIELDS_SHOWN = ("certificate.tracking_id", "deceased.name", "deceased.cnic", "deceased.date_of_death",
                      "applicant.name", "applicant.cnic", "applicant.relation", "spouse.relation")

BadImage = doc_check.BadImage


def _digits(cnic: str | None) -> str | None:
    d = re.sub(r"\D", "", cnic or "")
    return d if len(d) == 13 else None


def _open(data: bytes) -> tuple[Image.Image, Image.Image]:
    """Refuse non-images before anything is sent anywhere. Returns (original, upright RGB)."""
    try:
        original = Image.open(io.BytesIO(data))
        original.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise BadImage("That file is not a readable image.") from e
    return original, ImageOps.exif_transpose(original).convert("RGB")


def _edit_checks(original: Image.Image, rgb: Image.Image) -> tuple[list[str], list[str], dict]:
    flags, reasons = [], []
    fmt = (original.format or "").upper()
    software = doc_check._exif_software(original)
    ela = None
    if software and any(s in software.lower() for s in doc_check.EDIT_SOFTWARE):
        flags.append("edited_software")
        reasons.append(f"The file says it was saved by editing software ({software}).")
    if fmt in ("JPEG", "JPG"):
        ela = doc_check._ela(rgb)
        if ela and ela["ratio"] >= doc_check.ELA_RATIO_FLAG and ela["peak"] >= doc_check.ELA_MIN_PEAK:
            flags.append("ela_suspicious")
            reasons.append("Part of the image compresses differently from the rest (possible edit; weak signal).")
    return flags, reasons, {"file_format": fmt, "editing_software_tag": software, "ela": ela,
                            "ela_applicable": fmt in ("JPEG", "JPG")}


def _qr_checks(rgb: Image.Image, printed: str | None, claimed: str | None) -> tuple[list[str], list[str], dict]:
    flags, reasons = [], []
    payload = doc_check._qr(rgb)
    qr_cnic = doc_check._find_cnic(payload) if payload else None
    qr = {"found": bool(payload), "cnic_in_qr": bool(qr_cnic), "matches_printed_cnic": None, "matches_account_cnic": None}
    if not payload:
        flags.append("no_qr")
        reasons.append("No QR code on this side of the card (normal for the front of a CNIC).")
    elif not qr_cnic:
        flags.append("qr_unreadable_payload")
        reasons.append("A QR code was found but it does not contain a CNIC number.")
    else:
        if printed:
            qr["matches_printed_cnic"] = qr_cnic == printed
            if not qr["matches_printed_cnic"]:
                flags.append("qr_cnic_mismatch")
                reasons.append("The CNIC in the QR code is different from the printed CNIC.")
        if claimed:
            qr["matches_account_cnic"] = qr_cnic == claimed
            if not qr["matches_account_cnic"]:
                flags.append("qr_account_mismatch")
                reasons.append("The CNIC in the QR code is different from the CNIC on the account.")
    return flags, reasons, qr


def _compact_fields(fields: dict, keys: tuple) -> dict:
    """What the auditor sees: value, confidence, needs_review, method (no raw OCR text)."""
    return {k: {x: fields[k].get(x) for x in ("value", "confidence", "needs_review", "method")}
            for k in keys if k in fields}


def _service_summary(res: dict, keys: tuple) -> dict:
    return {"request_id": res.get("request_id"), "ocr_version": res.get("ocr_version"), "engine": res.get("engine"),
            "mock": res.get("mock"), "overall_confidence": res.get("overall_confidence"),
            "needs_review_fields": res.get("needs_review_fields", []),
            "flags": [{"code": f.get("code"), "severity": f.get("severity")} for f in res.get("flags", [])],
            "fields": _compact_fields(res.get("fields", {}), keys), "processing_ms": res.get("processing_ms")}


def _service_flags(res: dict) -> tuple[list[str], set, set, list[str]]:
    flags, human, ask, reasons = [], set(), set(), []
    for f in res.get("flags", []):
        code, sev = f.get("code", "?"), f.get("severity", "warning")
        if sev == "info":
            reasons.append(f"Note: {code} ({f.get('detail', '')}).")
            continue
        flags.append(code)
        (ask if code in ASK_MORE_FLAGS else human).add(code)
        reasons.append(f"{code} [{sev}]: {f.get('detail', '')}")
    return flags, human, ask, reasons


def _action(human: set, ask: set, reasons: list[str]) -> str:
    if human:
        reasons.append("Something on this document needs a person to check it, so an officer looks at it.")
        return "human"
    if ask:
        reasons.append("The photo is not good enough to read safely. Ask for a clearer photo.")
        return "ask_more"
    reasons.append("The document was read clearly and no warning signs were found.")
    return "auto"


def _empty_doc(source: str, action: str, flags: list[str], reasons: list[str], rules: dict, version) -> dict:
    return {"source": source, "action": action, "confidence": 0.0, "flags": flags,
            "ocr": {"confidence": 0.0, "text": "", "fields": {"cnic": None, "name": None}},
            "blur": {"score": None, "min_required": rules.get("doc_blur_min"), "is_blurry": None},
            "qr": {"found": None, "cnic_in_qr": None, "matches_printed_cnic": None, "matches_account_cnic": None},
            "printed_cnic_matches_account": None, "edit_checks": {},
            "thresholds_used": {"ocr_min_confidence": rules.get("ocr_min_confidence")},
            "rule_version": version, "reasons": reasons}


def _retake(doc_type: str, detail: dict, rid: str, rules: dict, version) -> dict:
    reason = detail.get("reason", "unreadable")
    d = _empty_doc("ocr_engine", "ask_more", [f"retake_{reason}"],
                   [f"The reader asked for a new photo ({reason}): {detail.get('message_en', '')}"], rules, version)
    d["retake"] = {"reason": reason, "message_en": detail.get("message_en"), "message_ur": detail.get("message_ur")}
    d["service"] = {"request_id": rid, "outcome": "retake", "reason": reason}
    d["doc_type"] = doc_type
    return d


def _nobody_could_read(doc_type: str, error: str, rules: dict, version) -> dict:
    d = _empty_doc("none", "human", ["ocr_unavailable"],
                   [f"No document reader was available ({error}), so an officer reads the photo."], rules, version)
    d["service"] = {"outcome": "unavailable", "error": error}
    d["doc_type"] = doc_type
    return d


# --------------------------------------------------------------------------- CNIC
def read_cnic(data: bytes, rules: dict, rule_version: int | None = None, claimed_cnic: str | None = None,
              filename: str = "cnic.jpg", content_type: str | None = None, request_id: str | None = None) -> dict:
    original, rgb = _open(data)
    claimed = _digits(claimed_cnic)
    call = ai_clients.read_document("cnic", data, filename, content_type, request_id)

    if call["status"] == ai_clients.RETAKE:
        return _retake("cnic", call["detail"], call["request_id"], rules, rule_version)
    if call["status"] == ai_clients.UNAVAILABLE:
        if settings.local_ocr_fallback:
            try:
                doc = doc_check.check_document(data, rules, rule_version, claimed_cnic)
                doc["source"] = "local_tesseract"
                doc["doc_type"] = "cnic"
                doc["service"] = {"outcome": "unavailable", "error": call["error"]}
                doc["reasons"].insert(0, "The OCR engine was not available, so the basic built-in reader was used.")
                return doc
            except doc_check.OcrUnavailable:
                pass
        return _nobody_could_read("cnic", call["error"], rules, rule_version)

    res = call["result"]
    fields = res.get("fields", {})
    val = lambda k: (fields.get(k) or {}).get("value")
    printed_str = val("cnic")
    printed = _digits(printed_str)
    overall = float(res.get("overall_confidence") or 0.0)
    ocr_min = rules["ocr_min_confidence"]

    flags, human, ask, reasons = _service_flags(res)
    reasons.insert(0, f"Document reader confidence {overall:.2f} (its least certain key field; "
                      f"needs at least {ocr_min:.2f} to be read safely).")
    if overall < ocr_min:
        flags.append("low_ocr_confidence")
        ask.add("low_ocr_confidence")
    if res.get("needs_review_fields"):
        reasons.append("A person should check: " + ", ".join(res["needs_review_fields"]) + ".")
    if not printed:
        flags.append("no_cnic_found")
        ask.add("no_cnic_found")

    printed_vs_account = None
    if printed and claimed:
        printed_vs_account = printed == claimed
        if not printed_vs_account:
            flags.append("printed_account_mismatch")
            reasons.append("The printed CNIC is different from the CNIC on the account.")
            # trusted only when the number itself was read confidently; otherwise it may be a misread
            (ask if (fields.get("cnic") or {}).get("needs_review", True) else human).add("printed_account_mismatch")

    q_flags, q_reasons, qr = _qr_checks(rgb, printed, claimed)
    e_flags, e_reasons, edit = _edit_checks(original, rgb)
    flags += q_flags + e_flags
    reasons += q_reasons + e_reasons
    human |= _HUMAN_LOCAL & set(flags)
    ask |= _ASK_LOCAL & set(flags)
    action = _action(human, ask, reasons)

    # confidence: the reader's number, lowered by the same edit / mismatch penalties as doc_check
    conf = overall
    if {"ela_suspicious", "edited_software"} & set(flags):
        conf *= 0.5
    if {"qr_cnic_mismatch", "qr_account_mismatch", "printed_account_mismatch"} & set(flags):
        conf *= 0.3
    if not printed:
        conf *= 0.5

    quality = res.get("quality") or {}
    return {
        "source": "ocr_engine", "doc_type": "cnic", "action": action, "confidence": round(conf, 4), "flags": flags,
        "ocr": {"confidence": overall, "text": "",
                "fields": {"cnic": printed_str, "name": val("name"), "date_of_birth": val("date_of_birth"),
                           "father_or_husband_name": val("father_or_husband_name"), "gender": val("gender")}},
        "blur": {"score": quality.get("sharpness"), "min_required": None, "is_blurry": False},
        "qr": qr, "printed_cnic_matches_account": printed_vs_account, "edit_checks": edit,
        "thresholds_used": {"ocr_min_confidence": ocr_min}, "rule_version": rule_version, "reasons": reasons,
        "service": {**_service_summary(res, CNIC_FIELDS_SHOWN), "outcome": "ok"},
    }


# --------------------------------------------------------------------------- death certificate
def read_death_certificate(data: bytes, rules: dict, rule_version: int | None = None,
                           claimant_cnic: str | None = None, filename: str = "death_certificate.jpg",
                           content_type: str | None = None, request_id: str | None = None) -> dict:
    """Checks that need only this photo and the claimant: the reader's flags and confidence, the applicant
    is the claimant, the claimant is not the deceased. Still TO DO in later steps (need the mock identity
    service and claim types): deceased marked dead in the records, applicant relation fits the benefit."""
    original, rgb = _open(data)
    claimant = _digits(claimant_cnic)
    call = ai_clients.read_document("death_certificate", data, filename, content_type, request_id)
    if call["status"] == ai_clients.RETAKE:
        return _retake("death_certificate", call["detail"], call["request_id"], rules, rule_version)
    if call["status"] == ai_clients.UNAVAILABLE:  # no local reader for certificates
        return _nobody_could_read("death_certificate", call["error"], rules, rule_version)

    res = call["result"]
    fields = res.get("fields", {})
    f = lambda k: fields.get(k) or {}
    overall = float(res.get("overall_confidence") or 0.0)
    ocr_min = rules["ocr_min_confidence"]

    flags, human, ask, reasons = _service_flags(res)
    reasons.insert(0, f"Document reader confidence {overall:.2f} (needs at least {ocr_min:.2f}).")
    if overall < ocr_min:
        flags.append("low_ocr_confidence")
        ask.add("low_ocr_confidence")
    if res.get("needs_review_fields"):
        reasons.append("A person should check: " + ", ".join(res["needs_review_fields"]) + ".")

    applicant, deceased = _digits(f("applicant.cnic").get("value")), _digits(f("deceased.cnic").get("value"))
    applicant_is_claimant = None
    if applicant and claimant:
        applicant_is_claimant = applicant == claimant
        if not applicant_is_claimant:
            flags.append("applicant_not_claimant")
            reasons.append("The applicant's CNIC on the certificate is not the CNIC of the person claiming.")
            (ask if f("applicant.cnic").get("needs_review", True) else human).add("applicant_not_claimant")
    elif not applicant:
        flags.append("applicant_cnic_missing")
        ask.add("applicant_cnic_missing")
        reasons.append("The applicant's CNIC could not be read on the certificate.")
    if deceased and claimant and deceased == claimant:
        flags.append("claimant_is_deceased")
        human.add("claimant_is_deceased")
        reasons.append("The person claiming has the same CNIC as the person who died.")

    e_flags, e_reasons, edit = _edit_checks(original, rgb)
    flags += e_flags
    reasons += e_reasons
    human |= _HUMAN_LOCAL & set(flags)
    action = _action(human, ask, reasons)

    conf = overall
    if {"ela_suspicious", "edited_software"} & set(flags):
        conf *= 0.5
    if {"applicant_not_claimant", "claimant_is_deceased"} & set(flags):
        conf *= 0.3

    return {
        "source": "ocr_engine", "doc_type": "death_certificate", "action": action,
        "confidence": round(conf, 4), "flags": flags,
        "fields": {k: f(k).get("value") for k in DEATH_FIELDS_SHOWN},
        "checks": {"applicant_is_claimant": applicant_is_claimant,
                   "deceased_marked_dead_in_records": "not checked yet (mock identity service step)",
                   "relation_fits_benefit": "not checked yet (claim types step)"},
        "edit_checks": edit, "thresholds_used": {"ocr_min_confidence": ocr_min},
        "rule_version": rule_version, "reasons": reasons,
        "service": {**_service_summary(res, DEATH_FIELDS_SHOWN), "outcome": "ok"},
    }
