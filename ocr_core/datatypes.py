"""Shared data types: OCR lines, extracted fields, flags and the readable-image error."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


class BadImage(Exception):
    """The photo cannot be read reliably. `reason` is a stable code the backend can map to a
    'please retake' message; the API returns it with HTTP 422."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class Line:
    """One line of text found by the OCR engine. `box` is 4 corner points (x, y) in image pixels."""
    text: str
    conf: float
    box: np.ndarray

    @property
    def x0(self) -> float: return float(self.box[:, 0].min())
    @property
    def x1(self) -> float: return float(self.box[:, 0].max())
    @property
    def y0(self) -> float: return float(self.box[:, 1].min())
    @property
    def y1(self) -> float: return float(self.box[:, 1].max())
    @property
    def cx(self) -> float: return (self.x0 + self.x1) / 2
    @property
    def cy(self) -> float: return (self.y0 + self.y1) / 2
    @property
    def h(self) -> float: return max(1.0, self.y1 - self.y0)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Line({self.text!r}, {self.conf:.2f}, x={self.x0:.0f}-{self.x1:.0f}, y={self.y0:.0f}-{self.y1:.0f})"


@dataclass
class Field:
    """One extracted value with everything a reviewer needs to trust or check it.

    value         normalised value (ISO dates, CNIC with dashes) or None when blank / not found
    confidence    0..1, how sure the service is that `value` is right (blank counts as a value)
    needs_review  True when a person should compare it with the photo
    raw           the text exactly as the OCR read it
    method        how the value was obtained (ocr, ocr+urdu_side_agree, reread_vote, derived_from_cnic...)
    note          short human-readable explanation (corrections, disagreements, why review)
    """
    value: Any = None
    confidence: float = 0.0
    needs_review: bool = False
    raw: str | None = None
    method: str = "ocr"
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"value": self.value, "confidence": round(float(self.confidence), 3),
               "needs_review": bool(self.needs_review), "method": self.method}
        if self.raw is not None:
            out["raw"] = self.raw
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Flag:
    """A finding about the document as a whole. Flags never change values; the backend's rules
    decide what to do with them. severity: info | warning | critical."""
    code: str
    severity: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass
class Extraction:
    doc_type: str
    fields: dict[str, Field]
    flags: list[Flag] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    key_fields: tuple[str, ...] = ()
