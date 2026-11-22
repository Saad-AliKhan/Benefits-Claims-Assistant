"""Pakistani CNIC, FRONT side only. A photo of the back is refused (BadImage 'cnic_back_side' or
'cnic_front_not_found') so the citizen is asked for the right side straight away.

Two card generations are handled:
* smart CNIC (2012 onward): English labels (Name, Father Name, Gender, Country of Stay, Identity
  Number, Date of Birth, Date of Issue, Date of Expiry) with each value printed under its label.
* old green card: only the CNIC number and date of birth are in Latin script; names, gender and
  identification mark are in Urdu Nastaliq. Those are returned as null with method
  'urdu_only_on_card' so the claim flow takes them from the identity lookup instead.

The CNIC number is the field everything else hangs on, so it is always re-read several ways and voted.
"""
from __future__ import annotations

import re
from datetime import date

import cv2
import numpy as np

from .config import SETTINGS
from .field_detector import load_detector
from .fields import boxed_value, checked_value, choice_field, name_field, not_found, review, text_field
from .imaging import check_quality
from .layout import find_label, horizontal, value_below
from .normalize import DIGIT_LOOKALIKES, cnic_digits, cnic_gender, parse_date
from .prepare import prepare
from .datatypes import BadImage, Extraction, Field, Flag, Line

SMART_LABELS = {
    "name": ["name"],
    "father_or_husband_name": ["father name", "husband name", "father's name", "husband's name"],
    "gender": ["gender"],
    "country_of_stay": ["country of stay"],
    "identity_number": ["identity number"],
    "date_of_birth": ["date of birth"],
    "date_of_issue": ["date of issue"],
    "date_of_expiry": ["date of expiry"],
}
KEY_FIELDS = ("cnic", "date_of_birth")


def _number_lines(lines: list[Line]) -> list[Line]:
    """Lines that look like a CNIC number: 10-15 digits once look-alike letters are fixed."""
    out = []
    for ln in lines:
        d = cnic_digits(ln.text)
        letters = sum(ch.isalpha() for ch in ln.text.translate(DIGIT_LOOKALIKES))
        dashed = bool(re.search(r"\d{4,5}\s*-\s*\d", ln.text.translate(DIGIT_LOOKALIKES)))
        if (12 <= len(d) <= 15 or (len(d) >= 10 and dashed)) and letters <= 1:
            out.append(ln)
    return sorted(out, key=lambda ln: (abs(len(cnic_digits(ln.text)) - 13), -ln.conf))


def _date_lines(lines: list[Line]) -> list[Line]:
    out = []
    for ln in lines:
        fixed = ln.text.translate(DIGIT_LOOKALIKES)
        if parse_date(ln.text) or re.search(r"(19|20)\d\d", fixed):
            if len(cnic_digits(ln.text)) <= 11:
                out.append(ln)
    return out


def _smart_hits(lines: list[Line]) -> dict:
    hits, used = {}, set()
    for key in ("father_or_husband_name", "country_of_stay", "identity_number", "date_of_birth",
                "date_of_issue", "date_of_expiry", "gender", "name"):
        hit = find_label(lines, SMART_LABELS[key], used=used)
        if hit and hit.score >= 0.85:
            hits[key] = hit
            used.add(id(hit.line))
    return hits


def _anchor_score(lines: list[Line]) -> float:
    lines = horizontal(lines)
    return (3.0 if _number_lines(lines) else 0.0) + len(_smart_hits(lines)) * 0.5


SMART_VALUE_CLASSES = {"Identity Number": ("cnic", "cnic"), "Name Eng": ("name", "name"),
                       "FatherName Eng": ("father_or_husband_name", "name"), "Gender Eng": ("gender", "gender"),
                       "Country Eng": ("country_of_stay", "text"), "Date of Birth": ("date_of_birth", "date"),
                       "Date of Issue": ("date_of_issue", "date"), "Date of Expiry": ("date_of_expiry", "date")}


def _detector_says_smart(boxes: dict) -> bool:
    found = [k for k in SMART_VALUE_CLASSES if k in boxes and boxes[k].score >= 0.4]
    return "Identity Number" in found and len(found) >= 5


