"""Shared first stage for every document: quality gate, crop, enlarge, read, straighten, turn upright."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .imaging import check_quality, find_document, resize_long_side, rotate, text_skew, warp_document
from .datatypes import BadImage, Line


PROBE_LONG_SIDE = 1200
SKEW_MIN_DEG = 1.0


@dataclass
class Prepared:
    image: np.ndarray          # the cleaned-up image all coordinates refer to
    lines: list[Line]
    quality: dict = field(default_factory=dict)


def prepare(engine, img: np.ndarray, long_side: int, anchor_score: Callable[[list[Line]], float],
            min_score: float, min_long_side: int = 0) -> Prepared:
    """Quality-check, crop to the document, enlarge to `long_side`, read, and straighten.

    `anchor_score(lines)` measures how much of the expected document was recognised (printed
    headings and labels). If the first reading scores below `min_score` the photo is tried turned
    90, 270 and 180 degrees, and the best orientation is kept."""
    quality = check_quality(img)
    corners = find_document(img)
    if corners is not None:
        img = warp_document(img, corners)
    quality["document_cropped"] = corners is not None

    if max(img.shape[:2]) < min_long_side:
        raise BadImage("too_small", f"the document is only {max(img.shape[:2])}px on its long side; "
                                    f"at least {min_long_side}px is needed to read it")
    base, _ = resize_long_side(img, long_side)
    work = base
    lines = engine.read(work)
    score, turned = anchor_score(lines), 0
    if score < min_score:
        # Not recognisable as it is: compare all four turns on a smaller copy (faster), then read
        # the best one at full size. All four are compared because a sideways page can still
        # score a little (the recogniser turns tall text boxes) and must not win over upright.
        probe, _ = resize_long_side(img, PROBE_LONG_SIDE)
        scores = {a: anchor_score(engine.read(rotate(probe, a))) for a in (0, 90, 180, 270)}
        best = max(scores, key=lambda a: (scores[a], a == 0))
        if best != 0 and scores[best] > scores[0]:
            work = rotate(base, best)
            lines = engine.read(work)
            score, turned = anchor_score(lines), best
    quality["rotated_degrees"] = turned

    skew = text_skew(lines)
    if abs(skew) > SKEW_MIN_DEG:  # smaller tilts do not affect reading; skip the second read
        straight = rotate(work, -skew)
        straight_lines = engine.read(straight)
        if anchor_score(straight_lines) >= score:
            work, lines = straight, straight_lines
            quality["deskewed_degrees"] = round(skew, 2)
    if not lines:
        raise BadImage("no_text_found", "no text could be found in the photo")
    quality["anchor_score"] = round(score, 2)
    return Prepared(work, lines, quality)
