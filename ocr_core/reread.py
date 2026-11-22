"""Re-reading one small region several ways and voting.

Used for the values that matter most (CNIC numbers, dates). The line is cropped, enlarged and
read in several versions (colour, contrast-stretched, thresholded, softened); each reading is
normalised and the readings vote. Agreement between versions is the confidence. This is what
gets '32103-9963008-2' right on a low-resolution photo of a green card where a single read
returns '32103-99630080'.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

import cv2
import numpy as np

from .imaging import crop_box
from .datatypes import Line


def _variants(crop: np.ndarray, text_h: float, light: bool = False) -> list[np.ndarray]:
    """Up to 12 versions (3 sizes x 4 contrast treatments), or 6 when `light` (2 sizes x colour,
    threshold, contrast-stretch) for values that are easier to read, such as dates."""
    base = 42.0 / max(text_h, 1.0)
    out = []
    v = crop.max(axis=2)  # brightness: dark ink is dark on white paper and on the green card alike
    factors = (1.0, 1.6) if light else (1.0, 1.6, 2.2)
    for s in sorted({min(4.0, max(1.0, base * k)) for k in factors}):
        col = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        vv = cv2.resize(v, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        _, otsu = cv2.threshold(vv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        soft = cv2.GaussianBlur(vv, (5, 5), 0)
        _, otsu_soft = cv2.threshold(soft, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        clahe = cv2.createCLAHE(2.0, (8, 8)).apply(vv)
        for img in ((col, otsu, clahe) if light else (col, otsu, otsu_soft, clahe)):
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            out.append(cv2.copyMakeBorder(img, 24, 24, 24, 24, cv2.BORDER_REPLICATE))
    return out


def reread(engine, image: np.ndarray, lines: list[Line], light: bool = False,
           tight: bool = False) -> list[tuple[str, float]]:
    """Read the region covered by `lines` in every variant; return (text, mean confidence) per variant.
    `tight` is for detector boxes, which hug the value: a smaller margin, and only the largest text in
    the crop is kept, so a small printed label just above the value ('Name') is left out."""
    if not lines:
        return []
    x0, y0 = min(ln.x0 for ln in lines), min(ln.y0 for ln in lines)
    x1, y1 = max(ln.x1 for ln in lines), max(ln.y1 for ln in lines)
    h = max(ln.h for ln in lines)
    pad_x, pad_y = (0.4 * h, 0.12 * h) if tight else (0.8 * h, 0.5 * h)
    crop = crop_box(image, x0, y0, x1, y1, pad_x=pad_x, pad_y=pad_y)
    if crop.size == 0:
        return []
    readings = []
    for var in _variants(crop, h, light):
        found = engine.read(var, text_score=0.3, crop=True)
        if not found:
            continue
        mid = var.shape[0] / 2
        row = [ln for ln in found if abs(ln.cy - mid) < 0.45 * var.shape[0]]
        if tight and row:
            tallest = max(row, key=lambda ln: ln.h)
            row = [ln for ln in row if ln.h >= 0.65 * tallest.h and abs(ln.cy - tallest.cy) < 0.6 * tallest.h]
        row = sorted(row, key=lambda ln: ln.x0)
        if row:
            readings.append((" ".join(ln.text for ln in row), sum(ln.conf for ln in row) / len(row)))
    return readings


def vote(candidates: list[tuple[str | None, float]]) -> tuple[str | None, float, int]:
    """candidates: (normalised value or None, ocr confidence). Returns (winner, confidence, n_valid).
    Confidence = share of valid readings that agree x their mean OCR confidence. Readings that
    could not be parsed at all (a digit cut off in one version) lower it only slightly."""
    groups: dict[str, list[float]] = defaultdict(list)
    invalid = 0
    for value, conf in candidates:
        if value is None:
            invalid += 1
        else:
            groups[value].append(conf)
    if not groups:
        return None, 0.0, 0
    n_valid = sum(len(g) for g in groups.values())
    winner = max(groups, key=lambda k: (len(groups[k]), sum(groups[k])))
    support = len(groups[winner]) / (n_valid + 0.25 * invalid)
    conf = support * (sum(groups[winner]) / len(groups[winner]))
    return winner, conf, n_valid


def vote_digits(candidates: list[tuple[str | None, float]], length: int,
                fmt: Callable[[str], str | None]) -> tuple[str | None, float]:
    """Position-by-position vote over digit strings of the right length, used when no complete
    reading wins outright. Confidence is the weakest position's agreement."""
    rows = [(v, c) for v, c in candidates if v and len(v) == length]
    if not rows:
        return None, 0.0
    digits, weakest = [], 1.0
    for i in range(length):
        tally: dict[str, float] = defaultdict(float)
        for v, c in rows:
            tally[v[i]] += c
        best = max(tally, key=tally.get)
        digits.append(best)
        weakest = min(weakest, tally[best] / sum(tally.values()))
    return fmt("".join(digits)), weakest * (sum(c for _, c in rows) / len(rows))
