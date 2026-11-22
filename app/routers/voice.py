"""Voice: Urdu speech in (Whisper, inside this app) and out (/tts).

The answer is only WHAT the person asks (intent + action); the screen then does the action with the
logged-in person's own data. Audio and transcripts are never stored or logged."""
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import ai_engines, audit
from app.db import get_db
from app.deps import require_role
from app.models import User

router = APIRouter(tags=["Voice"])
CACHE = Path(__file__).resolve().parents[2] / "tts_cache"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
VOICE_DOWN = {"code": "voice_unavailable",
              "message_en": "Voice is not available right now. Please type your question.",
              "message_ur": "آواز ابھی دستیاب نہیں۔ براہ کرم اپنا سوال لکھیں۔"}
CITIZEN = require_role("citizen", "helper")


@router.get("/tts")
def tts(text: str = Query(min_length=1, max_length=600), lang: str = Query("ur", pattern="^(ur|en)$"),
        user: User = Depends(require_role("citizen", "helper", "officer", "admin", "auditor"))):
    """Speech out (gTTS; needs internet). Cached, so a sentence is fetched once. The page falls back to the
    browser's own voice when this fails."""
    try:
        from gtts import gTTS
    except ImportError:
        raise HTTPException(503, "gTTS is not installed")
    CACHE.mkdir(exist_ok=True)
    f = CACHE / (hashlib.sha1(f"{lang}:{text}".encode("utf-8")).hexdigest() + ".mp3")
    if not f.exists():
        try:
            gTTS(text=text, lang=lang).save(str(f))
        except Exception:
            f.unlink(missing_ok=True)
            raise HTTPException(503, "Speech service unavailable")
    return FileResponse(f, media_type="audio/mpeg")


def _answer(db: Session, user: User, res: dict, source: str, mode: str, rid: str | None) -> dict:
    audit.record(db, "ai.voice_intent", actor=user,
                 details={"intent": res.get("intent"), "confidence": res.get("confidence"), "action": res.get("action"),
                          "reason": res.get("reason"), "source": source, "mode": mode, "request_id": rid},
                 commit=True)  # what was said is not stored
    return {"intent": res.get("intent"), "action": res.get("action"), "label_ur": res.get("label_ur"),
            "label_en": res.get("label_en"), "confidence": res.get("confidence"), "reason": res.get("reason"),
            "needs_backend": res.get("needs_backend"),
            "text": res.get("text_corrected") or res.get("transcript"),  # shown back to the person; never stored
            "source": source}


@router.post("/voice/understand")
def voice_understand(audio: UploadFile = File(..., description="webm/opus, ogg, m4a, mp3 or wav, up to 30 s"),
                     lang: str = Form("ur", pattern="^(ur|en)$"), db: Session = Depends(get_db), user: User = Depends(CITIZEN)):
    """Recorded question (Urdu, or English with lang=en) -> Whisper -> intent. 422 = record again; 503 = voice not ready: type instead."""
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too large")
    if not data:
        raise HTTPException(422, {"code": "record_again", "reason": "empty", "message_en": "Nothing was recorded. Please try again.",
                                  "message_ur": "کچھ ریکارڈ نہیں ہوا۔ دوبارہ کوشش کریں۔"})
    call = ai_engines.understand_audio(data, audio.filename or "question.webm", audio.content_type, language=lang)
    if call["status"] == ai_engines.OK and lang == "en":
        from app.agent import english_intent
        call["result"].update(english_intent(call["result"].get("transcript") or ""))
    if call["status"] == ai_engines.RECORD_AGAIN:
        raise HTTPException(422, {"code": "record_again", **call["detail"]})
    if call["status"] != ai_engines.OK:
        raise HTTPException(503, VOICE_DOWN)
    return _answer(db, user, call["result"], "whisper", "audio", call["request_id"])


class VoiceTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


@router.post("/voice/intent")
def voice_intent(body: VoiceTextIn, db: Session = Depends(get_db), user: User = Depends(CITIZEN)):
    """Typed question (or speech the browser turned into text) -> intent."""
    call = ai_engines.intent_from_text(body.text)
    return _answer(db, user, call["result"], "intent_detector", "text", call["request_id"])
