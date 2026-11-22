"""Voice recordings for TESTING the speech recognition (volunteers, with their permission).

A volunteer sees a situation ("You want to know when your money will come") and asks it in her OWN words,
the way she would ask a person. Recordings are saved on this machine only (data/recordings/, git-ignored)
with the situation they answer, so tools/voice/compare_asr.py can measure which Whisper model understands
real Pakistani Urdu best. Nothing here is used to decide any claim."""
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import audit
from app.db import get_db
from app.deps import require_role
from app.models import User

router = APIRouter(prefix="/voice/collect", tags=["Voice recordings (testing)"])
ANY = require_role("citizen", "helper", "officer", "admin", "auditor")
DIR = Path(__file__).resolve().parents[2] / "data" / "recordings"
MAX_BYTES = 5 * 1024 * 1024

# situation -> (Urdu, English). The volunteer is NOT given a sentence to read: only what she wants.
SITUATIONS = {
    "application_status": ("آپ جاننا چاہتی ہیں کہ آپ کی درخواست کا کیا بنا۔", "You want to know what happened to your application."),
    "required_documents": ("آپ پوچھنا چاہتی ہیں کہ کون سے کاغذات لانے ہیں۔", "You want to ask which papers you need."),
    "eligibility": ("آپ پوچھنا چاہتی ہیں کہ کیا آپ یہ امداد لے سکتی ہیں۔", "You want to ask whether you can get this help."),
    "talk_to_officer": ("آپ کسی افسر یا انسان سے بات کرنا چاہتی ہیں۔", "You want to talk to an officer / a real person."),
    "payment_status": ("آپ پوچھنا چاہتی ہیں کہ پیسے کب آئیں گے۔", "You want to ask when the money will come."),
    "how_to_apply": ("آپ کے شوہر فوت ہو گئے ہیں اور آپ مدد کے لیے درخواست دینا چاہتی ہیں۔", "Your husband died and you want to apply for help."),
    "consent_privacy": ("آپ پوچھنا چاہتی ہیں کہ آپ کی معلومات کون دیکھے گا۔", "You want to ask who will see your information."),
    "report_fraud": ("کسی نے فون کر کے آپ سے پیسے یا کوڈ مانگا، آپ بتانا چاہتی ہیں۔", "Someone called asking for money or a code; you want to report it."),
    "complaint": ("آپ کسی بات پر شکایت کرنا چاہتی ہیں۔", "You want to make a complaint."),
    "update_details": ("آپ کا فون نمبر یا بینک اکاؤنٹ بدل گیا ہے۔", "Your phone number or bank account changed."),
    "greeting": ("آپ سلام کرنا چاہتی ہیں۔", "You want to say hello."),
    "repeat": ("آپ کو بات سمجھ نہیں آئی، دوبارہ سننا چاہتی ہیں۔", "You did not understand and want to hear it again."),
    "payment_amount": ("آپ پوچھنا چاہتی ہیں کہ کتنے پیسے ملیں گے۔", "You want to ask how much money you will get."),
    "payment_not_received": ("آپ کو بتایا گیا تھا کہ پیسے بھیج دیے، مگر آپ کو نہیں ملے۔", "You were told the money was sent, but you did not get it."),
    "how_to_collect": ("آپ پوچھنا چاہتی ہیں کہ پیسے کہاں سے اور کیسے لیں۔", "You want to ask where and how to collect the money."),
    "why_decision": ("آپ جاننا چاہتی ہیں کہ فیصلہ ایسا کیوں ہوا۔", "You want to know why the decision was made."),
    "what_is_missing": ("آپ پوچھنا چاہتی ہیں کہ اور کیا چاہیے۔", "You want to ask what else is still needed."),
    "how_long": ("آپ پوچھنا چاہتی ہیں کہ کتنا وقت لگے گا۔", "You want to ask how long it will take."),
    "appeal": ("آپ فیصلے سے متفق نہیں، دوبارہ دیکھنے کا کہنا چاہتی ہیں۔", "You disagree with the decision and want it reviewed."),
    "withdraw_claim": ("آپ اپنی درخواست واپس لینا چاہتی ہیں۔", "You want to withdraw your application."),
    "send_document": ("آپ ایک کاغذ کی تصویر بھیجنا چاہتی ہیں۔", "You want to send a photo of a paper."),
    "cnic_problem": ("آپ کا شناختی کارڈ گم ہو گیا ہے یا اس کی میعاد ختم ہو گئی ہے۔", "Your ID card is lost or expired."),
    "no_death_certificate": ("آپ کے پاس وفات کا سرٹیفکیٹ نہیں ہے۔", "You do not have the death certificate."),
    "wrong_details": ("آپ کا نام یا کوئی معلومات غلط لکھی ہوئی ہے۔", "Your name or some details are written wrong."),
    "household_change": ("آپ کے گھر میں کوئی تبدیلی ہوئی ہے (بچہ، شادی، گھر بدلا)۔", "Something changed at home (a child, a marriage, a move)."),
    "other_programmes": ("آپ پوچھنا چاہتی ہیں کہ اور کون سی امداد مل سکتی ہے۔", "You want to ask what other help you can get."),
    "helper_visit": ("آپ چاہتی ہیں کہ کوئی گھر آ کر مدد کرے۔", "You want someone to come home to help you."),
    "office_info": ("آپ پوچھنا چاہتی ہیں کہ دفتر کہاں ہے اور کب کھلتا ہے۔", "You want to ask where the office is and when it opens."),
    "urgent_help": ("آپ مشکل میں ہیں اور فوری مدد چاہیے۔", "You are in trouble and need help urgently."),
    "thanks_goodbye": ("آپ شکریہ کہہ کر بات ختم کرنا چاہتی ہیں۔", "You want to say thank you and goodbye."),
    "speak_slowly": ("بات بہت تیز ہے، آپ آہستہ بولنے کا کہنا چاہتی ہیں۔", "It is too fast; you want it said slowly."),
    # short answers the assistant asks for
    "_yes": ("آپ سے پوچھا گیا 'کیا ٹھیک ہے؟' — آپ 'ہاں' کہنا چاہتی ہیں (اپنے انداز میں)۔", "You are asked 'Is that OK?' and want to say YES (your way)."),
    "_no": ("آپ سے پوچھا گیا 'کیا آپ کے پاس سرٹیفکیٹ ہے؟' — آپ 'نہیں' کہنا چاہتی ہیں۔", "You are asked 'Do you have the certificate?' and want to say NO."),
    "_lang": ("آپ سے پوچھا گیا کس زبان میں بات کریں گی — اردو بولیں۔", "You are asked which language — say Urdu."),
    "_cnic": ("کوئی بھی فرضی شناختی کارڈ نمبر بولیں، جیسے 35202-1234567-1 (اصلی نہیں)۔", "Say any MADE-UP CNIC number, e.g. 35202-1234567-1 (not a real one)."),
}


