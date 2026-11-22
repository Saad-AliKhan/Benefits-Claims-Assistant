# -*- coding: utf-8 -*-
"""The assistant: a voice-first conversation that walks a widow through her claim and answers her questions.

One turn in -> one turn out. In: her voice (Whisper -> text -> intent), a tap on a big button, a photo, or
typed text. Out: what the assistant says (Urdu / English, spoken aloud by the screen), what it expects
next, and the buttons to show. The same engine will serve WhatsApp later: only the transport changes.

    lang -> need -> offer_apply -> consent -> id_photo -> id_confirm -> death_have -> (death_photo | lookup |
    death_cnic) -> decision explained -> menu (any question) -> end

When things go wrong (from the design):
  did not understand  "Sorry, please say it again"; after 2 tries the choices appear as icon buttons
  background noise    "The voice is not clear. Can you go somewhere quieter?" + the tap option
  signal drops        the screen says "connection weak, your work is saved"; the state is saved after every
                      turn and the conversation resumes at the same step
  low confidence      a bad photo: "please take it again"; still bad: "I am not sure. An officer will check
                      your case, you will get an SMS." (case notes attached)
The assistant never decides alone what the decision engine and the officers decide; it explains.
"""
import re

from fastapi import HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_engines, audit, claims, documents
from app.config import settings
from app.consent import CLAIM_PURPOSES, has_consent
from app.mock_services import api as mock
from app.models import AgentSession, Case, User

MAX_TRIES = 2

