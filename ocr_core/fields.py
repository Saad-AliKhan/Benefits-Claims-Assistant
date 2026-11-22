"""Building Field objects from OCR lines, with cross-checks and re-reads for the critical values."""
from __future__ import annotations

import difflib
import re
from typing import Callable

import numpy as np

from .config import SETTINGS
from .layout import join_text, mean_conf
from .normalize import (NATIONALITIES, parse_card_date, split_camel, RELIGIONS, best_choice, clean_address, clean_name, clean_text, cnic_digits, cnic_problems, format_cnic, iso,
                        normalize_gender, normalize_relation, parse_cnic, parse_date)
from .reread import reread, vote, vote_digits
from .datatypes import Field, Line


def review(f: Field) -> Field:
    """Mark a field for review when it is not confident enough."""
    if f.confidence < SETTINGS.REVIEW_BELOW:
        f.needs_review = True
    return f


def blank(note: str | None = None, key: bool = False) -> Field:
    """The label was found and nothing is written beside it."""
    return Field(None, 0.95, needs_review=key, method="blank",
                 note=note or ("required value is blank" if key else None))


def not_found(what: str, key: bool = False) -> Field:
    return Field(None, 0.0, needs_review=key, method="not_found", note=f"{what} not found on the document")


def _parse_iso_date(text: str) -> str | None:
    return iso(parse_date(text))


def checked_value(engine, image: np.ndarray, groups: list[list[Line]], kind: str,
                  second_source_name: str = "urdu_side") -> Field:
    """A CNIC number or date that may be printed more than once (the death certificate repeats them
    on the Urdu side). Two matching readings are trusted; otherwise every copy is re-read in
    several versions and the readings vote."""
    parse: Callable[[str], str | None] = {"cnic": parse_cnic, "card_date": parse_card_date}.get(kind, _parse_iso_date)
    groups = [g for g in groups if g]
    if not groups:
        return not_found(kind)
    raws = [join_text(g) for g in groups]
    first = [(parse(r), mean_conf(g)) for r, g in zip(raws, groups)]
    valid = [(v, c) for v, c in first if v]
    raw = " | ".join(raws)

    if len(valid) >= 2 and len({v for v, _ in valid}) == 1:
        conf = 1.0
        for _, c in valid:
            conf *= (1 - c)
        f = Field(valid[0][0], min(0.995, 1 - conf), raw=raw, method=f"ocr+{second_source_name}_agree")
        return _cnic_sanity(f) if kind == "cnic" else f

    light = kind != "cnic"  # dates: 6 versions are enough; the CNIC number gets all 12
    rereads = [rc for g in groups for rc in reread(engine, image, g, light=light)]
    cands = list(first) + [(parse(t), c) for t, c in rereads]
    winner, conf, _ = vote(cands)
    method = "reread_vote"
    if kind == "cnic" and (winner is None or conf < 0.6):
        digit_cands = [(cnic_digits(t), c) for t, c in
                       ([(r, mean_conf(g)) for r, g in zip(raws, groups)] + rereads)]
        w2, c2 = vote_digits(digit_cands, 13, format_cnic)
        if w2 and c2 > conf:
            winner, conf, method = w2, c2, "digit_vote"
    if winner is None:
        return Field(None, 0.2, needs_review=True, raw=raw, method="unreadable",
                     note=f"could not read a {'CNIC number' if kind == 'cnic' else 'date'} here")
    note = None
    if len({v for v, _ in valid}) > 1:
        note = "the two printed copies disagree: " + " vs ".join(sorted({v for v, _ in valid}))
        conf = min(conf, 0.8)
    f = review(Field(winner, conf, raw=raw, method=method, note=note))
    return _cnic_sanity(f) if kind == "cnic" else f


def _cnic_sanity(f: Field) -> Field:
    problems = cnic_problems(f.value)
    if problems:
        f.needs_review = True
        f.confidence = min(f.confidence, 0.5)
        f.note = "; ".join(filter(None, [f.note, *problems]))
    return f


def name_field(lines: list[Line], remainder: str = "") -> Field:
    raw = " ".join(filter(None, [remainder, join_text(lines)])).strip()
    if not raw:
        return blank()
    value, notes, unknown = clean_name(raw)
    if value is None:
        return review(Field(None, 0.3, raw=raw, note="text found but it does not look like a name"))
    conf = mean_conf(lines) if lines else 0.9
    if notes:
        conf *= 0.97
    if unknown:
        conf *= 0.93
    note = "; ".join(notes) if notes else ("contains a name not in the names list" if unknown else None)
    return review(Field(value, conf, raw=raw, method="ocr+name_list" if notes else "ocr", note=note))