@router.get("/situations")
def situations(user: User = Depends(ANY)):
    return [{"id": k, "ur": v[0], "en": v[1]} for k, v in SITUATIONS.items()]


@router.post("")
def save(situation: str = Form(...), speaker: str = Form(...), consent: bool = Form(...),
         gender: str | None = Form(None), age: str | None = Form(None), place: str | None = Form(None),
         audio: UploadFile = File(...), db=Depends(get_db), user: User = Depends(ANY)):
    if not consent:
        raise HTTPException(422, "The volunteer must agree before her voice is recorded.")
    if situation not in SITUATIONS:
        raise HTTPException(422, "Unknown situation")
    code = re.sub(r"[^a-zA-Z0-9_-]", "", speaker)[:20]
    if not code:
        raise HTTPException(422, "Give a short speaker code (no names), e.g. v01")
    data = audio.file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(422, "Empty or too long recording")
    ext = (Path(audio.filename or "a.webm").suffix or ".webm")[:6]
    folder = DIR / code
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}_{situation.lstrip('_')}{ext}"
    (folder / name).write_bytes(data)
    row = {"file": f"{code}/{name}", "situation": situation, "speaker": code, "gender": gender, "age": age,
           "place": place, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": user.id}
    with open(DIR / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    audit.record(db, "voice.test_recording_saved", actor=user, details={"speaker": code, "situation": situation},
                 commit=True)
    n = sum(1 for _ in open(DIR / "index.jsonl", encoding="utf-8"))
    return {"saved": row["file"], "total": n}
