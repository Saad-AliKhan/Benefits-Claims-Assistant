"""The assistant: the 7-step conversation from the design, and each 'when things go wrong' row."""
import io

from PIL import Image
from sqlalchemy import select

from app.models import AgentSession, AuditLog, Case, SmsMessage
from tools import claim_runner


def jpg():
    b = io.BytesIO()
    Image.new("RGB", (900, 600), (235, 240, 230)).save(b, "JPEG")
    return b.getvalue()


class Talk:
    def __init__(self, env, sid="S01"):
        self.env = env
        self.u = claim_runner.claimant(env.db, env.scenario(sid))
        self.h = env.H(self.u)
        self.last = env.c.post("/agent/start", headers=self.h, json={"restart": True}).json()

    def say(self, text=None, choice=None, photo=None, voice=None):
        files, data = {}, {}
        if text is not None:
            data["text"] = text
        if choice is not None:
            data["choice"] = choice
        if voice is not None:
            files["audio"] = ("q.webm", b"\x1a\x45\xdf\xa3fake", "audio/webm")
            data["mock_transcript"] = voice
        if photo is not None:
            files["photo"] = (photo, jpg(), "image/jpeg")
        r = self.env.c.post("/agent/reply", headers=self.h, data=data, files=files or None)
        assert r.status_code == 200, r.text
        self.last = r.json()
        return self.last


def test_the_seven_steps_from_the_design(env):
    t = Talk(env)
    assert "کس زبان" in t.last["say"] and {b["id"] for b in t.last["buttons"]} == {"ur", "en"}       # 1
    t.say(voice="اردو")
    assert t.last["state"] == "need" and "کس کام میں مدد" in t.last["say"]
    t.say(voice="میرے شوہر فوت ہو گئے ہیں، مجھے مدد چاہیے")                                          # 2
    assert t.last["state"] == "offer_apply" and "افسوس" in t.last["say"]
    t.say(voice="جی ہاں")
    assert t.last["state"] == "consent" and "منع کر سکتی" in t.last["say"]                          # 3
    t.say(voice="ٹھیک ہے")
    assert t.last["state"] == "id_photo" and t.last["expect"] == "photo" and t.last["photo_hint"] == "cnic"
    method = env.db.scalar(select(AuditLog).where(AuditLog.action == "consent.method"))
    assert method.details["method"] == "voice"
    t.say(photo="cnic.jpg")                                                                          # 4
    assert t.last["state"] == "id_confirm" and "صحیح ہے" in t.last["say"]
    t.say(voice="جی")
    assert t.last["state"] == "death_have" and "وفات کا سرٹیفکیٹ" in t.last["say"]                  # 5
    t.say(voice="نہیں")
    say = t.last["say"]
    assert "مل گیا" in say and "کچھ کرنے کی ضرورت نہیں" in say                                       # found in records
    assert "اہل ہیں" in say and "روپے" in say and "بیوہ" in say                                     # 6
    assert "3 دن" in say and "SMS" in say and "اور کچھ پوچھنا ہے" in say                            # 7
    assert t.last["claim"]["status"] == "paid"
    kinds = [m.kind for m in env.db.scalars(select(SmsMessage).where(SmsMessage.user_id == t.u.id))]
    assert "received" in kinds and "paid" in kinds
    t.say(voice="میرے پیسے کب آئیں گے")
    assert "اکاؤنٹ" in t.last["say"] and t.last["state"] == "menu"
    t.say(voice="نہیں، شکریہ")
    assert t.last["ended"] is True


def test_english_and_unsupported_language(env):
    t = Talk(env)
    t.say(text="English please")
    assert t.last["lang"] == "en" and "help" in t.last["say"]
    t = Talk(env)
    t.say(text="سندھی")
    assert t.last["lang"] == "ur" and "دستیاب نہیں" in t.last["say"]


def test_did_not_understand_twice_shows_icon_buttons(env):
    t = Talk(env)
    t.say(text="اردو"); t.say(text="درخواست دینی ہے"); t.say(choice="yes")
    assert t.last["state"] == "consent"
    t.say(voice="بلبلبل")
    assert "دوبارہ بولیں" in t.last["say"] and t.last["state"] == "consent"
    t.say(voice="ززز")
    assert t.last["expect"] == "tap" and [b["id"] for b in t.last["buttons"]] == ["yes", "no"]
    assert all(b["icon"] for b in t.last["buttons"])
    t.say(choice="yes")
    assert t.last["state"] == "id_photo"
    assert env.db.scalar(select(AuditLog).where(AuditLog.action == "consent.method")).details["method"] == "tap"