# ---------------------------------------------------------------- what the assistant says
# key -> (Urdu, English). {placeholders} are filled in. Feminine Urdu by default; *_m variants for men.
T = {
    "ask_lang": ("السلام علیکم۔ میں آسرا ہوں، آپ کی مدد کے لیے۔ آپ کس زبان میں بات کرنا چاہیں گی؟ اردو یا انگریزی؟",
                 "Assalam o Alaikum. I am Aasra, here to help you. Which language would you like to talk in, Urdu or English?"),
    "lang_ok": ("ٹھیک ہے، ہم اردو میں بات کریں گے۔", "Fine, we will talk in English."),
    "lang_unsupported": ("معاف کیجیے، یہ زبان ابھی دستیاب نہیں۔ ہم اردو میں بات کرتے ہیں۔",
                         "Sorry, that language is not available yet. Let us talk in Urdu."),
    "ask_need": ("آپ کو کس کام میں مدد چاہیے؟", "What do you need help with?"),
    "offer_apply": ("مجھے افسوس ہے۔ میں آپ کی مدد کروں گی۔ کیا آپ ریلیف پیمنٹ کے لیے درخواست دینا چاہتی ہیں؟",
                    "I am sorry for your loss. I will help you. Do you want to apply for the relief payment?"),
    "ask_consent": ("میں آپ کا نام اور شناختی کارڈ دیکھوں گی، اور وفات کا ریکارڈ، صرف اس کام کے لیے۔ منظوری ہوئی تو رقم آپ "
                    "کے بینک اکاؤنٹ میں بھیجوں گی، اور ضرورت ہوئی تو ایک افسر آپ کا کیس دیکھے گا۔ آپ کبھی بھی منع کر سکتی ہیں۔ "
                    "کیا ٹھیک ہے؟",
                    "I will look at your name and identity card, and the death record, only for this. If approved I will "
                    "send the money to your bank account, and if needed an officer will look at your case. You can say no "
                    "at any time. Is that all right?"),
    "consent_no": ("کوئی بات نہیں۔ آپ کی اجازت کے بغیر میں کچھ نہیں دیکھوں گی۔",
                   "No problem. I will not look at anything without your permission."),
    "ask_id_photo": ("اپنے شناختی کارڈ کے سامنے والے رخ کی تصویر لیں۔ کارڈ نشان کے اندر رکھیں۔",
                     "Take a photo of the front of your identity card. Keep the card inside the frame."),
    "retake": ("تصویر صاف نہیں آئی۔ {why} براہ کرم دوبارہ لیں۔", "The photo is not clear. {why} Please take it again."),
    "not_sure": ("میں یقین سے نہیں کہہ سکتی۔ ایک افسر آپ کا کیس دیکھے گا، آپ کو SMS آئے گا۔",
                 "I am not sure. An officer will check your case, you will get an SMS."),
    "confirm_name": ("آپ کا نام {name} ہے، صحیح ہے؟", "Your name is {name}, is that right?"),
    "name_disputed": ("ٹھیک ہے، ایک افسر آپ کا نام درست کرے گا۔ ہم آگے چلتے ہیں۔",
                      "All right, an officer will correct your name. Let us continue."),
    "ask_cnic": ("اپنا شناختی کارڈ نمبر بولیں یا لکھیں۔", "Say or type your CNIC number."),
    "ask_cert": ("آپ کے {spouse} کا وفات کا سرٹیفکیٹ چاہیے۔ کیا آپ کے پاس ہے؟",
                 "We need your {spouse_en}'s death certificate. Do you have it?"),
    "ask_cert_photo": ("سرٹیفکیٹ کے پورے صفحے کی تصویر لیں، چاروں کونے نظر آئیں۔",
                       "Take a photo of the whole certificate page, with all four corners showing."),
    "checking": ("کوئی بات نہیں۔ میں چیک کرتی ہوں، شاید ریکارڈ میں مل جائے۔",
                 "No problem. Let me check, it may be in the records."),
    "found": ("مل گیا: {name}، وفات {date}۔ آپ کو کچھ کرنے کی ضرورت نہیں۔",
              "Found it: {name}, died {date}. You do not need to do anything."),
    "not_found": ("ریکارڈ میں نہیں ملا۔ اپنے {spouse} کا شناختی کارڈ نمبر بولیں یا لکھیں، یا 'مددگار' کہیں تو کوئی آپ کے گھر "
                  "آ کر مدد کرے گی۔",
                  "It is not in the records. Say or type your {spouse_en}'s CNIC number, or say 'helper' and someone "
                  "will visit you to help."),
    "eligible": ("آپ ریلیف پیمنٹ کے لیے اہل ہیں۔ رقم {amount} روپے ہے۔ وجہ: {why}۔",
                 "You are eligible for the relief payment. The amount is PKR {amount}. Why: {why_en}."),
    "paid": ("پیسے {days} دن میں آپ کے اکاؤنٹ میں آ جائیں گے۔ میں SMS بھی بھیج رہی ہوں۔",
             "The money will reach your account within {days} days. I am also sending you an SMS."),
    "pay_problem": ("لیکن رقم آپ کے اکاؤنٹ میں نہیں بھیجی جا سکی۔ ایک افسر آپ سے رابطہ کرے گا، آپ کو SMS آئے گا۔",
                    "But the money could not be sent to your account. An officer will contact you; you will get an SMS."),
    "need_more": ("{reason}", "{reason_en}"),
    "anything_else": ("اور کچھ پوچھنا ہے؟", "Anything else you would like to ask?"),
    "say_again": ("معاف کیجیے، دوبارہ بولیں۔", "Sorry, please say it again."),
    "tap_instead": ("نیچے بٹن دبائیں۔", "Please tap one of the buttons below."),
    "noise": ("آواز صاف نہیں آ رہی۔ کیا آپ کسی خاموش جگہ جا سکتی ہیں؟ یا نیچے بٹن دبائیں۔",
              "The voice is not clear. Can you go somewhere quieter? Or tap a button below."),
    "did_you_mean": ("کیا آپ کا مطلب ہے؟", "Did you mean:"),
    "resumed": ("آپ کا کام محفوظ ہے۔ ہم وہیں سے شروع کرتے ہیں۔", "Your work is saved. Let us continue where we stopped."),
    "goodbye": ("شکریہ۔ اللہ حافظ۔ جب چاہیں دوبارہ پوچھیں۔", "Thank you. Goodbye. Ask again any time."),
    "ok_ask": ("جی، پوچھیے۔", "Yes, please ask."),
    "no_claim": ("ابھی آپ کی کوئی درخواست نہیں۔", "You have no claim yet."),
}
ANSWERS = {  # fixed guidance (MOCK programme details: check them before any real use)
    "required_documents": ("آپ کا شناختی کارڈ، اور آپ کے شوہر کا شناختی کارڈ نمبر یا وفات کا سرٹیفکیٹ۔ اگر وفات ریکارڈ میں ہو تو "
                           "سرٹیفکیٹ کی ضرورت نہیں۔",
                           "Your CNIC, and your husband's CNIC number or death certificate. If the death is in the records, "
                           "no certificate is needed."),
    "eligibility": ("وفات پانے والے کی بیوی یا شوہر یہ مدد لے سکتے ہیں، اگر گھر کی آمدنی {limit} روپے ماہانہ سے کم ہو۔",
                    "The wife or husband of a person who died can get this, if the household income is below PKR {limit} "
                    "a month."),
    "how_to_collect": ("رقم سیدھی آپ کے اپنے نام کے بینک اکاؤنٹ میں آتی ہے۔ کسی ایجنٹ کو کبھی پیسے نہ دیں۔",
                       "The money goes straight into a bank account in your own name. Never give money to any agent."),
    "cnic_problem": ("اپنے قریبی نادرا دفتر جا کر کارڈ دوبارہ بنوائیں۔ آپ کی درخواست محفوظ رہے گی۔",
                     "Go to your nearest NADRA office to get the card renewed. Your claim stays saved."),
    "no_death_certificate": ("کوئی بات نہیں۔ اکثر وفات ریکارڈ میں مل جاتی ہے، میں چیک کر سکتی ہوں۔ نہ ملے تو یونین کونسل میں وفات "
                             "درج کروائیں؛ مددگار آپ کی مدد کر سکتی ہے۔",
                             "No problem. The death is often in the records; I can check. If not, register it at the union "
                             "council; a helper can help you."),
    "other_programmes": ("بی آئی ایس پی کفالت جیسے اور پروگرام بھی ہیں۔ ایک افسر آپ کو بتا سکتا ہے۔ (یہ معلومات فرضی ہیں)",
                         "There are other programmes, such as BISP Kafaalat. An officer can tell you more. (mock information)"),
    "office_info": ("ضلعی سماجی بہبود دفتر، پیر سے جمعہ، صبح 9 سے شام 4 بجے۔ (فرضی پتہ)",
                    "District social welfare office, Monday to Friday, 9 am to 4 pm. (mock address)"),
    "consent_privacy": ("آپ کی معلومات صرف اس درخواست کے لیے ہیں۔ 'میری اجازتیں' میں آپ دیکھ اور روک سکتی ہیں۔",
                        "Your information is used only for this claim. In 'My permissions' you can see and stop it."),
    "report_fraud": ("یہ امداد مفت ہے۔ کسی کو پیسے، پن یا او ٹی پی کبھی نہ دیں۔ میں نے افسر کو بتا دیا ہے۔",
                     "This help is free. Never give anyone money, a PIN or an OTP. I have told an officer."),
    "urgent_help": ("میں نے آپ کی بات فوری طور پر افسر کو بھیج دی ہے۔ ہنگامی صورت میں 15 یا 1122 پر کال کریں۔",
                    "I sent your message to an officer urgently. In an emergency call 15 or 1122."),
    "handoff": ("ٹھیک ہے۔ ایک افسر آپ کو فون کرے گا، آپ کو SMS آئے گا۔", "All right. An officer will call you; you will get an SMS."),
    "helper_visit": ("ٹھیک ہے۔ ایک مددگار آپ سے ملنے آئے گی، آپ کو SMS آئے گا۔", "All right. A helper will visit you; you will get an SMS."),
    "greeting": ("وعلیکم السلام۔", "Wa alaikum assalam."),
    "send_document": ("ٹھیک ہے، تصویر بھیجیں۔", "All right, send the photo."),
}
BUTTONS = {
    "yes_no": [("yes", "✓", "ہاں", "Yes"), ("no", "✗", "نہیں", "No")],
    "lang": [("ur", "🗣️", "اردو", "Urdu"), ("en", "🗣️", "انگریزی", "English")],
    "need": [("how_to_apply", "📝", "درخواست دینی ہے", "Apply"), ("application_status", "📋", "میری درخواست", "My claim"),
             ("payment_status", "💰", "پیسے", "Money"), ("talk_to_officer", "👤", "افسر سے بات", "An officer")],
    "id_photo": [("no_photo", "🚫", "تصویر نہیں لے سکتی", "I cannot take a photo")],
    "death_cnic": [("helper_visit", "🏠", "مددگار بھیجیں", "Send a helper")],
}

