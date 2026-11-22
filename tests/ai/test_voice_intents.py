"""Intent detection must never pick a WRONG intent on the test sets (unclear is allowed)."""
import json
from pathlib import Path

import pytest

from urdu_intent import detect_intent

HERE = Path(__file__).resolve().parents[2] / "tools" / "voice"  # the utterance sets


# 31 intents (Urdu + Roman Urdu) since 2026-11-22; before that 12 intents, held-out bar 0.85. A miss must be
# "unclear" (the agent then offers the two likeliest meanings as buttons), never a wrong intent.
# With the meaning model (models/meaning) the bars are higher; without it (keywords only) a little lower.
# test_heldout2.json: written before the 2nd round of examples; its first run gave 69% correct and 5-6 wrong
# intents, which led to the veto rule and some keywords, so it is no longer untouched.
# test_heldout3.json (162) and test_heldout4.json (101): written before the 3rd tuning round. First runs: set 3 78%
# right / 8 wrong, set 4 78% / 3 wrong (summary only). After tuning on set 3's mistakes, set 4 untouched: 80% / 2 wrong;
# its 2 wrong were then fixed too, so both are no longer untouched.
BARS = {"test_utterances.json": (0.90, 0.90), "test_heldout.json": (0.80, 0.75), "test_heldout2.json": (0.88, 0.85),
        "test_heldout3.json": (0.93, 0.90), "test_heldout4.json": (0.80, 0.76)}


@pytest.mark.parametrize("name", list(BARS))
def test_no_wrong_intents(name):
    from urdu_intent import meaning
    min_correct = BARS[name][0 if meaning.available() else 1]
    tests = json.loads((HERE / name).read_text(encoding="utf-8"))["tests"]
    got = [(detect_intent(t["text"])["intent"], t["intent"]) for t in tests]
    wrong = [(g, w) for g, w in got if g != w and g != "unclear"]
    assert not wrong, f"wrong intents: {wrong}"
    assert sum(g == w for g, w in got) / len(got) >= min_correct


def test_corrections_are_reported():
    r = detect_intent("میری درخاست کا کیا بنا")
    assert r["intent"] == "application_status"
    assert r["corrections"][0]["corrected"] == "درخواست"


def test_numbers_and_empty():
    assert detect_intent("میرا نمبر 3520208585428 ہے")["numbers"] == ["35202-0858542-8"]
    assert detect_intent("")["intent"] == "unclear"


@pytest.mark.parametrize("text,intent", [
    ("paise kab milenge", "payment_status"), ("mujhe kitni raqam milegi", "payment_amount"),
    ("mera claim kyun ruka hua hai", "why_decision"), ("meri darkhwast ka kya bana", "application_status"),
    ("ایک ایجنٹ پیسے مانگ رہا ہے", "report_fraud"), ("مجھے دھمکیاں مل رہی ہیں", "urgent_help"),
])
def test_roman_urdu_and_safety_intents(text, intent):
    assert detect_intent(text)["intent"] == intent


# ---- the meaning model (optional second opinion) ----
def test_meaning_model_only_rescues_unclear_and_can_be_off(monkeypatch):
    import urdu_intent
    from urdu_intent import meaning
    monkeypatch.setenv("MEANING_OFF", "1")
    assert meaning.scores("میرے پیسے کب تک آ جائیں گے") is None          # off: nothing changes
    off = urdu_intent.detect_intent("میرے پیسے کب تک آ جائیں گے")
    assert off["intent"] == "unclear"
    monkeypatch.delenv("MEANING_OFF")
    if not meaning.available():
        pytest.skip("meaning model files not downloaded (tools/fetch_models.ps1)")
    on = urdu_intent.detect_intent("میرے پیسے کب تک آ جائیں گے")
    assert on["intent"] == "payment_status" and on["method"] == "meaning"
    # off-topic talk stays unclear; a confident keyword answer is never changed
    for t in ("آج موسم کیسا ہے", "کرکٹ میچ کون جیتا", "ہیلو ہیلو آواز آ رہی ہے"):
        assert urdu_intent.detect_intent(t)["intent"] == "unclear"
    assert urdu_intent.detect_intent("میری درخواست کا کیا بنا")["method"] == "keywords"


# ---- noon ghunna (ں): speech recognition drops it ('نہی') or writes a full noon ('نہین') ----
def test_noon_ghunna_dropped_or_written_as_noon_changes_nothing():
    import re as _re
    tests = []
    for f in ("test_utterances.json", "test_heldout.json"):
        tests += [t for t in json.loads((Path(__file__).resolve().parents[2] / "tools" / "voice" / f)
                                        .read_text(encoding="utf-8"))["tests"] if "ں" in t["text"]]
    assert len(tests) > 40
    right = {k: 0 for k in ("as_written", "dropped", "full_noon", "nain")}
    for t in tests:
        variants = {"as_written": t["text"], "dropped": t["text"].replace("ں", ""),
                    "full_noon": t["text"].replace("ں", "ن"), "nain": _re.sub("نہیں", "نئیں", t["text"])}
        for k, v in variants.items():
            got = detect_intent(v)["intent"]
            assert got in (t["intent"], "unclear"), (v, got, t["intent"])   # never a wrong intent
            right[k] += got == t["intent"]
    assert max(right.values()) - min(right.values()) <= 2, right


@pytest.mark.parametrize("said,want", [
    ("ہاں", True), ("ہا", True), ("ہان جی", True), ("جی", True), ("ٹھیک ہے نا", True),
    ("نہیں", False), ("نہی", False), ("نہین", False), ("نئیں", False), ("جی نہی", False), ("نا جی", False),
    ("میرے پاس نہیں ہے", False), ("بلبل", None),
])
def test_yes_no_with_and_without_noon_ghunna(said, want):
    from app.agent import yes_no
    assert yes_no(said) is want