def choice_field(lines: list[Line], remainder: str, kind: str) -> Field:
    raw = " ".join(filter(None, [remainder, join_text(lines)])).strip()
    if not raw:
        return blank()
    fn = {"gender": normalize_gender, "relation": normalize_relation,
          "nationality": lambda t: best_choice(t, NATIONALITIES, 0.75),
          "religion": lambda t: best_choice(t, RELIGIONS, 0.75)}[kind]
    value = fn(raw)
    if value is None:
        return review(Field(clean_text(raw), 0.4, raw=raw, note=f"not a recognised {kind}"))
    return review(Field(value, mean_conf(lines) if lines else 0.9, raw=raw))


def text_field(lines: list[Line], remainder: str = "", address: bool = False) -> Field:
    raw = " ".join(filter(None, [remainder, join_text(lines)])).strip()
    if not raw:
        return blank()
    value = clean_address(raw) if address else clean_text(raw)
    return review(Field(value, mean_conf(lines) if lines else 0.9, raw=raw))


# ---------------------------------------------------------------------------------------------
# Values located by the field detector (a box, no OCR line yet)
# ---------------------------------------------------------------------------------------------
def _box_line(x0: float, y0: float, x1: float, y1: float, score: float) -> Line:
    return Line(text="", conf=score, box=np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32))


_LABEL_WORDS = ("name", "father", "husband", "fathername", "husbandname")


def _detected_name(text: str) -> str | None:
    """Name from a detector box, dropping a printed label word that slipped into the crop."""
    words = split_camel(text or "").split()
    while len(words) > 1 and max(difflib.SequenceMatcher(None, words[0].lower(), w).ratio()
                                 for w in _LABEL_WORDS) >= 0.75:
        words = words[1:]
    return clean_name(" ".join(words))[0]


def boxed_value(engine, image: np.ndarray, box, kind: str) -> Field:
    """Read the value inside a detector box several ways and vote. kind: cnic | date | name | gender | text."""
    line = _box_line(box.x0, box.y0, box.x1, box.y1, box.score)
    # the number reads best with a margin; names and dates need a tight crop so the small printed
    # label above them ('Name', 'Date of Birth') is not read into the value
    readings = reread(engine, image, [line], light=(kind != "cnic"), tight=(kind != "cnic"))
    parsers = {"cnic": parse_cnic, "date": parse_card_date, "name": _detected_name,
               "gender": normalize_gender, "text": clean_text}
    parse = parsers[kind]
    parsed = [(parse(t), c) for t, c in readings]
    if kind in ("name", "text"):
        # vote on letters only, so 'AnwarKhan' and 'Anwar Khan' support each other; show the most
        # common spelling of the winner
        keyed = [((re.sub(r"[^a-z]", "", v.lower()) or None) if v else None, c) for v, c in parsed]
        key, conf, _ = vote(keyed)
        spellings = [v for (v, _), (k, _) in zip(parsed, keyed) if k == key and v]
        winner = max(set(spellings), key=lambda v: (spellings.count(v), v.count(" "))) if spellings else None
    else:
        winner, conf, _ = vote(parsed)
    method = "detector+reread_vote"
    if kind == "cnic" and (winner is None or conf < 0.6):
        w2, c2 = vote_digits([(cnic_digits(t), c) for t, c in readings], 13, format_cnic)
        if w2 and c2 > conf:
            winner, conf, method = w2, c2, "detector+digit_vote"
    raws = [t for t, _ in readings]
    raw = max(set(raws), key=raws.count) if raws else None
    if winner is None:
        return Field(None, 0.2, needs_review=True, raw=raw, method="detector+unreadable",
                     note=f"the {kind} box was found but could not be read")
    note = None
    if kind == "name":
        _, notes, unknown = clean_name(winner)
        if unknown:
            conf *= 0.93
            note = "contains a name not in the names list"
    f = review(Field(winner, conf * min(1.0, 0.75 + box.score / 4), raw=raw, method=method, note=note))
    return _cnic_sanity(f) if kind == "cnic" else f