def _extract_detected(engine, img: np.ndarray, boxes: dict, quality: dict, today: date) -> Extraction | None:
    """Smart card read field by field from the detector's boxes. None if the number is unreadable,
    so the caller can fall back to the label-based reading."""
    card = boxes.get("Card")
    if card is not None and max(card.w, card.h) < 300:
        raise BadImage("too_small", f"the card is only {card.w:.0f}px wide in the photo; take it closer")
    f: dict[str, Field] = {"card.type": Field("smart", 0.95, method="field_detector")}
    for cls, (key, kind) in SMART_VALUE_CLASSES.items():
        box = boxes.get(cls)
        if box is None or box.score < 0.25:
            f[key] = not_found(key.replace("_", " "), key=key in KEY_FIELDS)
        else:
            f[key] = boxed_value(engine, img, box, kind)
    if f["cnic"].value is None:
        return None
    if f["gender"].value is None:
        f["gender"] = _gender_from_cnic(f["cnic"])
    _issue_expiry_agree(f)
    # The card does not say 'Father' or 'Husband' in a way the detector separates; leave it open.
    f["father_or_husband.relation"] = Field(None, 0.0, method="not_determined")
    quality = {**quality, "field_detector": True,
               "detector_scores": {k: round(b.score, 2) for k, b in boxes.items()}}
    return Extraction("cnic", f, _flags(f, "smart", today), quality, KEY_FIELDS)


def extract_cnic(engine, img: np.ndarray, today: date | None = None) -> Extraction:
    today = today or date.today()
    detector = load_detector()
    if detector is not None:
        quality = check_quality(img)
        boxes = detector.detect(img)
        if _detector_says_smart(boxes):
            ex = _extract_detected(engine, img, boxes, quality, today)
            if ex is not None:
                return ex
    prep = prepare(engine, img, SETTINGS.CNIC_LONG_SIDE, _anchor_score, min_score=3,
                   min_long_side=SETTINGS.CNIC_MIN_LONG_SIDE)
    lines, image = prep.lines, prep.image
    hits = _smart_hits(lines)
    card_type = "smart" if len(hits) >= 3 else "old_green"
    if card_type != "smart" and _has_qr(image):
        # only the back of a CNIC carries a QR code; the front is all this service reads
        raise BadImage("cnic_back_side", "this is the back of the card; the front (with the photo) is needed")
    f: dict[str, Field] = {"card.type": Field(card_type, 0.9 if len(hits) >= 5 or not hits else 0.75,
                                              method="label_count")}

    # --- CNIC number ---
    groups: list[list[Line]] = []
    if "identity_number" in hits:
        below = value_below(lines, hits["identity_number"].line)
        if below is not None:
            groups.append([below])
    for ln in _number_lines(lines)[:2]:
        if not any(ln in g for g in groups):
            groups.append([ln])
    if not groups:
        raise BadImage("cnic_number_not_found",
                       "no CNIC number found; photograph the front of the card, flat and in focus")
    f["cnic"] = checked_value(engine, image, groups, "cnic", second_source_name="second_copy")
    if f["cnic"].value is None:
        raise BadImage("cnic_number_unreadable", "the CNIC number could not be read; retake the photo closer")

    # --- other fields ---
    if card_type == "smart":
        for key in ("name", "father_or_husband_name"):
            hit = hits.get(key)
            f[key] = name_field([value_below(lines, hit.line)] if hit and value_below(lines, hit.line) else []) \
                if hit else not_found(key.replace("_", " "))
        hit = hits.get("father_or_husband_name")
        f["father_or_husband.relation"] = Field(
            ("Husband" if "husband" in hit.line.text.lower() else "Father") if hit else None,
            0.9 if hit else 0.0, method="label" if hit else "not_found")
        hit = hits.get("gender")
        below = value_below(lines, hit.line) if hit else None
        f["gender"] = choice_field([below], "", "gender") if below else _gender_from_cnic(f["cnic"])
        hit = hits.get("country_of_stay")
        below = value_below(lines, hit.line) if hit else None
        f["country_of_stay"] = text_field([below]) if below else not_found("country of stay")
        for key in ("date_of_birth", "date_of_issue", "date_of_expiry"):
            hit = hits.get(key)
            below = value_below(lines, hit.line) if hit else None
            f[key] = checked_value(engine, image, [[below]], "card_date") if below else not_found(key.replace("_", " "))
    else:
        for key in ("name", "father_or_husband_name"):
            f[key] = Field(None, 0.0, method="urdu_only_on_card",
                           note="printed only in Urdu on this card; take it from the identity lookup")
        f["father_or_husband.relation"] = Field(None, 0.0, method="urdu_only_on_card")
        f["gender"] = _gender_from_cnic(f["cnic"])
        f["country_of_stay"] = Field(None, 0.0, method="not_on_card")
        dls = [ln for ln in _date_lines(lines) if not any(ln in g for g in groups)]
        if dls:
            # the only Latin date on the front of the old card is the date of birth
            fields = [checked_value(engine, image, [[ln]], "date") for ln in dls[:3]]
            fields = [x for x in fields if x.value] or fields
            f["date_of_birth"] = min(fields, key=lambda x: (x.value is None, x.value or ""))
        else:
            f["date_of_birth"] = not_found("date of birth", key=True)
        if f["date_of_birth"].value is None:
            # no English labels and no date of birth: this is not a readable front side
            raise BadImage("cnic_front_not_found",
                           "no date of birth or card labels found; photograph the front of the card")
        f["date_of_issue"] = Field(None, 0.0, method="not_on_card")
        f["date_of_expiry"] = Field(None, 0.0, method="not_on_card")

    flags = _flags(f, card_type, today)
    return Extraction("cnic", f, flags, prep.quality, KEY_FIELDS)


