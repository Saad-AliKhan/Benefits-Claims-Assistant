"""Punjab / NADRA CRMS Death Registration Certificate.

Layout: English labels and values on the left, the same in Urdu on the right, in sections
(Deceased Person's Details, Parental Information, Husband's/Wife's Information, Address,
Applicant's Details). CNIC numbers and dates are printed in Latin digits on both sides, so each
one is read twice and the two readings are compared.
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from urllib.parse import urlparse

import cv2
import numpy as np

from .config import SETTINGS
from .fields import blank, checked_value, choice_field, name_field, not_found, review, text_field
from .layout import LabelHit, find_label, horizontal, join_text, mean_conf, norm, page_extent, same_row, values_right
from .normalize import cnic_digits, cnic_gender
from .prepare import prepare
from .datatypes import BadImage, Extraction, Field, Flag, Line

TITLE = ["death registration certificate"]
HEADERS = {
    "deceased": ["deceased person's details", "deceased persons details"],
    "parents": ["parental information", "parents information"],
    "husband": ["husband's information", "husbands information"],
    "wife": ["wife's information", "wifes information"],
    "address": ["address"],
    "applicant": ["applicant's details", "applicants details"],
}
LABELS = {
    "tracking_id": ["tracking id", "tracking no"],
    "record_no": ["record no", "registration no", "record number", "registration number"],
    "crms_no": ["crms no", "crms no."],
    "name": ["name"],
    "nationality": ["nationality"],
    "cnic": ["cnic no", "cnic number", "cnic"],
    "date_of_birth": ["date of birth"],
    "gender": ["gender"],
    "religion": ["religion"],
    "sickness_period": ["sickness period"],
    "date_of_death": ["date of death"],
    "date_of_burial": ["date of burial/last rite", "date of burial"],
    "place_of_death": ["place of death"],
    "reason_of_death": ["reason of death"],
    "nature_of_death": ["nature of death"],
    "burial_place": ["buried/last rite at", "buried at"],
    "father_name": ["father's name", "father name"],
    "mother_name": ["mother's name", "mother name"],
    "address": ["address"],
    "tehsil": ["tehsil"],
    "district": ["district"],
    "relation": ["relation with deceased"],
    "entry_date": ["entry date"],
    "issue_date": ["issue date"],
    "entry_status": ["entry status"],
}
ALL_LABEL_ALIASES = [a for v in LABELS.values() for a in v]
KEY_FIELDS = ("deceased.name", "deceased.cnic", "deceased.date_of_death",
              "applicant.name", "applicant.cnic", "applicant.relation", "certificate.tracking_id")


def _header_score(line: Line, alias: str) -> float:
    t, a = norm(line.text), norm(alias)
    if not t or len(t) < len(a) - 3:
        return 0.0
    best = 0.0
    for k in range(max(3, len(a) - 2), len(a) + 3):
        for s in range(0, max(1, len(t) - k + 1)):
            best = max(best, difflib.SequenceMatcher(None, t[s:s + k], a).ratio())
    return best


class _Page:
    """OCR lines plus the geometry needed to look up values on this certificate."""

    def __init__(self, lines: list[Line]):
        self.lines = lines
        self.x0, self.y0, self.x1, self.y1 = page_extent(lines)
        self.w = max(1.0, self.x1 - self.x0)
        # English values sit left of this x; the Urdu copies sit right of it.
        self.split = self.x0 + 0.58 * self.w
        self.headers = self._find_headers()

    def _find_headers(self) -> dict[str, Line]:
        found: dict[str, tuple[float, Line]] = {}
        for ln in self.lines:
            if not (self.x0 + 0.15 * self.w <= ln.cx <= self.x0 + 0.75 * self.w):
                continue
            for name, aliases in {**HEADERS, "title": TITLE}.items():
                need = 0.9 if name == "address" else 0.8
                s = max(_header_score(ln, a) for a in aliases)
                if name == "address" and len(norm(ln.text)) > 12:
                    continue
                if s >= need and (name not in found or s > found[name][0]):
                    found[name] = (s, ln)
        return {k: v[1] for k, v in found.items()}

    def section(self, name: str) -> tuple[float, float]:
        """y-range of a section: from its header to the next header below it."""
        order = sorted(self.headers.items(), key=lambda kv: kv[1].y0)
        if name not in self.headers:
            return (0.0, -1.0)
        start = self.headers[name].y1
        later = [ln.y0 for k, ln in order if ln.y0 > self.headers[name].y0 + 1 and k != "title"]
        return (start - 2, min(later) if later else self.y1 + 1)

    def label(self, field: str, y_range: tuple[float, float], used: set[int]) -> LabelHit | None:
        hit = find_label(self.lines, LABELS[field], y_range[0], y_range[1], x_max=self.split, used=used)
        if hit:
            used.add(id(hit.line))
        return hit

    def right_of(self, hit: LabelHit) -> list[Line]:
        return values_right(self.lines, hit.line, self.split, ALL_LABEL_ALIASES)

    def urdu_copy(self, hit: LabelHit, values: list[Line]) -> list[Line]:
        """The Latin-digit copy on the Urdu side of the same row."""
        anchor = values[0] if values else hit.line
        row = [ln for ln in self.lines if ln.x0 >= self.split and same_row(ln, anchor, 0.8)
               and sum(ch.isdigit() for ch in ln.text) >= 4]
        return sorted(row, key=lambda ln: ln.x0)[:1]


_LOOK = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"})


def tracking_id(text: str) -> str | None:
    """The certificate number as printed. Plain numbers ('91100067591436', '91-100076542318') -> digits only
    (as the records system stores them); with a letter prefix ('DC-2507-913284', 'TRK20261100143',
    'DR-0004587') -> prefix + digits, dashes kept."""
    t = re.sub(r"\s*-\s*", "-", (text or "").strip())
    for m in re.finditer(r"(?<![A-Za-z0-9])([A-Z]{2,4})?(-?)([0-9OoDlI|SB][0-9OoDlI|SB-]{5,})", t):
        prefix, dash, body = m.group(1) or "", m.group(2), m.group(3).rstrip("-")
        if not prefix and not body[:1].isdigit():  # a word, not a number
            continue
        body = body.translate(_LOOK)
        if not re.fullmatch(r"[0-9-]+", body):
            continue
        digits = body.replace("-", "")
        if prefix:
            if len(digits) >= 6:
                return prefix + dash + body
        elif len(digits) >= 10:
            return digits
    return None


def _anchor_score(lines: list[Line]) -> float:
    lines = horizontal(lines)
    if len(lines) < 5:
        return 0.0
    page = _Page(lines)
    labels = sum(1 for f in ("name", "cnic", "date_of_death", "relation", "father_name", "entry_date")
                 if find_label(lines, LABELS[f]))
    return len(page.headers) + 0.5 * labels


def _decode_qr(image: np.ndarray) -> str | None:
    det = cv2.QRCodeDetector()
    h, w = image.shape[:2]
    regions = [image, image[h // 2:, :], image[h // 2:, w // 4: 3 * w // 4]]
    for region in regions:
        for f in (1.0, 1.5, 2.0, 0.6):
            img = cv2.resize(region, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC) if f != 1 else region
            try:
                text, pts, _ = det.detectAndDecode(img)
            except cv2.error:
                continue
            if text:
                return text
    return None


def extract_death_certificate(engine, img: np.ndarray, today: date | None = None) -> Extraction:
    today = today or date.today()
    prep = prepare(engine, img, SETTINGS.DEATH_CERT_LONG_SIDE, _anchor_score, min_score=4,
                   min_long_side=SETTINGS.DEATH_CERT_MIN_LONG_SIDE)
    page = _Page(prep.lines)
    image = prep.image
    if "deceased" not in page.headers and "title" not in page.headers and prep.quality["anchor_score"] < 4:
        raise BadImage("not_a_death_certificate",
                       "the death certificate headings could not be found; check that the whole page is in the photo")

    f: dict[str, Field] = {}
    used: set[int] = set()

    def section(name: str) -> tuple[float, float]:
        return page.section(name)

    # --- certificate identifiers (top of page, above the deceased section) ---
    top = (page.y0 - 10, page.headers["deceased"].y0 if "deceased" in page.headers else page.y0 + 0.2 * (page.y1 - page.y0))
    hit = page.label("tracking_id", top, used)
    if hit is None:  # some certificates print 'Record No.' / 'Registration No.' instead (often on the right)
        hit = find_label(page.lines, LABELS["record_no"], top[0], top[1])
        if hit:
            used.add(id(hit.line))
    if hit:
        vals = values_right(page.lines, hit.line, page.x1 + 1, ALL_LABEL_ALIASES)[:2] \
            if hit.line.x0 >= page.split else page.right_of(hit)
        group = [hit.line] + vals
        value = tracking_id(hit.remainder + " " + join_text(vals))
        if value:
            f["certificate.tracking_id"] = review(Field(value, mean_conf(group), raw=join_text(group)))
        else:
            f["certificate.tracking_id"] = Field(None, 0.2, needs_review=True, raw=join_text(group),
                                                 note="tracking ID unreadable")
    else:
        # label unreadable ('ackng Id:9110...'): the tracking ID is the only 12+ digit number above
        # the deceased section
        cands = [ln for ln in page.lines if top[0] <= ln.cy <= top[1] and ln.x1 < page.split
                 and len(cnic_digits(ln.text.split(":")[-1])) >= 12]
        if cands:
            ln = max(cands, key=lambda c: c.conf)
            f["certificate.tracking_id"] = review(Field(cnic_digits(ln.text.split(":")[-1]), mean_conf([ln]) * 0.9,
                                                        raw=ln.text, method="ocr_without_label"))
        else:
            f["certificate.tracking_id"] = not_found("tracking ID", key=True)
    f["certificate.crms_no"] = _crms_number(page, top, used)

    # --- deceased ---
    dec = section("deceased")
    _person(page, image, engine, f, "deceased", dec, used, key=True,
            extra=["nationality", "date_of_birth", "gender", "religion", "date_of_death", "date_of_burial",
                   "place_of_death", "reason_of_death", "nature_of_death", "burial_place"])

    # --- parents: CNIC labels come right after each parent's name ---
    par = section("parents")
    for parent in ("father", "mother"):
        hit = page.label(f"{parent}_name", par, used)
        f[f"{parent}.name"] = name_field(page.right_of(hit), hit.remainder) if hit else not_found(f"{parent}'s name")
        if hit:
            below = (hit.line.y1 - 2, hit.line.y1 + 3.5 * hit.line.h)
            chit = page.label("cnic", below, used)
            f[f"{parent}.cnic"] = _cnic(page, image, engine, chit) if chit else not_found(f"{parent}'s CNIC")
        else:
            f[f"{parent}.cnic"] = not_found(f"{parent}'s CNIC")

    # --- spouse ---
    spouse = "husband" if "husband" in page.headers else "wife" if "wife" in page.headers else None
    # Many certificates print "Husband's Information" (or "شوہر/بیوی") whatever the deceased's gender, so the
    # deceased's gender decides; the heading is only used when the gender is unreadable.
    gender = f.get("deceased.gender", Field()).value
    if gender in ("Male", "Female"):
        f["spouse.relation"] = Field("Wife" if gender == "Male" else "Husband", 0.95, method="deceased_gender")
    else:
        f["spouse.relation"] = Field(spouse.title() if spouse else None, 0.7 if spouse else 0.0,
                                     method="section_heading" if spouse else "not_found")
    f["spouse.heading"] = Field(spouse.title() if spouse else None, 0.95 if spouse else 0.0, method="section_heading")
    if spouse:
        _person(page, image, engine, f, "spouse", section(spouse), used, key=False, extra=[])
    else:
        f["spouse.name"], f["spouse.cnic"] = not_found("spouse section"), not_found("spouse section")

    # --- address ---
    addr = section("address") if "address" in page.headers else (page.y0, page.y1)
    hit = page.label("address", addr, used)
    if hit:
        stop = find_label(page.lines, LABELS["tehsil"], hit.line.y0, addr[1] + 1, x_max=page.split)
        y_stop = (stop.line.y0 - 0.5 * stop.line.h) if stop else hit.line.y1 + 4 * hit.line.h
        parts = [ln for ln in page.lines if ln is not hit.line and ln.x0 < page.split
                 and ln.x0 > hit.line.x1 - hit.line.h and hit.line.y0 - 0.5 * hit.line.h <= ln.y0 < y_stop]
        rows: list[list[Line]] = []
        for ln in sorted(parts, key=lambda ln: ln.cy):
            if rows and same_row(rows[-1][0], ln):
                rows[-1].append(ln)
            else:
                rows.append([ln])
        parts = [ln for row in rows for ln in sorted(row, key=lambda ln: ln.x0)]
        f["address.full"] = text_field(parts, hit.remainder, address=True)
    else:
        f["address.full"] = not_found("address")
    for key in ("tehsil", "district"):
        hit = page.label(key, addr, used)
        f[f"address.{key}"] = text_field(page.right_of(hit), hit.remainder, address=True) if hit else not_found(key)

    # --- applicant and registration ---
    app = section("applicant")
    _person(page, image, engine, f, "applicant", app, used, key=True, extra=["relation"])
    reg = (app[0], page.y1 + 1) if app[1] > app[0] else (page.y0, page.y1)
    for key, kind in (("entry_date", "date"), ("issue_date", "date"), ("entry_status", "text")):
        hit = page.label(key, reg, used)
        if not hit:
            f[f"certificate.{key}"] = not_found(key.replace("_", " "))
        elif kind == "date":
            vals = page.right_of(hit) or ([hit.line] if hit.remainder else [])
            f[f"certificate.{key}"] = checked_value(engine, image, [vals, page.urdu_copy(hit, vals)], "date") \
                if vals else blank()
        else:
            f[f"certificate.{key}"] = text_field(page.right_of(hit), hit.remainder)

    # --- QR code ---
    qr = _decode_qr(image)
    f["certificate.qr_url"] = Field(qr, 0.99 if qr else 0.0, method="qr" if qr else "not_found")

    _refuse_if_incomplete(f, page, image.shape[0])
    flags = _flags(f, today)
    return Extraction("death_certificate", f, flags, prep.quality, KEY_FIELDS)


def _refuse_if_incomplete(f: dict[str, Field], page: _Page, image_h: int) -> None:
    """A page that is cut off or too degraded to read is a 'retake', not a result full of nulls."""
    missing = [k for k in KEY_FIELDS if f[k].value is None]
    edge = 0.025 * image_h
    applicant_missing = all(f[k].value is None for k in KEY_FIELDS if k.startswith("applicant."))
    deceased_missing = all(f[k].value is None for k in KEY_FIELDS if k.startswith("deceased."))
    if applicant_missing and "applicant" not in page.headers and page.y1 > image_h - edge:
        raise BadImage("cut_off", "the bottom of the certificate (Applicant's Details) is not in the photo")
    if deceased_missing and "deceased" not in page.headers and page.y0 < edge:
        raise BadImage("cut_off", "the top of the certificate (Deceased Person's Details) is not in the photo")
    if len(missing) >= 4:
        raise BadImage("unreadable", f"{len(missing)} of {len(KEY_FIELDS)} key fields could not be read")


def _crms_number(page: _Page, top: tuple[float, float], used: set[int]) -> Field:
    hit = page.label("crms_no", top, used)
    cands = ([hit.line] + page.right_of(hit)) if hit else \
        [ln for ln in page.lines if top[0] <= ln.cy <= top[1] and ln.x1 < page.split and "track" not in ln.text.lower()]
    for ln in cands:
        m = re.search(r"\b([A-Z][0-9OIlS]{8,10})\b", ln.text.replace(" ", " "))
        if m:
            value = m.group(1)[0] + cnic_digits(m.group(1)[1:])
            return review(Field(value, mean_conf([ln]) * (1.0 if hit else 0.85), raw=ln.text))
    return not_found("CRMS number")


def _cnic(page: _Page, image, engine, hit: LabelHit) -> Field:
    vals = page.right_of(hit)
    if not vals and hit.remainder and sum(c.isdigit() for c in hit.remainder) >= 6:
        vals = [hit.line]
    urdu = page.urdu_copy(hit, vals)
    if not vals and not urdu:
        return blank()
    return checked_value(engine, image, [vals, urdu], "cnic")


def _person(page: _Page, image, engine, f: dict[str, Field], prefix: str, rng: tuple[float, float],
            used: set[int], key: bool, extra: list[str]) -> None:
    if rng[1] <= rng[0]:
        for k in ["name", "cnic", *extra]:
            f[f"{prefix}.{k}"] = not_found(f"{prefix} section", key=key and k in ("name", "cnic", "relation"))
        return
    for k in ["name", "cnic", *extra]:
        hit = page.label(k, rng, used)
        is_key = f"{prefix}.{k}" in KEY_FIELDS
        if not hit:
            f[f"{prefix}.{k}"] = not_found(k.replace("_", " "), key=is_key)
            continue
        if k == "cnic":
            fld = _cnic(page, image, engine, hit)
        elif k.startswith("date_of"):
            vals = page.right_of(hit) or ([hit.line] if hit.remainder else [])
            fld = checked_value(engine, image, [vals, page.urdu_copy(hit, vals)], "date") if vals else blank()
        elif k == "name":
            fld = name_field(page.right_of(hit), hit.remainder)
        elif k == "gender":
            fld = choice_field(page.right_of(hit), hit.remainder, "gender")
        elif k in ("relation", "nationality", "religion"):
            fld = choice_field(page.right_of(hit), hit.remainder, k)
        else:
            fld = text_field(page.right_of(hit), hit.remainder)
        if is_key and fld.value is None:
            fld.needs_review = True
            fld.note = fld.note or "required value is blank"
        f[f"{prefix}.{k}"] = fld


def _d(f: dict[str, Field], key: str) -> date | None:
    v = f.get(key)
    return date.fromisoformat(v.value) if v and v.value else None


def _flags(f: dict[str, Field], today: date) -> list[Flag]:
    flags: list[Flag] = []
    dob, death = _d(f, "deceased.date_of_birth"), _d(f, "deceased.date_of_death")
    burial, entry, issue = _d(f, "deceased.date_of_burial"), _d(f, "certificate.entry_date"), _d(f, "certificate.issue_date")

    if death and entry and (entry - death).days >= SETTINGS.LATE_REGISTRATION_DAYS:
        flags.append(Flag("LATE_REGISTRATION", "warning",
                          f"death on {death} was registered on {entry}, {(entry - death).days} days later"))
    order = [("date of birth", dob, "date of death", death), ("date of death", death, "date of burial", burial),
             ("date of death", death, "entry date", entry), ("entry date", entry, "issue date", issue)]
    for a_name, a, b_name, b in order:
        if a and b and b < a:
            flags.append(Flag("DATE_ORDER", "critical", f"{b_name} {b} is before {a_name} {a}"))
    for name, d in (("date of death", death), ("entry date", entry), ("issue date", issue)):
        if d and d > today:
            flags.append(Flag("FUTURE_DATE", "critical", f"{name} {d} is in the future"))
    if dob and death and not (0 <= (death - dob).days / 365.25 <= 115):
        flags.append(Flag("AGE_IMPLAUSIBLE", "warning", f"age at death would be {(death - dob).days / 365.25:.0f} years"))

    gender = f.get("deceased.gender", Field()).value
    by_digit = cnic_gender(f.get("deceased.cnic", Field()).value)
    if gender in ("Male", "Female") and by_digit and gender != by_digit:
        flags.append(Flag("CNIC_GENDER_MISMATCH", "warning",
                          f"gender is {gender} but the CNIC's last digit indicates {by_digit}"))
    heading = f.get("spouse.heading", Field()).value
    if gender in ("Male", "Female") and heading:
        expected = "Husband" if gender == "Female" else "Wife"
        if heading != expected:  # common template wording, not a sign of a problem by itself
            flags.append(Flag("SPOUSE_HEADING_GENERIC", "info",
                              f"deceased is {gender} but the spouse section is headed '{heading}'s Information'"))
    dc, ac = f.get("deceased.cnic", Field()).value, f.get("applicant.cnic", Field()).value
    if dc and ac and dc == ac:
        flags.append(Flag("APPLICANT_IS_DECEASED", "critical", "applicant CNIC equals the deceased person's CNIC"))
    status = f.get("certificate.entry_status", Field()).value
    if status and status.strip().lower() != "normal":
        flags.append(Flag("ENTRY_STATUS_NOT_NORMAL", "warning", f"entry status is '{status}'"))

    qr = f.get("certificate.qr_url", Field()).value
    if not qr:
        flags.append(Flag("QR_NOT_READ", "info", "the verification QR code could not be read from the photo"))
    else:
        host = (urlparse(qr).hostname or "").lower()
        trusted = SETTINGS.QR_TRUSTED_DOMAIN.lower()
        if not (host == trusted or host.endswith("." + trusted)):
            flags.append(Flag("QR_UNTRUSTED_DOMAIN", "critical",
                              f"QR code points to '{host or qr[:60]}', not {trusted}"))
    for k in KEY_FIELDS:
        if f.get(k) is None or f[k].value is None:
            flags.append(Flag("MISSING_KEY_FIELD", "warning", f"{k} could not be read"))
    return flags
