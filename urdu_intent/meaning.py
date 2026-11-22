"""Second opinion by MEANING: a small multilingual sentence model (paraphrase-multilingual-MiniLM-L12-v2,
ONNX int8, CPU, ~120 MB, Apache-2.0) turns a sentence into a vector; sentences that mean the same thing land
close together even when they share no words ("مجھے ابھی تک رقم نہیں ملی" ~ "میرے پیسے نہیں آئے").

It only RESCUES sentences the keyword matcher was unsure about, and only when it is clearly sure itself
(thresholds tuned so that it adds no wrong intents on the test sentences). Missing model files -> it is
simply off and everything works as before. Get the files with tools/fetch_models.ps1 (or set
MEANING_MODEL_DIR to a folder holding model*.onnx + tokenizer.json).
"""
from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MAX_TOKENS = 64
_lock = threading.Lock()
_state: dict = {"model": None, "error": None}


def model_dir() -> Path:
    return Path(os.environ.get("MEANING_MODEL_DIR") or ROOT / "models" / "meaning")


def available() -> bool:
    d = model_dir()
    return (d / "tokenizer.json").is_file() and any(d.glob("model*.onnx")) and \
        os.environ.get("MEANING_OFF", "").lower() not in ("1", "true", "yes")


class _Encoder:
    def __init__(self, d: Path):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        onnx = sorted(d.glob("model*.onnx"), key=lambda p: (("quint8" not in p.name and "qint8" not in p.name), p.name))[0]
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        self.session = ort.InferenceSession(str(onnx), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding(pad_id=self.tok.token_to_id("<pad>") or 1, pad_token="<pad>")
        self.file = onnx.name

    def encode(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 64):
            enc = self.tok.encode_batch(texts[i:i + 64])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]                     # (batch, tokens, 384)
            m = mask[..., None].astype(np.float32)
            vec = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)    # mean pooling
            out.append(vec / np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-9, None))
        return np.vstack(out) if out else np.zeros((0, 384), dtype=np.float32)


def _encoder() -> _Encoder | None:
    if _state["model"] is not None or _state["error"] is not None:
        return _state["model"]
    with _lock:
        if _state["model"] is None and _state["error"] is None:
            try:
                _state["model"] = _Encoder(model_dir())
            except Exception as e:  # a broken download must not break the app
                _state["error"] = f"{type(e).__name__}: {e}"
    return _state["model"]


@lru_cache(maxsize=1)
def _examples() -> tuple[list[str], np.ndarray]:
    from . import intents
    from .correct import correct
    names, texts = [], []
    for name, spec in intents().items():
        for ex in spec["examples"]:
            names.append(name)
            texts.append(correct(ex).text)
    return names, _encoder().encode(texts)


def status() -> dict:
    if not available():
        return {"on": False, "why": f"no model files in {model_dir()}"}
    enc = _encoder()
    return {"on": enc is not None, "file": enc.file if enc else None, "error": _state["error"]}


def scores(text: str) -> dict[str, float] | None:
    """Best cosine similarity of the sentence to each intent's example questions; None when off."""
    if not available() or _encoder() is None or not (text or "").strip():
        return None
    names, ex = _examples()
    sims = ex @ _encoder().encode([text])[0]
    best: dict[str, float] = {}
    for n, s in zip(names, sims.tolist()):
        if s > best.get(n, -1.0):
            best[n] = s
    return best


def reset():
    """Forget the loaded model and example vectors (after intents.json changes, or in tests)."""
    _state["model"], _state["error"] = None, None
    _examples.cache_clear()
