"""Smart CNIC field detector: a small YOLO model trained on the 'CNIC Detection' dataset (Roboflow,
public domain; 180 training photos of smart CNIC fronts) that boxes the card and each value
(Name Eng, FatherName Eng, Gender Eng, Country Eng, Identity Number, Date of Birth/Issue/Expiry, and
the Urdu Name / Father Name).

It answers 'where is each field', not 'what does it say': each box is then cropped and read by the
normal OCR engine with re-reads and voting. Runs with ONNX Runtime (already a dependency); the
training framework is not needed at run time. Training: tools/train_cnic_detector.md.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = Path(os.environ.get("OCR_CNIC_DETECTOR_PATH",
                                 Path(__file__).resolve().parent / "models" / "cnic_fields.onnx"))
ENABLED = os.environ.get("OCR_CNIC_DETECTOR", "1").lower() not in ("0", "false", "no")
INPUT = 640


@dataclass
class Box:
    name: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float: return self.x1 - self.x0
    @property
    def h(self) -> float: return self.y1 - self.y0


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float = 0.5) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx0 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy0 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx1 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy1 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx1 - xx0, 0, None) * np.clip(yy1 - yy0, 0, None)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        ratio = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][ratio < iou]
    return keep


class FieldDetector:
    def __init__(self, path: Path = MODEL_PATH, threads: int = 2):
        import ast

        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        self.names = ast.literal_eval(meta["names"]) if "names" in meta else {}
        self.version = meta.get("version", "")
        self._lock = threading.Lock()

    def detect(self, image: np.ndarray, min_score: float = 0.25) -> dict[str, Box]:
        """Best box per field, in the coordinates of `image`. The training photos were stretched to
        640x640, so the input is stretched the same way (no letterbox)."""
        h, w = image.shape[:2]
        rgb = cv2.cvtColor(cv2.resize(image, (INPUT, INPUT), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        x = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        with self._lock:
            out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0]  # (4+nc, N)
        pred = out.T
        cls_scores = pred[:, 4:]
        cls = cls_scores.argmax(1)
        score = cls_scores.max(1)
        keep = score >= min_score
        pred, cls, score = pred[keep], cls[keep], score[keep]
        if not len(pred):
            return {}
        cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        sx, sy = w / INPUT, h / INPUT
        xyxy = np.stack([(cx - bw / 2) * sx, (cy - bh / 2) * sy, (cx + bw / 2) * sx, (cy + bh / 2) * sy], 1)
        best: dict[str, Box] = {}
        for c in np.unique(cls):
            idx = np.where(cls == c)[0]
            k = idx[_nms(xyxy[idx], score[idx])[0]]  # each field appears once on a card
            name = self.names.get(int(c), str(int(c)))
            x0, y0, x1, y1 = xyxy[k]
            best[name] = Box(name, float(score[k]), float(max(0, x0)), float(max(0, y0)), float(min(w, x1)),
                             float(min(h, y1)))
        return best


_DETECTOR: FieldDetector | None = None
_LOADED = False


def load_detector() -> FieldDetector | None:
    """The detector, or None when it is switched off (OCR_CNIC_DETECTOR=0) or the model file is missing."""
    global _DETECTOR, _LOADED
    if not _LOADED:
        _LOADED = True
        if ENABLED and MODEL_PATH.exists():
            _DETECTOR = FieldDetector()
    return _DETECTOR
