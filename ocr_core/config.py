"""Tunable thresholds. Every value can be overridden with an environment variable of the same
name, so the numbers can be changed without touching code."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # A field below this confidence is marked needs_review.
    REVIEW_BELOW: float = _f("OCR_REVIEW_BELOW", 0.85)
    # Photo quality gate (variance of the Laplacian at 1000 px width). Below REJECT the photo is
    # refused with 'blurry'; below WARN it is read but a warning is added.
    BLUR_REJECT: float = _f("OCR_BLUR_REJECT", 25)
    BLUR_WARN: float = _f("OCR_BLUR_WARN", 80)
    # Share of the image that is blown-out white glare.
    GLARE_REJECT: float = _f("OCR_GLARE_REJECT", 0.10)
    MIN_SIDE_PX: int = int(_f("OCR_MIN_SIDE_PX", 300))
    # Death registered this many days (or more) after the death -> LATE_REGISTRATION flag.
    LATE_REGISTRATION_DAYS: int = int(_f("OCR_LATE_REGISTRATION_DAYS", 365))
    # Domain a genuine certificate's QR code should point to.
    QR_TRUSTED_DOMAIN: str = os.environ.get("OCR_QR_TRUSTED_DOMAIN", "crms.nadra.gov.pk")
    # Long side (px) each document is scaled to before reading. Small photos are enlarged,
    # which helps the OCR more than any other single setting.
    DEATH_CERT_LONG_SIDE: int = int(_f("OCR_DEATH_CERT_LONG_SIDE", 2600))
    CNIC_LONG_SIDE: int = int(_f("OCR_CNIC_LONG_SIDE", 1600))
    # Smallest usable photo (long side, px, after cropping to the document). A whole A4 page needs
    # more pixels than a card for its small print to be legible.
    DEATH_CERT_MIN_LONG_SIDE: int = int(_f("OCR_DEATH_CERT_MIN_LONG_SIDE", 1000))
    CNIC_MIN_LONG_SIDE: int = int(_f("OCR_CNIC_MIN_LONG_SIDE", 600))
    CPU_THREADS: int = int(_f("OCR_CPU_THREADS", 2))


SETTINGS = Settings()
