"""Speech -> text -> intent (urdu_intent). Plain Python, used by the web service and by the command-line tool
tools/voice_cli.py.

Two kinds of speech engine, chosen by WHISPER_MODEL:
    small | medium | turbo        Whisper, through faster-whisper
    indic | indic-onnx            Indic-Transcribe Core (voice_core/indic.py): trained on Urdu among 25 languages
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from urdu_intent import detect_intent, off_topic_reason
from urdu_intent.numbers import spoken_digits

from . import indic

HERE = Path(__file__).resolve().parent.parent  # project root: urdu_intent/ lives there
MODEL_NAME = os.environ.get("WHISPER_MODEL") or "small"   # base | small | medium | turbo | indic | indic-onnx
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


ALIASES = {"turbo": "large-v3-turbo", "large-v3-turbo": "large-v3-turbo"}


def resolve(name: str) -> str:
    """A model downloaded by tools/fetch_models.ps1 (models/whisper-small, models/whisper-turbo) is used
    from there; otherwise faster-whisper downloads it by name. A folder path is used as it is."""
    if Path(name).is_dir():
        return str(Path(name))
    short = "turbo" if ALIASES.get(name) == "large-v3-turbo" else name
    local = HERE / "models" / f"whisper-{short}"
    return str(local) if (local / "model.bin").is_file() else ALIASES.get(name, name)


_models: dict = {}


def load_model(name: str | None = None):
    name = name or MODEL_NAME
    if indic.is_indic(name):
        runtime, folder = indic.find(name)
        key = f"indic:{folder}"
        if key not in _models:
            _models[key] = indic.IndicEngine(str(folder), threads=CPU_THREADS)
        return _models[key]
    from faster_whisper import WhisperModel  # imported here so mock mode needs no model

    key = resolve(name)
    if key not in _models:
        _models[key] = WhisperModel(key, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)
    return _models[key]


def speech_spans(audio: np.ndarray) -> list[dict]:
    """Where someone is speaking (Silero voice detection, shipped with faster-whisper): [{start, end}] in samples."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    return get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))


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


def highpass(audio: np.ndarray, cutoff: float = 100.0) -> np.ndarray:
    """First-order high-pass filter: speech lives above ~100 Hz, fans and traffic rumble below it."""
    if len(audio) < 2:
        return audio
    rc = 1.0 / (2 * np.pi * cutoff)
    a = rc / (rc + 1.0 / 16000)
    out = np.empty_like(audio, dtype=np.float32)
    out[0] = audio[0]
    prev_x, prev_y = float(audio[0]), float(audio[0])
    for i in range(1, len(audio)):
        x = float(audio[i]); prev_y = a * (prev_y + x - prev_x); prev_x = x; out[i] = prev_y
    return out


# Words a recogniser writes when nobody spoke ("شکریہ" / "thank you" from video subtitles; Indic-Transcribe Core
# also writes text on non-speech audio). Real one-word answers (جی، ہاں، نہیں) are NOT in this list, so a short
# genuine reply is never dropped.
SILENCE_WORDS = {"اچھا", "شکریہ", "ہمم", "thank you", "thanks", "you"}
MIN_SPEECH_S = 0.25     # less voice than this (after voice detection) = nobody spoke


def silence_filler(text: str, speech_s: float | None, no_speech: float) -> bool:
    """True when `text` was written over silence, not said."""
    t = text.strip().strip(".!?،۔").lower()
    if not t:
        return False
    if speech_s is not None and speech_s < MIN_SPEECH_S:
        return True
    return t in SILENCE_WORDS and no_speech >= 0.5


def _transcribe_indic(engine, audio: np.ndarray, language: str) -> tuple[str, float, float]:
    """-> (text, seconds of speech, no-speech score). Only the part with speech is sent to the model: it writes
    words on silence, and a shorter clip is faster."""
    spans = speech_spans(audio)
    speech_s = sum(sp["end"] - sp["start"] for sp in spans) / 16000
    if not spans or speech_s < MIN_SPEECH_S:
        return "", speech_s, 1.0
    clip = audio[max(0, spans[0]["start"]):min(len(audio), spans[-1]["end"])]
    text = spoken_digits(engine.transcribe(clip, language=language))
    return text, speech_s, 0.0


def transcribe(audio: np.ndarray, model: str | None = None, language: str = "ur") -> dict:
    """quality: ok | silent (nothing said) | noisy (sound, but no clear speech: ask for a quieter place)."""
    seconds = len(audio) / 16000
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if peak < 1e-4:
        return {"text": "", "seconds_audio": round(seconds, 1), "seconds_taken": 0.0, "quality": "silent"}
    rms = float(np.sqrt(np.mean(np.square(audio))))
    audio = highpass(audio)                             # fan hum and traffic rumble (< ~100 Hz) out
    peak = float(np.abs(audio).max()) or 1.0
    audio = (audio / peak * 0.9).astype(np.float32)   # quiet phone recordings -> normal level
    t0 = time.time()
    engine = load_model(model)
    if isinstance(engine, indic.IndicEngine):
        with _lock:
            text, speech_s, no_speech = _transcribe_indic(engine, audio, language)
        if silence_filler(text, speech_s, no_speech):
            text = ""
        quality = "ok" if text else ("noisy" if rms > 0.02 else "silent")
        if noise_transcript(text):
            quality = "noisy"
        return {"text": text, "seconds_audio": round(seconds, 1), "seconds_taken": round(time.time() - t0, 1),
                "quality": quality}
    with _lock:
        # No initial_prompt: with a short or unclear clip Whisper repeated the prompt's word list for over a
        # minute (seen on a 2 s clip). Spelling of claim words is fixed afterwards by urdu_intent's
        # sound-alike correction instead. Output length is capped by the clip length for the same reason.
        segments, info = engine.transcribe(audio, language=language, task="transcribe", beam_size=5,
                                           vad_filter=True, condition_on_previous_text=False,
                                           without_timestamps=True,
                                           max_new_tokens=int(20 + 10 * seconds))
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
    no_speech = max((s.no_speech_prob for s in segments), default=1.0)
    if silence_filler(text, getattr(info, "duration_after_vad", None), no_speech):
        text = ""
    quality = "ok" if text and no_speech < 0.6 else ("noisy" if rms > 0.02 or text else "silent")
    if noise_transcript(text):
        quality = "noisy"
    return {"text": text, "seconds_audio": round(seconds, 1), "seconds_taken": round(time.time() - t0, 1),
            "quality": quality}


def noise_transcript(text: str) -> bool:
    """Words Whisper produces from noise, not speech: 'subscribe' / 'ناظرین' (it learned from video subtitles),
    or one word over and over ('ایسا ایسا ایسا ایسا', seen on loud fan-like noise). The app then asks for a
    quieter place instead of acting on them."""
    if not text:
        return False
    if off_topic_reason(text) == "noise":
        return True
    words = text.split()
    return len(words) >= 4 and max(words.count(w) for w in set(words)) >= 4 and len(set(words)) * 2 <= len(words)


def understand_bytes(data: bytes, language: str = "ur") -> dict:
    """language: 'ur' (Urdu, default) or 'en' (English mode: the caller works out the intent)."""
    stt = transcribe(decode(data), language=language)
    return {"transcript": stt["text"], "model": MODEL_NAME, "seconds_audio": stt["seconds_audio"],
            "seconds_taken": stt["seconds_taken"], "audio_quality": stt.get("quality", "ok"), "language": language,
            **detect_intent(stt["text"])}