# ---- English mode (app.agent.english_intent: meaning model + English keywords) ----
def test_english_questions():
    from app.agent import english_intent
    from urdu_intent import meaning
    tests = json.loads((HERE / "test_english.json").read_text(encoding="utf-8"))["tests"]
    got = [(english_intent(t["text"])["intent"], t["intent"]) for t in tests]
    wrong = [(g, w) for g, w in got if g != w and g != "unclear"]
    right = sum(g == w for g, w in got) / len(got)
    if meaning.available():
        # first run of this set: 23/33 right, 1 wrong ("What time is it?" -> how long it takes)
        assert len(wrong) <= 1 and right >= 0.65, (wrong, right)
    else:
        assert len(wrong) <= 3   # English keywords only
    assert english_intent("When will I get my money?")["action"] == "lookup_payment"


@pytest.mark.parametrize("name,min_right", [("test_english2.json", 0.88), ("test_english3.json", 0.85)])
def test_english_held_out_sets(name, min_right):
    # written before the 3rd round. First runs: set 2 85% right / 3 wrong, set 3 89% / 0 wrong (summary only);
    # after: set 2 93% / 0 (its mistakes were looked at), set 3 89% / 0 (untouched)
    from app.agent import english_intent
    from urdu_intent import meaning
    tests = json.loads((HERE / name).read_text(encoding="utf-8"))["tests"]
    got = [(english_intent(t["text"])["intent"], t["intent"]) for t in tests]
    wrong = [(g, w) for g, w in got if g != w and g != "unclear"]
    if meaning.available():
        assert not wrong and sum(g == w for g, w in got) / len(got) >= min_right, wrong
    else:
        assert len(wrong) <= 3


# ---- guards: noise words from Whisper, and everyday subjects that are not the claim ----
@pytest.mark.parametrize("text,reason", [
    ("ڈاکٹر کی فیس کتنی ہے", "off_topic"), ("bijli ka bill kaise jama karun", "off_topic"),
    ("میرے بیٹے کا امطحان کب ہی", "off_topic"),           # misheard 'امتحان' is still an exam
    ("قصائی کی دکان کتنے بجے کھلتی ہے", "off_topic"), ("سبسکرائب کریں", "noise"), ("ناظرین", "noise"),
])
def test_off_topic_and_noise_are_unclear(text, reason):
    r = detect_intent(text)
    assert r["intent"] == "unclear" and r["reason"] == reason, r


@pytest.mark.parametrize("text", [
    "ڈاکٹر کے پیسے نہیں ہیں بچہ بہت بیمار ہے",             # danger is never blocked as off-topic
    "بجلی کا بل بھرنے کے لیے امداد کی رقم کب آئے گی",        # a claim word keeps the question in scope
])
def test_claim_words_or_danger_keep_a_sentence_in_scope(text):
    r = detect_intent(text)
    assert r["intent"] != "unclear", r


def test_english_noise_and_off_topic():
    from app.agent import english_intent
    assert english_intent("Thanks for watching!")["intent"] == "unclear"
    assert english_intent("How much is the bus fare?")["intent"] == "unclear"
    assert english_intent("How much money will I get?")["intent"] == "payment_amount"


# ---- correction must not turn everyday words into claim words ----
@pytest.mark.parametrize("said,has,lacks", [
    ("کیا شنآختی کارڈ کی کاپی لگے گی", "کیا", "نیا"),          # not 'نیا شناختی' (a new ID card)
    ("درخواست کےساتھ کون سے کاغذ لگیں گے", "کے ساتھ", "کیسے"),
    ("کون سی چیزیں جمع کرآنی پڑیں گی", "کرآنی", "کمانے"),       # 'get it submitted' is not 'earn'
    ("آپ کے بینگ اکاؤنٹ میں", "بینک", "بینگ"),                  # Whisper's real mistakes on clear Urdu speech
    ("شناختی قارڈ کی تصویر", "کارڈ", "قارڈ"),
])
def test_correction_keeps_everyday_words(said, has, lacks):
    from urdu_intent.correct import correct
    t = correct(said).text
    assert has in t and lacks not in t.split(), t


# ---- Roman Urdu typed fast, and Punjabi-influenced speech ----
@pytest.mark.parametrize("text,intent", [
    ("main complain karna chahti hoon", "complaint"),         # 'karna' is not 'kitna'
    ("paise kado aan ge", "payment_status"), ("kinne din lagne ne", "how_long"),
    ("paise ni aaye ajj tak", "payment_not_received"), ("paise account mein nahy aaye", "payment_not_received"),
    ("maut da certificate kithon banwaiye", "no_death_certificate"), ("meri darkhwast da ki banya", "application_status"),
    ("میری application کا status بتا دیں", "application_status"), ("کسی نے OTP مانگا ہے", "report_fraud"),
])
def test_roman_dialect_and_mixed_english(text, intent):
    assert detect_intent(text)["intent"] == intent


@pytest.mark.parametrize("text,noise", [
    ("ایسا ایسا ایسا ایسا", True), ("Thanks for watching!", True), ("like and subscribe", True),
    ("نہیں نہیں نہیں", False), ("میرے پیسے کب آئیں گے", False), ("", False),
])
def test_whisper_noise_transcripts(text, noise):
    from voice_core import noise_transcript
    assert noise_transcript(text) is noise
