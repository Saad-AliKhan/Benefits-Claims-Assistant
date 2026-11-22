"""Speech -> text (faster-whisper) -> intent (urdu_intent). Plain Python, used by the web service
and by the command-line tool tools/voice_cli.py."""
from __future__ import annotations

import io
import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from urdu_intent import detect_intent

HERE = Path(__file__).resolve().parent.parent  # project root: urdu_intent/ lives there
MODEL_NAME = os.environ.get("WHISPER_MODEL") or "small"   # base | small | medium | large-v3-turbo
CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "0"))  # 0 = let CTranslate2 decide
MAX_SECONDS = float(os.environ.get("VOICE_MAX_SECONDS", "30"))
_lock = threading.Lock()


class BadAudio(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


@lru_cache(maxsize=1)
def vocabulary_prompt() -> str:
    """Claim words from the sound-alike dictionary; helps Whisper spell them correctly."""
    words = json.loads((HERE / "urdu_intent" / "sound_alikes.json").read_text(encoding="utf-8"))["words"]
    return "، ".join(list(words)[:25])


@lru_cache(maxsize=1)
def load_model():
    from faster_whisper import WhisperModel  # imported here so mock mode needs no model

    return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)


def decode(data: bytes) -> np.ndarray:
    """Any common audio format (wav, m4a, mp3, ogg, browser webm/opus) -> 16 kHz mono float32."""
    from faster_whisper.audio import decode_audio

    try:
        audio = decode_audio(io.BytesIO(data))
    except Exception as exc:  # PyAV raises many error types for broken files
        raise BadAudio("unreadable_audio", "the file could not be decoded as audio") from exc
    seconds = len(audio) / 16000
    if seconds > MAX_SECONDS:
        raise BadAudio("too_long", f"{seconds:.0f} s of audio; keep questions under {MAX_SECONDS:.0f} s")
    return audio


def transcribe(audio: np.ndarray) -> dict:
    """quality: ok | silent (nothing said) | noisy (sound, but no clear speech: ask for a quieter place)."""
    seconds = len(audio) / 16000
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if peak < 1e-4:
        return {"text": "", "seconds_audio": round(seconds, 1), "seconds_taken": 0.0, "quality": "silent"}
    rms = float(np.sqrt(np.mean(np.square(audio))))
    audio = (audio / peak * 0.9).astype(np.float32)   # quiet phone recordings -> normal level
    t0 = time.time()
    with _lock:
        segments, _ = load_model().transcribe(audio, language="ur", task="transcribe", beam_size=5,
                                              vad_filter=True, initial_prompt=vocabulary_prompt())
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
    no_speech = max((s.no_speech_prob for s in segments), default=1.0)
    quality = "ok" if text and no_speech < 0.6 else ("noisy" if rms > 0.02 or text else "silent")
    return {"text": text, "seconds_audio": round(seconds, 1), "seconds_taken": round(time.time() - t0, 1),
            "quality": quality}


def understand_bytes(data: bytes) -> dict:
    stt = transcribe(decode(data))
    return {"transcript": stt["text"], "model": MODEL_NAME, "seconds_audio": stt["seconds_audio"],
            "seconds_taken": stt["seconds_taken"], "audio_quality": stt.get("quality", "ok"),
            **detect_intent(stt["text"])}