def test_background_noise_asks_for_a_quiet_place_and_offers_buttons(env):
    t = Talk(env)
    t.say(choice="ur"); t.say(choice="how_to_apply")
    t.say(voice="<noise>")
    assert "خاموش جگہ" in t.last["say"] and t.last["expect"] == "tap" and t.last["buttons"]
    assert t.last["state"] == "offer_apply"
    t.say(choice="yes")
    assert t.last["state"] == "consent"


def test_signal_drop_resumes_at_the_same_step(env):
    t = Talk(env)
    t.say(choice="ur"); t.say(choice="how_to_apply"); t.say(choice="yes"); t.say(choice="yes")
    assert t.last["state"] == "id_photo"
    again = env.c.get("/agent", headers=t.h).json()          # the phone reconnects
    assert again["resumed"] and again["state"] == "id_photo" and "محفوظ" in again["say"]
    t.say(photo="cnic.jpg")
    assert t.last["state"] == "id_confirm"


def test_bad_photo_retake_then_officer_with_notes(env):
    t = Talk(env)
    t.say(choice="ur"); t.say(choice="how_to_apply"); t.say(choice="yes"); t.say(choice="yes")
    t.say(photo="retake.jpg")
    assert "دوبارہ لیں" in t.last["say"] and t.last["state"] == "id_photo"
    t.say(photo="blurry_retake.jpg")
    assert "یقین سے نہیں کہہ سکتی" in t.last["say"] and "افسر" in t.last["say"]
    case = env.db.get(Case, t.last["claim"]["case_id"])
    assert case.status == "escalated"
    notes = env.db.scalars(select(AuditLog).where(AuditLog.action == "case.note", AuditLog.case_id == case.id)).all()
    assert any("could not read" in n.details["note"] for n in notes)
    assert env.db.scalar(select(SmsMessage).where(SmsMessage.kind == "with_officer", SmsMessage.user_id == t.u.id))


def test_name_said_wrong_goes_to_a_person_check(env):
    t = Talk(env)
    t.say(choice="ur"); t.say(choice="how_to_apply"); t.say(choice="yes"); t.say(choice="yes")
    t.say(photo="cnic.jpg"); t.say(choice="no")
    assert "افسر آپ کا نام درست" in t.last["say"]
    t.say(choice="no")
    assert t.last["claim"]["status"] == "escalated"


def test_questions_and_handoffs_from_the_menu(env):
    t = Talk(env)
    t.say(choice="ur")
    t.say(voice="مجھے افسر سے بات کرنی ہے")
    assert "افسر آپ کو فون کرے گا" in t.last["say"]
    t.say(voice="کون سے کاغذات چاہیے")
    assert "شناختی کارڈ" in t.last["say"]
    t.say(voice="کسی نے پیسے مانگے ہیں")
    assert "مفت" in t.last["say"]


def test_helper_talks_for_a_family(env):
    s = env.scenario("S01")
    citizen = claim_runner.claimant(env.db, s)
    helper = env.user("helper@demo.pk", "helper")
    r = env.c.post("/agent/start", headers=env.H(helper, citizen.id), json={})
    assert r.status_code == 403  # no helper_access permission yet


def test_what_she_said_is_not_stored(env):
    t = Talk(env)
    t.say(voice="اردو"); t.say(voice="میری درخواست کا کیا بنا")
    for row in env.db.scalars(select(AuditLog).where(AuditLog.action == "agent.turn")):
        assert "درخواست" not in str(row.details)
    s = env.db.scalar(select(AgentSession))
    assert s.user_id == t.u.id


def test_someone_elses_card_is_noticed_in_the_conversation(env, monkeypatch):
    import json as _json
    from app import ai_engines
    fixture = _json.loads(_json.dumps(ai_engines._fixture("cnic", "clean")))
    fixture["fields"]["cnic"]["value"] = env.scenario("S02")["claimant"]["cnic"]
    monkeypatch.setattr(ai_engines, "_fixture", lambda doc_type, scenario: fixture)
    t = Talk(env)
    t.say(choice="ur"); t.say(choice="how_to_apply"); t.say(choice="yes"); t.say(choice="yes")
    t.say(photo="cnic.jpg")
    assert "مختلف" in t.last["say"] and "رخسانہ" in t.last["say"]   # her own name (in Urdu), not the card's
    t.say(choice="yes"); t.say(choice="no")
    assert t.last["claim"]["status"] == "escalated"
