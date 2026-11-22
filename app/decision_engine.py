# -*- coding: utf-8 -*-
"""Decision engine: the three zones, explanations, guardrails. Pure function, no database.

    green  = act alone      (approve and pay automatically)
    yellow = ask for proof  (tell the citizen exactly what to send)
    red    = a human decides (the claim goes to the officer queue with notes)

Inputs are the results of the claim steps (app/claims.py) and of the AI checks:
    identity      registry check of the claimant (+ CNIC photo, if sent)
    eligibility   death record, relation, programme rules, duplicates (+ certificate photo, if sent)
    doc / death   OCR readings of the CNIC / death certificate photos (optional)
    scam          scam classifier on a message the citizen pasted (optional)
Every threshold comes from the ACTIVE rule version (app/rules.py), so the admin can change them.

Guardrails: the outcome is the WORST of all checks (a good score can never outvote a red flag);
a refusal is never automatic (anything that would refuse goes to a person); amounts above
`max_auto_amount` always need a person.
"""

SEVERITY = {"green": 0, "yellow": 1, "red": 2}
NAMES = {0: "green", 1: "yellow", 2: "red"}

# MOCK numbers so the "cost of being wrong" is visible in the demo. Say so to the judges.
HUMAN_REVIEW_COST_PKR = 300
ASK_MORE_COST_PKR = 50

# code -> (English for the citizen, Urdu for the citizen). Never accusing: "an officer will check".
MESSAGES = {
    "all_ok": ("Your papers look fine. Your claim is approved.",
               "آپ کے کاغذات ٹھیک ہیں۔ آپ کا کلیم منظور ہو گیا ہے۔"),
    "scam_blocked": ("The message you pasted looks like a scam. Do not share any PIN, OTP or money. An officer will look at your case.",
                     "آپ کا پیغام دھوکہ لگتا ہے۔ اپنا پن، او ٹی پی یا رقم کسی کو نہ دیں۔ ایک افسر آپ کا کیس دیکھے گا۔"),
    "scam_unsure": ("We are not sure about the message you pasted, so an officer will check it.",
                    "ہمیں آپ کے پیغام کے بارے میں یقین نہیں، اس لیے ایک افسر اسے دیکھے گا۔"),
    "id_not_found": ("We could not find this CNIC number in the identity records. Please check the number, or send a photo of the front of your CNIC.",
                     "یہ شناختی کارڈ نمبر ریکارڈ میں نہیں ملا۔ نمبر دوبارہ دیکھیں، یا شناختی کارڈ کے سامنے والے رخ کی تصویر بھیجیں۔"),
    "id_incomplete": ("Your identity record is missing some details. Please send a photo of the front of your CNIC.",
                      "آپ کے شناختی ریکارڈ میں کچھ معلومات نہیں ہیں۔ براہ کرم شناختی کارڈ کے سامنے والے رخ کی تصویر بھیجیں۔"),
    "id_human": ("Your name or details are close to the records but not the same, so an officer will check them.",
                 "آپ کا نام یا معلومات ریکارڈ سے ملتی جلتی ہیں لیکن بالکل ایک جیسی نہیں، اس لیے ایک افسر دیکھے گا۔"),
    "record_missing": ("We could not find the death record yet. Please send a photo of the death certificate.",
                       "وفات کا ریکارڈ ابھی نہیں ملا۔ براہ کرم وفات کے سرٹیفکیٹ کی تصویر بھیجیں۔"),
    "elig_human": ("Some details of the claim do not match the records, so an officer will check them.",
                   "کلیم کی کچھ معلومات ریکارڈ سے نہیں ملتیں، اس لیے ایک افسر انہیں دیکھے گا۔"),
    "doc_ask_more": ("The CNIC photo is not clear. Please take it again in good light.",
                     "شناختی کارڈ کی تصویر صاف نہیں۔ براہ کرم روشنی میں دوبارہ لیں۔"),
    "doc_human": ("Something on the CNIC photo needs an officer to look at it.",
                  "شناختی کارڈ کی تصویر میں کوئی بات ہے جسے ایک افسر دیکھے گا۔"),
    "death_ask_more": ("The death certificate photo is not clear. Please take it again in good light.",
                       "وفات کے سرٹیفکیٹ کی تصویر صاف نہیں۔ براہ کرم روشنی میں دوبارہ لیں۔"),
    "death_human": ("Something on the death certificate needs an officer to look at it.",
                    "وفات کے سرٹیفکیٹ میں کوئی بات ہے جسے ایک افسر دیکھے گا۔"),
    "amount_over_limit": ("This amount needs an officer's approval.",
                          "اتنی رقم کے لیے افسر کی منظوری ضروری ہے۔"),
    "confidence_low": ("We are not sure enough to decide, so an officer will check your case.",
                       "ہمیں فیصلے کا پورا یقین نہیں، اس لیے ایک افسر آپ کا کیس دیکھے گا۔"),
    "confidence_mid": ("We need a little more proof before we can go ahead. Please send a photo of your CNIC or the death certificate.",
                       "آگے بڑھنے سے پہلے ہمیں کچھ اور ثبوت چاہیے۔ براہ کرم شناختی کارڈ یا وفات کے سرٹیفکیٹ کی تصویر بھیجیں۔"),
}
NEXT_STEP = {
    "green": "Nothing more to do. The money is being sent to your account.",
    "yellow": "Please send what we asked for.",
    "red": "An officer will review your case. You do not need to do anything or pay anyone.",
}
_ACTION_SEV = {"auto": 0, "ask_more": 1, "human": 2}


