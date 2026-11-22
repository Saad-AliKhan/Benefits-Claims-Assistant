"""Intent detection must never pick a WRONG intent on the test sets (unclear is allowed)."""
import json
from pathlib import Path

import pytest

from urdu_intent import detect_intent

HERE = Path(__file__).resolve().parents[2] / "tools" / "voice"  # the utterance sets


# 31 intents (Urdu + Roman Urdu) since 2026-11-22; before that 12 intents, held-out bar 0.85. A miss must be
# "unclear" (the agent then offers the two likeliest meanings as buttons), never a wrong intent.
@pytest.mark.parametrize("name,min_correct", [("test_utterances.json", 0.90), ("test_heldout.json", 0.80)])
def test_no_wrong_intents(name, min_correct):
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
