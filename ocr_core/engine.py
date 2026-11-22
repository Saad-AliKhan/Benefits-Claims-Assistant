"""OCR engine wrapper.

The default engine is RapidOCR: the same PP-OCRv4 detection and recognition models as PaddleOCR,
run with ONNX Runtime. The models ship inside the pip package (about 15 MB), so the service needs
no model download, starts in a second or two and runs in well under 1 GB of RAM, which matters for
free hosting tiers. Anything that can return text lines with boxes and scores can replace it: give
it a `read(image_bgr) -> list[Line]` method and a `name`.
"""
from __future__ import annotations

import threading

import numpy as np

from .config import SETTINGS
from .datatypes import Line


class RapidEngine:
    name = "rapidocr-onnxruntime/PP-OCRv4"

    def __init__(self, threads: int | None = None):
        from rapidocr_onnxruntime import RapidOCR

        n = threads or SETTINGS.CPU_THREADS
        threads_kw = {f"{p}intra_op_num_threads": n for p in ("", "det_", "rec_", "cls_")}
        threads_kw.update({f"{p}inter_op_num_threads": 1 for p in ("", "det_", "rec_", "cls_")})
        # whole pages: keep full resolution (the default would shrink anything over 2000 px)
        self._ocr = RapidOCR(max_side_len=3000, **threads_kw)
        # small crops for re-reading: the default detector would enlarge a 130 px strip to 736 px
        # high (about 0.5 s each); cap it instead, the crops are already enlarged by reread.py
        self._crop_ocr = RapidOCR(det_limit_type="max", det_limit_side_len=960, **threads_kw)
        self._lock = threading.Lock()

    def read(self, image: np.ndarray, text_score: float = 0.5, crop: bool = False) -> list[Line]:
        """Read every text line in a BGR image. Text-direction classification is off: documents are
        straightened before reading, and the classifier sometimes flips short digit groups."""
        ocr = self._crop_ocr if crop else self._ocr
        with self._lock:
            result, _ = ocr(image, use_cls=False, text_score=text_score)
        lines = []
        for box, text, score in result or []:
            lines.append(Line(text=str(text).strip(), conf=float(score), box=np.asarray(box, dtype=np.float32)))
        lines.sort(key=lambda ln: (round(ln.cy / max(ln.h, 1)), ln.x0))
        return [ln for ln in lines if ln.text]


_ENGINE: RapidEngine | None = None


def load_engine() -> RapidEngine:
    """Create the engine once per process and reuse it (loading takes ~1 s)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RapidEngine()
    return _ENGINE