YES = {"ہاں", "ہاں جی", "جی", "جی ہاں", "ٹھیک ہے", "ٹھیک", "صحیح", "صحیح ہے", "درست", "بالکل", "اوکے", "ہے", "haan", "han",
       "haan ji", "ji", "jee", "ji haan", "theek hai", "thik hai", "theek", "sahi", "sahi hai", "bilkul", "ok", "okay", "yes",
       "g", "hn", "hanji"}
NO = {"نہیں", "نا", "نہ", "جی نہیں", "نہیں جی", "غلط", "nahi", "nahin", "nai", "na", "no", "nhi", "ji nahi", "ghalat", "galat"}
LANGS = {"ur": ("اردو", "urdu", "urdoo", "ordu"), "en": ("انگریزی", "انگلش", "english", "angrezi", "inglish")}
OTHER_LANGS = ("سندھی", "پنجابی", "پشتو", "سرائیکی", "بلوچی", "sindhi", "punjabi", "pashto", "saraiki", "balochi")
# English mode: the intent engine is trained on Urdu and Roman Urdu, so English gets a small keyword list.
EN_KEYWORDS = [
    ("urgent_help", ("urgent", "emergency", "danger", "no food", "hospital")),
    ("report_fraud", ("fraud", "scam", "bribe", "asked me for money", "agent")),
    ("talk_to_officer", ("officer", "person", "human", "call me")),
    ("payment_not_received", ("not received", "didn't get", "did not get", "not arrived")),
    ("payment_amount", ("how much", "amount")),
    ("payment_status", ("money", "payment", "paid")),
    ("why_decision", ("why",)),
    ("what_is_missing", ("missing", "what else")),
    ("how_long", ("how long", "when")),
    ("required_documents", ("document", "papers")),
    ("withdraw_claim", ("withdraw", "cancel")),
    ("appeal", ("appeal", "review")),
    ("complaint", ("complain",)),
    ("helper_visit", ("visit", "helper", "come home")),
    ("application_status", ("status", "my claim", "my application")),
    ("eligibility", ("eligible", "can i get")),
    ("how_to_apply", ("apply", "died", "passed away", "widow", "death", "help")),
    ("thanks_goodbye", ("thank", "bye")),
    ("repeat", ("again", "repeat")),
]

HANDOFF_INTENTS = {"talk_to_officer": "handoff", "complaint": "complaint", "appeal": "appeal",
                   "payment_not_received": "payment_problem", "wrong_details": "correction",
                   "household_change": "household", "helper_visit": "helper_visit", "report_fraud": "fraud_report",
                   "urgent_help": "urgent"}


def _norm(t: str | None) -> str:
    return re.sub(r"[؟?!۔.,،]", " ", (t or "").strip().lower()).strip()


NEG_WORDS = {"نہیں", "غلط", "nahi", "nahin", "nhi", "nai", "no", "ghalat", "galat", "mat"}


def yes_no(text: str | None) -> bool | None:
    """'ہاں جی' / 'جی' / 'ٹھیک ہے' -> True; 'نہیں' (also 'نہی', 'نئیں': noon ghunna dropped by speech
    recognition), 'جی نہیں', 'نا جی' -> False; anything else -> None (ask again). A 'no' word anywhere wins."""
    from urdu_intent.normalize import normalize
    t = normalize(_norm(text))
    if not t:
        return None
    words = t.split()
    if t in NO or any(w in NEG_WORDS for w in words) or words[0] in ("نا", "نہ", "na", "naa"):
        return False
    if t in YES or (len(words) <= 4 and any(w in YES for w in words)):
        return True
    return None


def language(text: str | None) -> str | None:
    t = _norm(text)
    for code, names in LANGS.items():
        if any(n in t for n in names):
            return code
    if any(n in t for n in OTHER_LANGS):
        return "other"
    return None


