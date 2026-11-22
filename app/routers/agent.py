"""The assistant (voice-first conversation). A helper can talk for a family that allowed it: header X-Acting-For."""
from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as AnyUpload

from app import agent
from app.config import settings
from app.consent import acting_citizen
from app.db import get_db
from app.deps import require_role
from app.models import User

router = APIRouter(prefix="/agent", tags=["Assistant (citizen / helper)"])
CITIZEN = require_role("citizen", "helper")


class Start(BaseModel):
    restart: bool = False


@router.get("")
def resume(db: Session = Depends(get_db), user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    """The last thing the assistant said, so a dropped connection resumes at the same step (starts one if none)."""
    return agent.start(db, user, acting_citizen(db, user, x_acting_for))


@router.post("/start")
def start(body: Start | None = None, db: Session = Depends(get_db), user: User = Depends(CITIZEN),
          x_acting_for: int | None = Header(None)):
    return agent.start(db, user, acting_citizen(db, user, x_acting_for), restart=bool(body and body.restart))


@router.post("/reply")
def reply(text: str | None = Form(None), choice: str | None = Form(None), audio: UploadFile | None = File(None),
                photo: UploadFile | None = File(None), mock_transcript: str | None = Form(None),
          state: str | None = Form(None),
                db: Session = Depends(get_db), user: User = Depends(CITIZEN), x_acting_for: int | None = Header(None)):
    """One turn: her voice (audio), a tap (choice = a button id), a photo, or typed text."""
    citizen = acting_citizen(db, user, x_acting_for)
    data = name = None
    if isinstance(audio, AnyUpload) and audio.filename:
        data, name = audio.file.read(8 * 1024 * 1024), audio.filename
    pic = photo if isinstance(photo, AnyUpload) and photo.filename else None
    return agent.reply(db, user, citizen, text=(text or "").strip()[:500] or None, choice=choice, audio=data,
                       audio_name=name, photo=pic, mock_transcript=mock_transcript if settings.voice_mock else None, state=state)
