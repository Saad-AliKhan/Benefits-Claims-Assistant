# -*- coding: utf-8 -*-
"""Indic-Transcribe Core (Bodhan AI, IIT Madras, with AI4Bharat) as Aasra's Urdu speech engine.

What it is: a 1.2B-parameter speech recogniser for 25 Indian languages + English (NVIDIA Canary-1b-v2
architecture: FastConformer encoder + Transformer decoder). Urdu is supported ('ur', Perso-Arabic script); on the
Voice of India benchmark its Urdu error (OIWER) is 5.0. Not a Whisper model, so it runs through its own code, not
faster-whisper.

Licence: Indic Open Model License v1.0 (free for research, government, non-profit and commercial use; credit
Bodhan AI; hosting it as an API for third parties needs Bodhan AI's written approval unless the operator is a
non-profit, government or academic body). Base model nvidia/canary-1b-v2: CC-BY-4.0.

Two ways to run it, picked by the folder it is in (tools/voice/fetch_indic.py downloads either):

    models/indic-transcribe-core       official checkpoint, PyTorch (4.6 GB on disk, ~5 GB RAM). Needs
                                       requirements-indic.txt (torch, torchaudio, transformers, sentencepiece,
                                       soundfile). Most accurate.
    models/indic-transcribe-onnx-int8  community ONNX export (hari31416/indic-transcribe-onnx-int8): 1.5 GB,
                                       ~2.5 GB RAM, about 2x faster on CPU, same text as PyTorch on its tests.
                                       Unofficial.

Things this wrapper handles, from the model card:
  * Language: always passed ('ur' or 'en'). Its automatic language detection often hears Urdu as Hindi.
  * Silence: like other recognisers it writes words on non-speech audio, so voice_core runs voice detection
    first and never sends it a clip with no speech.
  * Numbers come out as words (no inverse text normalisation): voice_core turns runs of number words into
    digits (urdu_intent/numbers.py), so a CNIC said aloud still works.
  * Length: trained on clips up to 30 s; the app's limit is 30 s.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = {"pytorch": ROOT / "models" / "indic-transcribe-core",
           "onnx": ROOT / "models" / "indic-transcribe-onnx-int8"}
NAMES = {"indic": None, "indic-core": None, "indic-transcribe-core": None,     # None = whichever is downloaded
         "indic-pytorch": "pytorch", "indic-onnx": "onnx"}
HF_REPOS = {"pytorch": "bodhan-ai/indic-transcribe-core", "onnx": "hari31416/indic-transcribe-onnx-int8"}


class IndicMissing(RuntimeError):
    pass


def is_indic(name: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    return n in NAMES or "indic-transcribe" in Path(n).name


def find(name: str) -> tuple[str, Path]:
    """-> (runtime 'pytorch' | 'onnx', folder). A folder path is used as it is."""
    p = Path(name)
    if p.is_dir():
        return ("onnx" if any(p.glob("*.onnx")) or any(p.glob("onnx/*.onnx")) else "pytorch"), p
    want = NAMES.get(name.lower())
    order = [want] if want else ["pytorch", "onnx"]
    for runtime in order:
        folder = FOLDERS[runtime]
        if folder.is_dir() and any(folder.iterdir()):
            return runtime, folder
    raise IndicMissing("Indic-Transcribe Core is not downloaded. Accept its licence on Hugging Face "
                       "(huggingface.co/bodhan-ai/indic-transcribe-core), run 'hf auth login', then "
                       "'python tools/voice/fetch_indic.py' (see README, 'Speech models').")


def _write_wav(audio: np.ndarray) -> str:
    """16 kHz mono float -> a temporary 16-bit WAV file (both runtimes take a file path)."""
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="aasra-")
    os.close(fd)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return path


def _text(out) -> str:
    """The runtimes return a string, a dict with 'text', or a list of either."""
    if isinstance(out, (list, tuple)):
        return " ".join(_text(o) for o in out).strip()
    if isinstance(out, dict):
        return str(out.get("text") or out.get("transcript") or "").strip()
    return str(out or "").strip()


def _import_from(folder: Path, module: str):
    """Import the model's own inference code, which ships in its folder."""
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    return importlib.import_module(module)


class IndicEngine:
    """Same job as a faster-whisper model in voice_core: audio (16 kHz mono float32) -> text."""

    def __init__(self, name: str = "indic", threads: int = 0):
        self.runtime, self.folder = find(name)
        self.name = f"indic-transcribe-core ({self.runtime})"
        self._lock = threading.Lock()
        if self.runtime == "pytorch":
            import torch  # noqa: F401  (a clear ImportError if requirements-indic.txt is not installed)
            if threads:
                torch.set_num_threads(threads)
            mod = _import_from(self.folder, "indic_transcribe")
            try:
                self._model = mod.IndicTranscribe.from_pretrained(str(self.folder), device="cpu")
            except TypeError:  # older code without a device argument
                self._model = mod.IndicTranscribe.from_pretrained(str(self.folder))
        else:
            mod = _import_from(self.folder, "pipeline_onnx")
            self._model = mod.IndicTranscribeONNX(self.folder)

    def transcribe(self, audio: np.ndarray, language: str = "ur") -> str:
        lang = language if language in ("ur", "en") else "ur"
        path = _write_wav(audio)
        try:
            with self._lock:
                if self.runtime == "pytorch":
                    out = self._model(path, lang=lang)
                else:
                    out = self._model.transcribe(path, lang=lang, mode="native")
            return _text(out)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