def decide(amount: int, identity: dict | None, eligibility: dict | None, scam: dict | None, doc: dict | None,
           rules: dict, rule_version: int | None = None, death: dict | None = None) -> dict:
    checks: list[dict] = []

    def add(step: str, sev: int, code: str | None, detail: str):
        checks.append({"step": step, "severity": NAMES[sev], "code": code, "detail": detail})

    # 1) scam message (a gate only; not part of the confidence number)
    if scam is None:
        add("scam", 0, None, "No message was pasted, so no scam check was needed.")
    elif scam["action"] == "block_and_warn":
        add("scam", 2, "scam_blocked", f"Scam probability {scam['scam_probability']:.2f} >= block threshold {rules['scam_block_min']:.2f}.")
    elif scam["action"] == "human":
        add("scam", 2, "scam_unsure", f"Scam probability {scam['scam_probability']:.2f} is between the safe and block thresholds.")
    else:
        add("scam", 0, None, f"Scam probability {scam['scam_probability']:.2f}: message looks safe.")

    # 2) identity (registry + optional CNIC photo)
    if identity is None:
        add("identity", 1, "id_not_found", "The identity step has not been done.")
    else:
        sev = _ACTION_SEV[identity["action"]]
        code = None if sev == 0 else identity.get("code") or ("id_human" if sev == 2 else "id_incomplete")
        add("identity", sev, code, identity["detail"])

    # 3) eligibility (death record, relation, programme, duplicates + optional certificate photo)
    if eligibility is None:
        add("eligibility", 1, "record_missing", "The eligibility step has not been done.")
    else:
        for p in eligibility["problems"]:
            add("eligibility", _ACTION_SEV[p["action"]], p["user_code"], p["detail"])
        if not eligibility["problems"]:
            add("eligibility", 0, None, eligibility["detail"])

    # 4) document photos (optional: plain typed claims work without them)
    if doc is None:
        add("document", 0, None, "No CNIC photo was sent (not required when the registry check is clear).")
    else:
        sev = _ACTION_SEV[doc["action"]]
        add("document", sev, [None, "doc_ask_more", "doc_human"][sev],
            f"CNIC photo: {doc['action']} (quality {doc['confidence']:.2f}, flags: {', '.join(doc['flags']) or 'none'}).")
    if death is None:
        add("death_certificate", 0, None, "No death certificate photo was sent (the records check is used).")
    else:
        sev = _ACTION_SEV[death["action"]]
        add("death_certificate", sev, [None, "death_ask_more", "death_human"][sev],
            f"Certificate photo: {death['action']} (confidence {death['confidence']:.2f}, flags: {', '.join(death['flags']) or 'none'}).")

    # 5) money guardrail
    max_amount = rules["max_auto_amount"]
    if amount > max_amount:
        add("amount", 2, "amount_over_limit", f"Amount PKR {amount:,} is above the automatic limit of PKR {max_amount:,}.")
    else:
        add("amount", 0, None, f"Amount PKR {amount:,} is within the automatic limit of PKR {max_amount:,}.")

    # 6) weakest-link confidence over the evidence that was read (not over parts that already ask for more)
    parts = {}
    for name, d in (("identity", identity), ("eligibility", eligibility), ("cnic_photo", doc), ("certificate_photo", death)):
        if d is not None and d.get("action") != "ask_more":
            parts[name] = float(d["confidence"])
    confidence = round(min(parts.values()), 4) if parts else 0.0
    hi, lo = rules["auto_approve_min_confidence"], rules["human_review_below_confidence"]
    if len(parts) < 2:
        add("confidence", 0, None, "Confidence check skipped: waiting for complete, readable evidence.")
    elif confidence >= hi:
        add("confidence", 0, None, f"Confidence {confidence:.2f} >= {hi:.2f} (act alone).")
    elif confidence < lo:
        add("confidence", 2, "confidence_low", f"Confidence {confidence:.2f} < {lo:.2f} (send to a human).")
    else:
        add("confidence", 1, "confidence_mid", f"Confidence {confidence:.2f} is between {lo:.2f} and {hi:.2f} (ask for more proof).")

    worst = max(SEVERITY[c["severity"]] for c in checks)
    outcome = NAMES[worst]

    # User-facing reason: only the checks that caused the outcome, at most two sentences.
    causes = []
    for c in checks:
        if c["severity"] == outcome and c["code"] and c["code"] not in causes:
            causes.append(c["code"])
    if len(causes) > 1:
        causes = [c for c in causes if not c.startswith("confidence_")]
    causes = causes[:2]
    if outcome == "green":
        causes = ["all_ok"]
    msgs = dict(MESSAGES)
    for code, d in (("doc_ask_more", doc), ("death_ask_more", death)):  # the OCR engine's own retake words
        r = (d or {}).get("retake") or {}
        if r.get("message_en") and r.get("message_ur"):
            msgs[code] = (r["message_en"], r["message_ur"])
    reason_en = " ".join(msgs[c][0] for c in causes)
    reason_ur = " ".join(msgs[c][1] for c in causes)

    asks = sorted({c["code"] for c in checks if c["severity"] == "yellow" and c["code"]})
    trace = {
        "rule_version": rule_version,
        "thresholds_used": {k: rules[k] for k in ("auto_approve_min_confidence", "human_review_below_confidence",
                                                  "max_auto_amount", "scam_block_min", "max_monthly_income",
                                                  "late_registration_days") if k in rules},
        "inputs": {
            "amount": amount,
            "identity": identity,
            "eligibility": eligibility,
            "document": None if doc is None else {
                k: doc.get(k) for k in ("action", "confidence", "flags", "reasons", "source", "service", "retake")}
                | {"fields": (doc.get("ocr") or {}).get("fields"), "qr": doc.get("qr"), "edit_checks": doc.get("edit_checks")},
            "death_certificate": None if death is None else {
                k: death.get(k) for k in ("action", "confidence", "flags", "fields", "checks", "reasons", "source",
                                          "service", "retake")},
            "scam": None if scam is None else {k: scam[k] for k in ("label", "action", "scam_probability", "red_flags")},
        },
        "confidence_parts": parts,
        "checks": checks,
        "asks_for": asks,
        "cost": {"amount_at_risk_pkr": amount, "expected_loss_if_auto_pkr": round((1 - confidence) * amount),
                 "human_review_cost_pkr": HUMAN_REVIEW_COST_PKR, "ask_more_cost_pkr": ASK_MORE_COST_PKR,
                 "note": "Cost figures are mock assumptions. Expected loss = (1 - confidence) x amount."},
        "final": {"outcome": outcome, "confidence": confidence, "requires_officer": outcome == "red"},
        "reason_user_ur": reason_ur,
        "prototype": True,
    }
    return {"outcome": outcome, "confidence": confidence, "requires_officer": outcome == "red",
            "reason_user": reason_en, "reason_user_ur": reason_ur, "next_step": NEXT_STEP[outcome],
            "asks_for": asks, "trace": trace, "rule_version": rule_version}