def digits_cnic(text: str | None) -> str | None:
    d = re.sub(r"\D", "", (text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    return mock.norm_cnic(d) if len(d) == 13 else None


# ---------------------------------------------------------------- the engine
class Agent:
    def __init__(self, db: Session, session: AgentSession, user: User, citizen: User):
        self.db, self.s, self.user, self.citizen = db, session, user, citizen
        self.lines: list[tuple[str, str]] = []  # (ur, en) said this turn
        self.expect, self.buttons, self.photo_hint, self.slow, self.heard = "speech", [], None, False, None
        self.from_voice = False
        rec = mock.identity(citizen.cnic) if citizen.cnic else None
        self.male = bool(rec and rec.get("gender") == "M")

    # ---- output helpers
    def say(self, key: str, **v):
        ur, en = ANSWERS.get(key) or T[key]
        ur, en = ur.format(**v), en.format(**v)
        if self.male:  # the few feminine forms, for widowers
            ur = (ur.replace("چاہیں گی", "چاہیں گے").replace("چاہتی ہیں", "چاہتے ہیں").replace("سکتی ہیں", "سکتے ہیں")
                    .replace("آپ کے شوہر", "آپ کی اہلیہ").replace("آپ سے ملنے آئے گی", "آپ سے ملنے آئے گا"))
        self.lines.append((ur, en))

    def say_text(self, ur: str, en: str):
        self.lines.append((ur, en))

    def ask(self, key: str, state: str, expect: str = "speech", buttons: str | None = None, **v):
        self.say(key, **v)
        self.s.state, self.expect = state, expect
        self.buttons = list(BUTTONS.get(buttons, [])) if buttons else []

    @property
    def data(self) -> dict:
        return self.s.data or {}

    def set(self, **kv):
        d = dict(self.s.data or {})
        d.update(kv)
        self.s.data = d

    def spouse(self) -> dict:
        return {"spouse": "اہلیہ" if self.male else "شوہر", "spouse_en": "wife" if self.male else "husband"}

    # ---- the claim this conversation is about
    def case(self) -> Case | None:
        cid = self.data.get("case_id")
        if cid:
            return self.db.get(Case, cid)
        c = self.db.scalar(select(Case).where(Case.citizen_id == self.citizen.id).order_by(Case.id.desc()).limit(1))
        if c:
            self.set(case_id=c.id)
        return c

    def ensure_case(self) -> Case:
        c = self.case()
        if c is None or c.status in ("withdrawn", "rejected"):
            c = claims.create(self.db, self.user, self.citizen)
            self.set(case_id=c.id)
        return c

    # ---- failure handling
    def not_understood(self, question_key: str, buttons: str | None, alternatives=None, **v):
        self.s.tries = (self.s.tries or 0) + 1
        if self.s.tries < MAX_TRIES:
            self.say("say_again")
            self.say(question_key, **v)
            self.buttons = list(BUTTONS.get(buttons, [])) if buttons else []
        else:
            self.say(question_key, **v)
            self.say("tap_instead")
            self.buttons = list(BUTTONS.get(buttons or "yes_no", []))
            if alternatives:  # "did you mean...?" with the two likeliest meanings
                from urdu_intent import intents
                spec = intents()
                self.buttons = [(a["intent"], "❓", spec[a["intent"]]["label_ur"], spec[a["intent"]]["label_en"])
                                for a in alternatives[:2] if a["intent"] in spec] + self.buttons
            self.expect = "tap"

    def progress(self):
        self.s.tries = 0

    # ---- one turn
    def turn(self, text: str | None = None, choice: str | None = None, photo: UploadFile | None = None,
             voice: dict | None = None) -> dict:
        if voice is not None:
            if voice.get("audio_quality") in ("noisy", "silent") and not voice.get("transcript"):
                self.say("noise" if voice.get("audio_quality") == "noisy" else "say_again")
                self.repeat_question(tap=True)
                return self.out()
            text = voice.get("transcript") or ""
            self.heard, self.from_voice = text, True
        elif text:
            self.heard = text
        try:
            getattr(self, "on_" + self.s.state)(text=text, choice=choice, photo=photo)
        except HTTPException as e:
            if e.status_code == 403:
                raise
            self.db.rollback()
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            self.lines = []
            self.say_text("یہ قدم ابھی نہیں ہو سکا۔ ایک افسر مدد کر سکتا ہے، 'افسر' کہیں۔",
                          f"This step could not be done now ({detail}). An officer can help: say 'officer'.")
            self.menu()
        return self.out()

    def repeat_question(self, tap: bool = False):
        last = (self.s.last_turn or {})
        self.lines.append(tuple(last.get("question") or T["ask_need"]))
        self.expect = "tap" if tap else last.get("expect", "speech")
        self.buttons = [tuple(b) for b in last.get("buttons_raw", [])] or list(BUTTONS["yes_no"] if last.get("expect") == "yes_no" else [])

    def intent_of(self, text: str | None, choice: str | None) -> dict:
        if choice:
            from urdu_intent import intents
            spec = intents().get(choice)
            return {"intent": choice, "action": spec["action"] if spec else None, "alternatives": []}
        from urdu_intent import detect_intent
        r = detect_intent(text or "")
        if r["intent"] == "unclear" and self.s.lang == "en" and text and re.search(r"[a-zA-Z]", text):
            t = _norm(text)
            for intent, words in EN_KEYWORDS:
                if any(w in t for w in words):
                    return {"intent": intent, "action": None, "alternatives": []}
        return r

    # ---- states
    def on_lang(self, text=None, choice=None, photo=None):
        lang = choice if choice in ("ur", "en") else language(text)
        if lang is None:
            return self.not_understood("ask_lang", "lang")
        self.progress()
        if lang == "other":
            self.s.lang = "ur"
            self.say("lang_unsupported")
        else:
            self.s.lang = lang
            self.say("lang_ok")
        self.ask("ask_need", "need")

    def on_need(self, text=None, choice=None, photo=None):
        r = self.intent_of(text, choice)
        if r["intent"] == "unclear":
            if yes_no(text) is False:
                return self.goodbye()
            return self.not_understood("ask_need", "need", r.get("alternatives"))
        self.progress()
        self.answer(r)

    def on_offer_apply(self, text=None, choice=None, photo=None):
        yn = True if choice == "yes" else False if choice == "no" else yes_no(text)
        if yn is None:
            return self.not_understood("offer_apply", "yes_no")
        self.progress()
        if not yn:
            return self.ask("ask_need", "need")
        self.ask("ask_consent", "consent", "yes_no", "yes_no")

    def on_consent(self, text=None, choice=None, photo=None):
        yn = True if choice == "yes" else False if choice == "no" else yes_no(text)
        if yn is None:
            return self.not_understood("ask_consent", "yes_no")
        self.progress()
        if not yn:
            self.say("consent_no")
            return self.menu()
        case = self.ensure_case()
        if case.step == "consent":
            claims.give_consent(self.db, case, self.user, self.citizen, list(CLAIM_PURPOSES))
            audit.record(self.db, "consent.method", actor=self.user, case_id=case.id,
                         details={"method": "tap" if choice else "voice" if self.from_voice else "text",
                                  "session": self.s.id, "purposes": list(CLAIM_PURPOSES),
                                  "said_by": "helper" if self.user.id != self.citizen.id else "citizen"})
            from app import sms
            sms.send(self.db, self.citizen, "received", case.id)
            self.db.commit()
        self.ask("ask_id_photo", "id_photo", "photo", "id_photo")
        self.photo_hint = "cnic"

    def on_id_photo(self, text=None, choice=None, photo=None):
        case = self.case()
        if photo is None:
            if choice == "no_photo" or yes_no(text) is False or "تصویر نہیں" in (text or ""):
                return self.identity_without_photo(case)
            self.photo_hint = "cnic"
            return self.not_understood("ask_id_photo", "id_photo")
        try:
            claims.identity_step(self.db, case, self.user, self.citizen, None, photo)
        except HTTPException as e:
            if e.status_code not in (413, 422):
                raise
            self.db.rollback()
            return self.bad_photo("id_photo", "ask_id_photo", {}, "cnic")
        self.db.refresh(case)
        doc = documents.latest(self.db, case.id, "cnic") or {}
        if doc.get("action") == "ask_more" or doc.get("retake"):
            return self.bad_photo("id_photo", "ask_id_photo", doc, "cnic")
        self.progress()
        name = ((doc.get("ocr") or {}).get("fields") or {}).get("name") or self.registry_name(case)
        self.set(confirm_name=name)
        self.ask("confirm_name", "id_confirm", "yes_no", "yes_no", name=name)

    def identity_without_photo(self, case: Case):
        if not self.citizen.cnic:
            return self.ask("ask_cnic", "id_cnic", "digits")
        claims.identity_step(self.db, case, self.user, self.citizen, None, None)
        self.db.refresh(case)
        name = self.registry_name(case) or self.citizen.full_name
        self.set(confirm_name=name)
        self.ask("confirm_name", "id_confirm", "yes_no", "yes_no", name=name)

    def on_id_cnic(self, text=None, choice=None, photo=None):
        cnic = digits_cnic(text)
        if cnic is None:
            return self.not_understood("ask_cnic", None)
        self.progress()
        case = self.case()
        claims.identity_step(self.db, case, self.user, self.citizen, cnic, None)
        self.db.refresh(case)
        name = self.registry_name(case) or self.citizen.full_name
        self.set(confirm_name=name)
        self.ask("confirm_name", "id_confirm", "yes_no", "yes_no", name=name)

    def registry_name(self, case: Case) -> str | None:
        return ((((case.data or {}).get("identity") or {}).get("result") or {}).get("registry") or {}).get("full_name")

    def bad_photo(self, state: str, question: str, doc: dict, hint: str):
        n = self.data.get("retakes_" + hint, 0) + 1
        self.set(**{"retakes_" + hint: n})
        if n < 2:
            why = ((doc.get("retake") or {}).get("message_ur") or "روشنی میں، سیدھا رکھ کر، قریب سے تصویر لیں۔",
                   (doc.get("retake") or {}).get("message_en") or "Use good light, hold it flat, and come closer.")
            self.say_text(T["retake"][0].format(why=why[0]), T["retake"][1].format(why=why[1]))
            self.ask(question, state, "photo", "id_photo" if hint == "cnic" else None, **self.spouse())
            self.photo_hint = hint
            return
        claims.citizen_handoff(self.db, self.case(), self.user, "photo_unreadable")
        self.say("not_sure")
        self.menu()

    def on_id_confirm(self, text=None, choice=None, photo=None):
        yn = True if choice == "yes" else False if choice == "no" else yes_no(text)
        if yn is None:
            return self.not_understood("confirm_name", "yes_no", name=self.data.get("confirm_name", ""))
        self.progress()
        case = self.case()
        if not yn:
            d = dict(case.data or {})
            ident = dict(d.get("identity") or {})
            res = dict(ident.get("result") or {})
            res.update(action="human", code="id_human", confidence=min(res.get("confidence") or 0.5, 0.5),
                       detail=(res.get("detail") or "") + " The citizen said the name read is not hers.")
            ident["result"] = res
            d["identity"] = ident
            case.data = d
            claims._note(self.db, case, "The citizen said the name read from her CNIC is wrong.", self.user)
            self.db.commit()
            self.say("name_disputed")
        if (case.data or {}).get("eligibility") and case.step in ("decide", "proof"):
            return self.decide()
        self.ask("ask_cert", "death_have", "yes_no", "yes_no", **self.spouse())

    def on_death_have(self, text=None, choice=None, photo=None):
        if photo is not None:
            return self.on_death_photo(photo=photo)
        yn = True if choice == "yes" else False if choice == "no" else yes_no(text)
        if yn is None:
            return self.not_understood("ask_cert", "yes_no", **self.spouse())
        self.progress()
        if yn:
            self.ask("ask_cert_photo", "death_photo", "photo")
            self.photo_hint = "certificate"
            return
        self.say("checking")
        case = self.case()
        if not has_consent(self.db, self.citizen.id, "records_check"):
            raise HTTPException(403, "No permission to check the records")
        found = mock.deaths_for_applicant(self.citizen.cnic) if self.citizen.cnic else []
        if not found:
            return self.ask("not_found", "death_cnic", "digits", "death_cnic", **self.spouse())
        rec = found[0]
        self.say("found", name=rec["deceased_name"], date="-".join(reversed(rec["date_of_death"].split("-"))))
        claims.eligibility_step(self.db, case, self.user, self.citizen, rec["deceased_cnic"],
                                rec["applicant_relation"], None)
        self.decide()

    def on_death_photo(self, text=None, choice=None, photo=None):
        if photo is None:
            if yes_no(text) is False:
                return self.on_death_have(choice="no")
            self.photo_hint = "certificate"
            return self.not_understood("ask_cert_photo", None)
        case = self.case()
        try:
            claims.eligibility_step(self.db, case, self.user, self.citizen, None, self.default_relation(), photo)
        except HTTPException as e:
            if e.status_code != 422:
                raise
            self.db.rollback()
        doc = documents.latest(self.db, case.id, "death_certificate") or {}
        self.db.refresh(case)
        if doc.get("retake") or case.step != "decide":
            return self.bad_photo("death_photo", "ask_cert_photo", doc, "certificate")
        self.progress()
        self.decide()

    def default_relation(self) -> str:
        return "Husband" if self.male else "Wife"

    def on_death_cnic(self, text=None, choice=None, photo=None):
        r = self.intent_of(text, choice) if not digits_cnic(text) else {"intent": None}
        if choice == "helper_visit" or r.get("intent") == "helper_visit" or "مددگار" in (text or "") or "helper" in _norm(text):
            claims.citizen_handoff(self.db, self.case(), self.user, "helper_visit")
            self.say("helper_visit")
            return self.menu()
        cnic = digits_cnic(text)
        if cnic is None:
            return self.not_understood("not_found", "death_cnic", **self.spouse())
        self.progress()
        claims.eligibility_step(self.db, self.case(), self.user, self.citizen, cnic, self.default_relation(), None)
        self.decide()

    # ---- the decision, explained
    def decide(self):
        case = self.case()
        claims.decide(self.db, case, self.user, self.citizen, None, None)
        self.db.refresh(case)
        d = claims.latest_decision(self.db, case.id)
        if case.status in ("paid", "approved", "payment_failed") and d.outcome == "green":
            why_ur, why_en = self.reasons(case)
            self.say("eligible", amount=f"{case.amount:,}", why=why_ur, why_en=why_en)
            if case.status == "payment_failed":
                self.say("pay_problem")
            else:
                self.say("paid", days=settings.payment_settlement_days)
        elif d.outcome == "yellow" and self.data.get("proof_rounds", 0) >= 1:
            claims.citizen_handoff(self.db, case, self.user, "photo_unreadable")
            self.say("not_sure")
        elif d.outcome == "yellow":
            self.set(proof_rounds=self.data.get("proof_rounds", 0) + 1, retakes_certificate=0)
            self.say_text(d.trace.get("reason_user_ur", ""), d.reason_user)
            asks = d.trace.get("asks_for", [])
            if any(a.startswith(("record", "death")) for a in asks):
                self.ask("ask_cert_photo", "death_photo", "photo")
                self.photo_hint = "certificate"
            else:
                self.set(retakes_cnic=0)
                self.ask("ask_id_photo", "id_photo", "photo", "id_photo")
                self.photo_hint = "cnic"
            return
        else:
            self.say("not_sure")
        self.menu()

    def reasons(self, case: Case) -> tuple[str, str]:
        e = (((case.data or {}).get("eligibility") or {}).get("result") or {})
        ur, en = [], []
        rel = (((case.data or {}).get("eligibility") or {}).get("input") or {}).get("relation")
        if rel in ("Wife", "Widow"):
            ur.append("آپ بیوہ ہیں"); en.append("you are a widow")
        elif rel in ("Husband", "Widower"):
            ur.append("آپ کی اہلیہ وفات پا چکی ہیں"); en.append("your wife has died")
        if e.get("programme"):
            ur.append("آپ کی آمدنی کم ہے"); en.append("your income is low")
        if e.get("record_found"):
            ur.append("وفات کا ریکارڈ موجود ہے"); en.append("the death is in the records")
        return " اور ".join(ur[:2]) if len(ur) <= 2 else "، ".join(ur[:-1]) + " اور " + ur[-1], ", ".join(en)

    # ---- after the claim: any question
    def menu(self):
        self.ask("anything_else", "menu", "speech", "yes_no")

    def on_menu(self, text=None, choice=None, photo=None):
        if photo is not None:
            return self.on_id_photo(photo=photo)
        yn = True if choice == "yes" else False if choice == "no" else yes_no(text)
        r = self.intent_of(text, choice) if choice not in ("yes", "no") else {"intent": "unclear"}
        if r["intent"] == "unclear":
            if yn is False:
                return self.goodbye()
            if yn is True:
                self.progress()
                return self.ask("ok_ask", "menu", "speech")
            return self.not_understood("anything_else", "need", r.get("alternatives"))
        self.progress()
        self.answer(r)

    def goodbye(self):
        self.say("goodbye")
        self.s.state, self.s.ended, self.expect, self.buttons = "end", True, "none", []

    def on_end(self, text=None, choice=None, photo=None):
        self.s.ended = False
        self.ask("ask_need", "need")

    def answer(self, r: dict):
        """Answer one question from her own claim, or do what she asked (a person, a visit, a correction)."""
        intent = r["intent"]
        case = self.case()
        d = claims.latest_decision(self.db, case.id) if case else None
        if intent in ("how_to_apply",) or (intent == "eligibility" and not case):
            if case and case.status in ("draft", "waiting_citizen"):
                return self.resume_claim(case)
            if case and case.status in ("paid", "approved", "escalated", "assigned", "payment_failed"):
                self.say_text(*self.status_text(case, d))
                return self.menu()
            return self.ask("offer_apply", "offer_apply", "yes_no", "yes_no")
        if intent in HANDOFF_INTENTS:
            kind = HANDOFF_INTENTS[intent]
            if kind == "payment_problem" and not (case and case.status == "paid"):
                self.say_text(*self.status_text(case, d)) if case else self.say("no_claim")
                return self.menu()
            target = case or self.ensure_case()
            claims.citizen_handoff(self.db, target, self.user, kind)
            key = {"urgent": "urgent_help", "fraud_report": "report_fraud", "helper_visit": "helper_visit"}.get(kind, "handoff")
            self.say(key)
            return self.menu()
        if intent == "withdraw_claim":
            if not case or case.status not in ("draft", "waiting_citizen", "escalated", "assigned"):
                self.say("no_claim")
                return self.menu()
            return self.confirm_withdraw()
        if intent in ("application_status", "payment_status", "why_decision", "what_is_missing", "how_long",
                      "payment_amount"):
            if not case:
                if intent == "payment_amount":
                    self.say_text(f"رقم {settings.benefit_amount:,} روپے ہے، اور ہر بچے کے لیے 10,000 روپے زیادہ (زیادہ سے زیادہ پانچ)۔",
                                  f"The amount is PKR {settings.benefit_amount:,}, plus PKR 10,000 per child (up to five).")
                else:
                    self.say("no_claim")
                return self.menu()
            self.say_text(*self.status_text(case, d, intent))
            if intent == "what_is_missing" and case.status in ("draft", "waiting_citizen"):
                return self.resume_claim(case)
            return self.menu()
        if intent == "send_document":
            if case and case.status in ("draft", "waiting_citizen"):
                return self.resume_claim(case)
            self.say("send_document")
            return self.ask("ask_id_photo", "id_photo", "photo", "id_photo")
        if intent == "eligibility":
            from app import rules
            self.say("eligibility", limit=f"{rules.get_active(self.db).config['max_monthly_income']:,}")
            return self.menu()
        if intent in ("repeat", "speak_slowly"):
            last = self.s.last_turn or {}
            for ur, en in last.get("lines", []):
                self.say_text(ur, en)
            self.slow = intent == "speak_slowly"
            self.expect, self.buttons = last.get("expect", "speech"), [tuple(b) for b in last.get("buttons_raw", [])]
            self.s.state = last.get("state", self.s.state)
            return
        if intent == "thanks_goodbye":
            return self.goodbye()
        if intent in ANSWERS:
            self.say(intent)
            if intent == "no_death_certificate" and case and case.step == "eligibility":
                return self.ask("ask_cert", "death_have", "yes_no", "yes_no", **self.spouse())
            return self.menu()
        self.say("handoff")
        return self.menu()

    def confirm_withdraw(self):
        self.say_text("کیا آپ واقعی اپنی درخواست واپس لینا چاہتی ہیں؟", "Do you really want to withdraw your claim?")
        self.s.state, self.expect, self.buttons = "confirm_withdraw", "yes_no", list(BUTTONS["yes_no"])

    def on_confirm_withdraw(self, text=None, choice=None, photo=None):
        yn = True if choice == "yes" else False if choice == "no" else yes_no(text)
        if yn is None:
            return self.not_understood("anything_else", "yes_no")
        self.progress()
        if yn:
            claims.withdraw(self.db, self.case(), self.user)
            self.say_text("آپ کی درخواست واپس لے لی گئی۔", "Your claim has been withdrawn.")
        self.menu()

    def resume_claim(self, case: Case):
        """Continue the claim at the step where it stopped (signal drop, or she came back another day)."""
        step = case.step
        if step == "consent":
            return self.ask("ask_consent", "consent", "yes_no", "yes_no")
        if step == "identity":
            self.photo_hint = "cnic"
            return self.ask("ask_id_photo", "id_photo", "photo", "id_photo")
        if step == "eligibility":
            return self.ask("ask_cert", "death_have", "yes_no", "yes_no", **self.spouse())
        if step == "decide":
            return self.decide()
        if step == "proof":
            d = claims.latest_decision(self.db, case.id)
            asks = d.trace.get("asks_for", []) if d else []
            if any(a.startswith(("record", "death")) for a in asks):
                self.photo_hint = "certificate"
                return self.ask("ask_cert_photo", "death_photo", "photo")
            self.photo_hint = "cnic"
            return self.ask("ask_id_photo", "id_photo", "photo", "id_photo")
        return self.menu()

    def status_text(self, case: Case | None, d, intent: str = "application_status") -> tuple[str, str]:
        if case is None:
            return T["no_claim"]
        days = settings.payment_settlement_days
        s = case.status
        if intent == "payment_amount":
            return (f"آپ کی رقم {case.amount:,} روپے ہے۔", f"Your amount is PKR {case.amount:,}.")
        if intent == "why_decision" and s in ("paid", "approved", "payment_failed"):
            ur, en = self.reasons(case)
            return (f"آپ کی درخواست منظور ہوئی۔ وجہ: {ur}۔", f"Your claim was approved. Why: {en}.")
        if s == "paid":
            return (f"{case.amount:,} روپے آپ کے اکاؤنٹ میں بھیج دیے گئے ہیں، {days} دن میں پہنچ جائیں گے۔ حوالہ {case.payment_ref}۔",
                    f"PKR {case.amount:,} has been sent to your account and will arrive within {days} days. Ref {case.payment_ref}.")
        if s == "payment_failed":
            return T["pay_problem"][0].replace("لیکن ", ""), T["pay_problem"][1].replace("But the", "The")
        if s in ("escalated", "assigned"):
            if intent == "how_long":
                return ("ایک افسر عام طور پر 3 کام کے دنوں میں کیس دیکھ لیتا ہے۔ (فرضی وقت)",
                        "An officer usually checks a case within 3 working days. (mock time)")
            reason = (d.trace.get("reason_user_ur", ""), d.reason_user) if d else ("", "")
            return (f"ایک افسر آپ کا کیس دیکھ رہا ہے۔ {reason[0]}", f"An officer is checking your case. {reason[1]}")
        if s == "waiting_citizen" and d:
            return (d.trace.get("reason_user_ur", ""), d.reason_user)
        if s == "rejected":
            return (f"آپ کی درخواست منظور نہیں ہوئی۔ {case.resolution_note or ''} اپیل کے لیے 'اپیل' کہیں۔",
                    f"Your claim was not approved. {case.resolution_note or ''} Say 'appeal' to ask for a review.")
        if s == "draft":
            return ("آپ کی درخواست ابھی مکمل نہیں۔ ہم وہیں سے شروع کر سکتے ہیں۔",
                    "Your claim is not finished yet. We can continue where you stopped.")
        return (f"آپ کی درخواست: {s}", f"Your claim: {s}")

    # ---- output
    def out(self) -> dict:
        lang = self.s.lang or "ur"
        question = self.lines[-1] if self.lines else ("", "")
        buttons = [{"id": b[0], "icon": b[1], "label": b[2] if lang == "ur" else b[3]} for b in self.buttons]
        case = self.case()
        turn = {
            "session_id": self.s.id, "state": self.s.state, "lang": lang, "expect": self.expect,
            "say": " ".join(ur if lang == "ur" else en for ur, en in self.lines),
            "say_ur": " ".join(ur for ur, _ in self.lines), "say_en": " ".join(en for _, en in self.lines),
            "buttons": buttons, "photo_hint": self.photo_hint, "slow": self.slow, "heard": self.heard,
            "ended": bool(self.s.ended), "claim": claims.citizen_view(self.db, case) if case else None,
        }
        turn = jsonable_encoder(turn)
        self.s.last_turn = {"lines": [list(x) for x in self.lines], "question": list(question), "expect": self.expect,
                            "buttons_raw": [list(b) for b in self.buttons], "state": self.s.state, "turn": turn}
        self.db.commit()
        return turn


# ---------------------------------------------------------------- sessions
def current(db: Session, user: User, citizen: User) -> AgentSession | None:
    return db.scalar(select(AgentSession).where(AgentSession.user_id == user.id, AgentSession.citizen_id == citizen.id,
                                                AgentSession.ended.is_(False)).order_by(AgentSession.id.desc()).limit(1))


def start(db: Session, user: User, citizen: User, restart: bool = False, channel: str = "web") -> dict:
    s = current(db, user, citizen)
    if s is not None and not restart and s.last_turn:
        t = dict(s.last_turn["turn"])
        t["resumed"] = True
        lang = t.get("lang", "ur")
        t["say"] = (T["resumed"][0] if lang == "ur" else T["resumed"][1]) + " " + t["say"]
        return t
    if s is not None:
        s.ended = True
    s = AgentSession(user_id=user.id, citizen_id=citizen.id, channel=channel, state="lang", tries=0, data={},
                     last_turn={}, ended=False)
    db.add(s)
    db.flush()
    audit.record(db, "agent.session_started", actor=user, details={"session": s.id, "channel": channel,
                                                                    "citizen_id": citizen.id})
    a = Agent(db, s, user, citizen)
    a.ask("ask_lang", "lang", "speech", "lang")
    return a.out()


def reply(db: Session, user: User, citizen: User, text: str | None = None, choice: str | None = None,
          audio: bytes | None = None, audio_name: str | None = None, photo: UploadFile | None = None,
          mock_transcript: str | None = None, state: str | None = None) -> dict:
    s = current(db, user, citizen)
    if s is None:
        return start(db, user, citizen)
    if state and s.state != state and s.last_turn:
        # The phone sent this answer before, but the reply was lost (weak signal) and it sent it again:
        # do not apply it twice, show where we are.
        t = dict(s.last_turn["turn"])
        t["resumed"] = True
        return t
    voice = None
    if audio:
        call = ai_engines.understand_audio(audio, audio_name or "q.webm", None, mock_transcript=mock_transcript)
        if call["status"] == ai_engines.RECORD_AGAIN:
            voice = {"audio_quality": "silent", "transcript": ""}
        elif call["status"] != ai_engines.OK:
            raise HTTPException(503, {"code": "voice_unavailable",
                                      "message_ur": "آواز ابھی دستیاب نہیں۔ براہ کرم بٹن دبائیں یا لکھیں۔",
                                      "message_en": "Voice is not available right now. Please tap or type."})
        else:
            voice = call["result"]
    a = Agent(db, s, user, citizen)
    t = a.turn(text=text, choice=choice, photo=photo, voice=voice)
    audit.record(db, "agent.turn", actor=user, case_id=a.data.get("case_id"),
                 details={"session": s.id, "state": s.state, "input": "voice" if audio else "photo" if photo else
                          "tap" if choice else "text", "quality": (voice or {}).get("audio_quality"),
                          "intent": None}, commit=True)  # what she said is not stored
    return t
