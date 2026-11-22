"""Finding labels and their values among OCR lines, independent of where the document sits in the photo.

A value is located relative to its printed label ('CNIC No :' -> the text to its right, or just
below it on smart cards), never by fixed pixel positions, so tilt, crop and zoom do not matter.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .datatypes import Line


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _orig_index_after(text: str, n_alnum: int) -> int:
    """Index in `text` just after its first n_alnum letters/digits."""
    count = 0
    for i, ch in enumerate(text):
        if ch.isalnum():
            count += 1
            if count == n_alnum:
                return i + 1
    return len(text)


LOOKALIKE_PAIRS = [("in", "m"), ("rn", "m"), ("ii", "u"), ("vv", "w"), ("cl", "d"), ("li", "h")]


@dataclass
class LabelHit:
    line: Line
    score: float
    remainder: str  # text on the same OCR line after the label ('Relation with Deceased: Daughter')


def match_label(line: Line, alias: str) -> LabelHit | None:
    """Does this line start with the label? Tolerates OCR slips ('Dato of Death!', 'CNICNo',
    'Namet'). Returns the text after the label as `remainder`."""
    t0, a = norm(line.text), norm(alias)
    if not t0 or not a or len(t0) < len(a) - 2:
        return None
    best, best_k = 0.0, 0
    # also try the text with one common print confusion undone ('Naine' -> 'Name', 'Rellglon')
    variants = [(t0, -1, 0)]
    for src, dst in LOOKALIKE_PAIRS:
        i = t0.find(src)
        if i >= 0:
            variants.append((t0[:i] + dst + t0[i + len(src):], i, len(src) - len(dst)))
    for t, at, shift in variants:
        for k in range(max(1, len(a) - 2), min(len(t), len(a) + 2) + 1):
            s = difflib.SequenceMatcher(None, t[:k], a).ratio()
            if s > best:
                best, best_k = s, (k + shift if 0 <= at < k else k)
    need = 0.86 if len(a) <= 5 else 0.8
    if best < need:
        return None
    rem = line.text[_orig_index_after(line.text, best_k):]
    rem = rem.lstrip(" :;.,!?_-'|").strip()
    if len(rem) <= 2 and not re.search(r"\d", rem):
        rem = ""  # a stray ':' read as a letter ('Namet')
    return LabelHit(line, best, rem)


def find_label(lines: list[Line], aliases: list[str], y_min: float = -1e9, y_max: float = 1e9,
               x_max: float = 1e9, used: set[int] | None = None) -> LabelHit | None:
    best: LabelHit | None = None
    for ln in lines:
        if not (y_min <= ln.cy <= y_max) or ln.x0 > x_max or (used and id(ln) in used):
            continue
        for alias in aliases:
            hit = match_label(ln, alias)
            if hit and (best is None or hit.score > best.score):
                best = hit
    return best


def same_row(a: Line, b: Line, tol: float = 0.6) -> bool:
    return abs(a.cy - b.cy) <= tol * max(a.h, b.h)


def values_right(lines: list[Line], label: Line, x_max: float, stop_aliases: list[str],
                 max_gap_h: float = 12.0) -> list[Line]:
    """Lines on the label's row, to its right and left of x_max, nearest first, stopping at the
    next printed label ('Gender: Female  Religion: Islam')."""
    cands = sorted((ln for ln in lines if ln is not label and same_row(ln, label)
                    and ln.x0 >= label.x1 - 0.5 * label.h and ln.x0 < x_max), key=lambda ln: ln.x0)
    out: list[Line] = []
    prev_x1 = label.x1
    for ln in cands:
        if ln.x0 - prev_x1 > max_gap_h * label.h:
            break
        if any(match_label(ln, a) for a in stop_aliases):
            break
        out.append(ln)
        prev_x1 = ln.x1
    return out


def value_below(lines: list[Line], label: Line, max_rows: float = 2.6) -> Line | None:
    """The line just under a label, starting near the label's left edge (smart CNIC layout)."""
    best, best_d = None, 1e9
    for ln in lines:
        if ln is label or ln.y0 < label.y1 - 0.3 * label.h or ln.y0 > label.y1 + max_rows * label.h:
            continue
        if abs(ln.x0 - label.x0) > 2.5 * label.h and not (ln.x0 <= label.x0 <= ln.x1):
            continue
        d = (ln.y0 - label.y1) + 0.3 * abs(ln.x0 - label.x0)
        if d < best_d:
            best, best_d = ln, d
    return best


def horizontal(lines: list[Line]) -> list[Line]:
    """Lines whose box is wider than tall. On a sideways photo the recogniser still reads some text
    (it turns tall boxes), so orientation is judged on horizontal lines only."""
    return [ln for ln in lines if (ln.x1 - ln.x0) > 1.2 * ln.h or len(ln.text) <= 3]


def page_extent(lines: list[Line]) -> tuple[float, float, float, float]:
    xs0 = sorted(ln.x0 for ln in lines)
    xs1 = sorted(ln.x1 for ln in lines)
    # ignore the extreme 2% so a speck outside the page does not stretch it
    k = max(0, len(lines) // 50)
    return xs0[k], min(ln.y0 for ln in lines), xs1[-1 - k], max(ln.y1 for ln in lines)


def join_text(lines: list[Line]) -> str:
    return " ".join(ln.text for ln in lines).strip()


def mean_conf(lines: list[Line]) -> float:
    return sum(ln.conf for ln in lines) / len(lines) if lines else 0.0
