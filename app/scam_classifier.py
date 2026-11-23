# -*- coding: utf-8 -*-
"""Step 11: scam message classifier (Urdu script + Roman Urdu).

TF-IDF on character n-grams + logistic regression. Trained offline by
`python -m scripts.train_scam`; the model file is loaded here.
Thresholds come from the active rule version: `scam_block_min`.
"""
import json
import re
import unicodedata
from pathlib import Path

import joblib

MODEL_DIR = Path(__file__).resolve().parent / "ml_models"
MODEL_PATH = MODEL_DIR / "scam_model.joblib"
METRICS_PATH = MODEL_DIR / "scam_metrics.json"

_URL = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:xyz|top|cc|tk|ml|ga|cf)\b\S*|bit\.ly/\S+)", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?92|0)?3\d{2}[-\s]?\d{7}(?!\d)")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CHARMAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ہ", "ۃ": "ہ", "ھ": "ہ", "ۓ": "ے"})
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")


def normalize_text(text: str) -> str:
    """Same Urdu letter written two ways becomes one; links/phones become tokens."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_DIGITS)
    t = _URL.sub(" urltoken ", t)
    t = _PHONE.sub(" phonetoken ", t)
    t = t.translate(_CHARMAP)
    t = _DIACRITICS.sub("", t)
    t = re.sub(r"\d{3,}", " numtoken ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


# Human-readable explanations (shown as reasons; the MODEL decides the score).
_FLAGS = [
    ("asks for a secret (PIN / OTP / password / card number)",
     r"(پن|پاس ورڈ|او ٹی پی|خفیہ نمبر|کارڈ نمبر|شناختی کارڈ نمبر|\bpin\b|\botp\b|password|card number|cnic number)"),
    ("contains a link", r"urltoken"),
    ("asks you to call or message a phone number", r"phonetoken"),
    ("asks you to pay a fee or send money first",
     r"(فیس|ایزی پیسہ|جاز کیش|ٹیکس|رقم بھیج|\bfee\b|easypaisa|jazzcash|tax ada|rupay bhej|rupay .* karein)"),
    ("promises a prize or lottery", r"(انعام|لاٹری|مبارک|inaam|lottery|mubarak)"),
    ("uses urgency or threats",
     r"(فوراً|فوری|ابھی|آخری موقع|بلاک|منسوخ|foran|abhi|aakhri|block|mansookh)"),
]
_SAFE_SIGNALS = [
    ("warns you NOT to share secrets",
     r"(نہ بتائیں|نہ دیں|نہیں مانگتا|کبھی نہیں|na batayen|na dein|nahi mangta|kabhi nahi)"),
    ("says no payment is needed", r"(ادا کرنے کی ضرورت نہیں|فیس نہ دیں|payment ki zaroorat nahi)"),
]


class ModelMissing(RuntimeError):
    pass


_model = None


def load_model():
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise ModelMissing("Scam model not found. Run: python -m scripts.train_scam")
        _model = joblib.load(MODEL_PATH)
    return _model


def load_metrics() -> dict | None:
    return json.loads(METRICS_PATH.read_text(encoding="utf-8")) if METRICS_PATH.exists() else None


def classify(text: str, rules: dict, rule_version: int | None = None) -> dict:
    """label: scam | safe | unsure.   action: block_and_warn | allow | human.
    scam   : probability >= scam_block_min
    safe   : probability <= 1 - scam_block_min
    unsure : in between -> a human looks at it."""
    block_min = rules["scam_block_min"]
    safe_max = round(1 - block_min, 4)
    clean = normalize_text(text)
    p = float(load_model().predict_proba([clean])[0][1]) if clean else 0.5

    if p >= block_min:
        label, action = "scam", "block_and_warn"
    elif p <= safe_max:
        label, action = "safe", "allow"
    else:
        label, action = "unsure", "human"

    red = [name for name, rx in _FLAGS if re.search(rx, clean, re.I)]
    safe = [name for name, rx in _SAFE_SIGNALS if re.search(rx, clean, re.I)]
    reasons = [f"Scam probability {p:.2f} (block at {block_min:.2f}, safe at or below {safe_max:.2f})."]
    if red:
        reasons.append("Red flags: " + "; ".join(red) + ".")
    if safe:
        reasons.append("Reassuring signs: " + "; ".join(safe) + ".")
    if label == "unsure":
        reasons.append("The system is not sure, so a human checks it.")

    return {
        "label": label, "action": action, "scam_probability": round(p, 4),
        "confidence": round(max(p, 1 - p), 4), "red_flags": red, "safe_signals": safe,
        "thresholds_used": {"scam_block_min": block_min, "safe_max": safe_max},
        "rule_version": rule_version, "reasons": reasons,
    }