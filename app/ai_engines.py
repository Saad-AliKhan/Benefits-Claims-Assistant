# -*- coding: utf-8 -*-
"""The two AI engines, running inside this app (no separate services):

    OCR    ocr_core/       CNIC front + death certificate -> fields, confidences, flags
    voice  voice_core/     Urdu speech -> text (Whisper, on this machine) -> intent (urdu_intent/)

Both load in the background when the app starts, so pages work at once; until an engine is ready its
calls answer "unavailable" and the claim flow uses its fallbacks. Every function returns a plain dict
and NEVER raises into the claim flow:

    {"status": "ok",           "result": {...}}
    {"status": "retake",       "detail": {...}}      OCR: ask for a new photo
    {"status": "record_again", "detail": {...}}      voice: ask to record again
    {"status": "unavailable",  "error": "..."}       engine not ready / failed: use the fallback

`detail` always has `reason`, `message_en` and `message_ur`. Mock modes (OCR_MOCK / VOICE_MOCK) answer
instantly from data/ocr_fixtures/ or a fixed sentence, for building screens. Nothing here logs field
values or transcripts (personal data).
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.ocr_messages import retake as retake_message

log = logging.getLogger("lastmile.ai")
OK, RETAKE, RECORD_AGAIN, UNAVAILABLE = "ok", "retake", "record_again", "unavailable"
FIXTURES = Path(__file__).resolve().parent.parent / "data" / "ocr_fixtures"
MOCK_SENTENCE = "مجھے پیسے کب ملیں گے"

_state = {"ocr": None, "ocr_error": None, "voice_ready": False, "voice_error": None}
_ocr_lock = threading.Lock()     # one OCR job at a time (CPU and memory bound)
_started = threading.Event()


def new_request_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- start-up
def _load_ocr():
    try:
        import numpy as np
        from ocr_core import load_engine
        engine = load_engine()
        engine.read(np.full((64, 256, 3), 255, np.uint8))  # warm-up
        _state["ocr"] = engine
        log.info("OCR engine ready: %s", engine.name)
    except Exception as e:  # missing package, broken model file...
        _state["ocr_error"] = f"{type(e).__name__}: {e}"
        log.error("OCR engine could not start: %s", _state["ocr_error"])


def _load_voice():
    try:
        import os
        os.environ["WHISPER_MODEL"] = settings.whisper_model  # read by voice_core when it is imported
        import voice_core
        voice_core.load_model()  # first start downloads the Whisper model (about 500 MB for 'small')
        _state["voice_ready"] = True
        log.info("Whisper model ready: %s", voice_core.MODEL_NAME)
    except Exception as e:  # no internet on first start, missing package...
        _state["voice_error"] = f"{type(e).__name__}: {e}"
        log.error("Whisper could not start: %s", _state["voice_error"])


def start_loading() -> None:
    """Called once when the app starts. Loads the engines in background threads."""
    if _started.is_set():
        return
    _started.set()
    if not settings.ocr_mock:
        threading.Thread(target=_load_ocr, name="load-ocr", daemon=True).start()
    if not settings.voice_mock and settings.voice_preload:
        threading.Thread(target=_load_voice, name="load-whisper", daemon=True).start()
    threading.Thread(target=_load_meaning, name="load-meaning", daemon=True).start()


def _load_meaning() -> None:
    """The meaning model (optional): load it and its example vectors now, not on the first question."""
    try:
        from urdu_intent import meaning
        if meaning.available():
            meaning.scores("سلام")
    except Exception:  # noqa: BLE001 - optional; status() shows the error
        log.exception("meaning model failed to load")


def _meaning_status() -> dict:
    try:
        from urdu_intent import meaning
        return meaning.status()
    except Exception as e:  # noqa: BLE001
        return {"on": False, "error": str(e)}


def status() -> dict:
    """For GET /health/ai: is each engine ready?"""
    return {
        "ocr": {"mock": settings.ocr_mock, "ready": settings.ocr_mock or _state["ocr"] is not None,
                "error": _state["ocr_error"]},
        "voice": {"mock": settings.voice_mock, "ready": settings.voice_mock or _state["voice_ready"],
                  "whisper_model": None if settings.voice_mock else settings.whisper_model,
                  "error": _state["voice_error"]},
        "intent": {"ready": True, "meaning_model": _meaning_status()},
        "fallbacks": {"local_ocr": settings.local_ocr_fallback},
    }


# --------------------------------------------------------------------------- OCR
@lru_cache(maxsize=None)
def _fixture(doc_type: str, scenario: str) -> dict:
    return json.loads((FIXTURES / doc_type / f"{scenario}.json").read_text(encoding="utf-8"))


def _mock_scenario(filename: str) -> str:
    name = (filename or "").lower()
    for word, scenario in (("retake", "retake"), ("blur", "retake"), ("review", "review"), ("flag", "flagged")):
        if word in name:
            return scenario
    return "clean"


def read_document(doc_type: str, data: bytes, filename: str = "photo.jpg",
                  content_type: str | None = None, request_id: str | None = None) -> dict:
    """doc_type: 'cnic' (front of the card) | 'death_certificate'."""
    rid = request_id or new_request_id(doc_type)
    if settings.ocr_mock:
        body = json.loads(json.dumps(_fixture(doc_type, _mock_scenario(filename))))
        if "detail" in body:
            return {"status": RETAKE, "detail": body["detail"], "request_id": rid}
        return {"status": OK, "result": {**body, "request_id": rid}, "request_id": rid}

    engine = _state["ocr"]
    if engine is None:
        why = _state["ocr_error"] or "the OCR engine is still starting"
        return {"status": UNAVAILABLE, "error": why, "request_id": rid}
    if not _ocr_lock.acquire(timeout=settings.ocr_timeout_s):
        return {"status": UNAVAILABLE, "error": "the OCR engine is busy", "request_id": rid}
    try:
        from ocr_core import BadImage, read_document as ocr_read
        try:
            result = ocr_read(engine, doc_type, data)
        except BadImage as e:
            return {"status": RETAKE, "detail": retake_message(e.reason, e.detail), "request_id": rid}
        except Exception as e:  # an engine bug must not break the claim
            log.exception("OCR failed request_id=%s", rid)
            return {"status": UNAVAILABLE, "error": f"OCR failed ({type(e).__name__})", "request_id": rid}
    finally:
        _ocr_lock.release()
    log.info("ocr request_id=%s doc=%s overall=%.2f flags=%s", rid, doc_type, result["overall_confidence"],
             ",".join(f["code"] for f in result["flags"]) or "-")
    return {"status": OK, "result": {"request_id": rid, "mock": False, **result}, "request_id": rid}


# --------------------------------------------------------------------------- voice
_AUDIO_MSGS = {"unreadable_audio": ("The recording could not be played. Please record again.",
                                    "ریکارڈنگ چل نہیں سکی۔ براہ کرم دوبارہ ریکارڈ کریں۔"),
               "too_long": ("Please ask one short question at a time.",
                            "براہ کرم ایک وقت میں ایک مختصر سوال پوچھیں۔")}


def understand_audio(data: bytes, filename: str = "question.webm", content_type: str | None = None,
                     request_id: str | None = None, mock_transcript: str | None = None) -> dict:
    """Recorded Urdu question -> transcript + intent (+ audio_quality: ok | silent | noisy).
    Mock mode 'hears' mock_transcript (or a fixed sentence); '<noise>' / '<silence>' simulate bad audio."""
    rid = request_id or new_request_id("voice")
    from urdu_intent import detect_intent
    if settings.voice_mock:
        said = mock_transcript or MOCK_SENTENCE
        quality = {"<noise>": "noisy", "<silence>": "silent"}.get(said, "ok")
        said = "" if quality != "ok" else said
        return {"status": OK, "result": {"transcript": said, "mock": True, "audio_quality": quality,
                                         **detect_intent(said)}, "request_id": rid}
    if not _state["voice_ready"]:
        if _state["voice_error"]:
            return {"status": UNAVAILABLE, "error": _state["voice_error"], "request_id": rid}
        if not settings.voice_preload:      # load on first use
            _load_voice()
            if not _state["voice_ready"]:
                return {"status": UNAVAILABLE, "error": _state["voice_error"] or "Whisper failed", "request_id": rid}
        else:
            return {"status": UNAVAILABLE, "error": "Whisper is still starting", "request_id": rid}
    import voice_core
    try:
        result = voice_core.understand_bytes(data)
    except voice_core.BadAudio as e:
        en, ur = _AUDIO_MSGS.get(e.reason, _AUDIO_MSGS["unreadable_audio"])
        return {"status": RECORD_AGAIN, "request_id": rid,
                "detail": {"code": "record_again", "reason": e.reason, "message_en": en, "message_ur": ur}}
    except Exception as e:
        log.exception("voice failed request_id=%s", rid)
        return {"status": UNAVAILABLE, "error": f"speech recognition failed ({type(e).__name__})", "request_id": rid}
    log.info("voice request_id=%s intent=%s conf=%.2f took=%ss", rid, result["intent"], result["confidence"],
             result.get("seconds_taken"))
    return {"status": OK, "result": result, "request_id": rid}


def intent_from_text(text: str, request_id: str | None = None) -> dict:
    """Typed (or browser-transcribed) Urdu question -> intent. Pure Python, always available."""
    from urdu_intent import detect_intent
    return {"status": OK, "result": {"transcript": text, **detect_intent(text)},
            "request_id": request_id or new_request_id("voice")}