def _issue_expiry_agree(f: dict[str, Field]) -> None:
    """A smart card expires on the same day and month as it was issued, 5, 7 or 10 years later.
    Two separately read dates that fit this are very unlikely to both be misread, so each confirms
    the other (like the two printed copies on the death certificate)."""
    i, x = f.get("date_of_issue"), f.get("date_of_expiry")
    if not (i and x and i.value and x.value and len(i.value) == 10 and len(x.value) == 10):
        return
    if i.value[5:] == x.value[5:] and int(x.value[:4]) - int(i.value[:4]) in (5, 7, 10):
        joint = min(0.99, 1 - (1 - i.confidence) * (1 - x.confidence))
        for fld in (i, x):
            fld.confidence = max(fld.confidence, joint)
            fld.method += "+issue_expiry_agree"
            fld.needs_review = fld.confidence < SETTINGS.REVIEW_BELOW or bool(fld.note)


def _has_qr(image: np.ndarray) -> bool:
    det = cv2.QRCodeDetector()
    for f in (1.0, 0.5):
        img = image if f == 1.0 else cv2.resize(image, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        try:
            text, _, _ = det.detectAndDecode(img)
        except cv2.error:
            continue
        if text:  # a decodable code only: printed security patterns can look like a QR to detect()
            return True
    return False


def _gender_from_cnic(cnic: Field) -> Field:
    g = cnic_gender(cnic.value)
    return Field(g, cnic.confidence if g else 0.0, needs_review=cnic.needs_review,
                 method="derived_from_cnic", note="from the last digit of the CNIC (odd = male, even = female)")


def _d(f: dict[str, Field], key: str) -> date | None:
    """A full date, or None (blank, 'lifetime', or year only)."""
    v = f.get(key)
    try:
        return date.fromisoformat(v.value) if v and v.value and len(v.value) == 10 else None
    except ValueError:
        return None


def _flags(f: dict[str, Field], card_type: str, today: date) -> list[Flag]:
    flags: list[Flag] = []
    if card_type == "old_green":
        flags.append(Flag("URDU_ONLY_FIELDS", "info",
                          "old green card: name and father/husband name are printed only in Urdu; "
                          "confirm them against the identity record"))
    exp = _d(f, "date_of_expiry")
    if exp and exp < today:
        flags.append(Flag("CARD_EXPIRED", "warning", f"card expired on {exp}"))
    dob, issue = _d(f, "date_of_birth"), _d(f, "date_of_issue")
    if dob:
        age = (today - dob).days / 365.25
        if age < 18:
            flags.append(Flag("UNDER_18", "warning", f"date of birth {dob} gives age {age:.0f}; a CNIC is issued at 18"))
        if age > 120 or dob > today:
            flags.append(Flag("DOB_IMPLAUSIBLE", "critical", f"date of birth {dob} is not plausible"))
    if dob and issue and issue < dob:
        flags.append(Flag("DATE_ORDER", "critical", f"date of issue {issue} is before date of birth {dob}"))
    g = f.get("gender")
    by_digit = cnic_gender(f["cnic"].value)
    if g and g.method != "derived_from_cnic" and g.value in ("Male", "Female") and by_digit and g.value != by_digit:
        flags.append(Flag("CNIC_GENDER_MISMATCH", "warning",
                          f"gender is {g.value} but the CNIC's last digit indicates {by_digit}"))
    for k in KEY_FIELDS:
        if f.get(k) is None or f[k].value is None:
            flags.append(Flag("MISSING_KEY_FIELD", "warning", f"{k} could not be read"))
    return flags
