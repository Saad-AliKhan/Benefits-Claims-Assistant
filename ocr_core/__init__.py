"""ocr_core: reads Pakistani CNICs and Punjab death registration certificates from photos.

Plain Python, no web framework. The FastAPI app in /app wraps it; a Python backend (Django,
FastAPI) can also import it directly:

    from ocr_core import load_engine, read_document
    result = read_document(load_engine(), "death_certificate", image_bytes)
"""
from __future__ import annotations

import time
from datetime import date

from .cnic import extract_cnic
from .config import SETTINGS
from .death_certificate import extract_death_certificate
from .engine import load_engine
from .imaging import load_image
from .datatypes import BadImage, Extraction

__version__ = "1.0.0"
__all__ = ["load_engine", "read_document", "BadImage", "DOC_TYPES", "__version__"]

DOC_TYPES = {"cnic": extract_cnic, "death_certificate": extract_death_certificate}


def to_result(ex: Extraction, engine_name: str, ms: int) -> dict:
    present = [ex.fields[k].confidence if ex.fields.get(k) and ex.fields[k].value is not None else 0.0
               for k in ex.key_fields]
    overall = min(present) if present else 0.0
    return {
        "doc_type": ex.doc_type,
        "ocr_version": __version__,
        "engine": engine_name,
        "quality": {"ok": True, **ex.quality},
        "fields": {k: v.to_dict() for k, v in ex.fields.items()},
        "flags": [fl.to_dict() for fl in ex.flags],
        "needs_review_fields": [k for k, v in ex.fields.items() if v.needs_review],
        "overall_confidence": round(overall, 3),
        "review_threshold": SETTINGS.REVIEW_BELOW,
        "processing_ms": ms,
    }


def read_document(engine, doc_type: str, data: bytes, today: date | None = None) -> dict:
    """Read one photo. Raises BadImage when the photo should be retaken."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown doc_type {doc_type!r}")
    t0 = time.perf_counter()
    img = load_image(data)
    ex = DOC_TYPES[doc_type](engine, img, today=today)
    return to_result(ex, engine.name, int((time.perf_counter() - t0) * 1000))
