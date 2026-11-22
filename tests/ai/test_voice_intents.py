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
BARS = {"test_utterances.json": (0.90, 0.90), "test_heldout.json": (0.80, 0.75), "test_heldout2.json": (0.88, 0.85)}


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
