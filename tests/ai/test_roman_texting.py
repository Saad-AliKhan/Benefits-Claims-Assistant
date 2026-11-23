"""Roman Urdu as people text it (2026-11-23 round): vowels dropped, 'ha' for 'hai', 'darkhast' spellings."""
import pytest

from app.agent import english_intent, looks_roman_urdu
from urdu_intent import detect_intent


@pytest.mark.parametrize("text,intent", [
    ("mujay darkhuwast deni ha", "how_to_apply"),     # reported from the demo laptop
    ("mjhe darkhast deni hai", "how_to_apply"),
    ("darkhast kaise du", "how_to_apply"),             # was 'qist' (instalment) -> payment_status
    ("mjhe pese kab milenge", "payment_status"),
    ("kisi ne phone kr ke paise mange", "report_fraud"),
    ("mujhe ye madad mil skti ha", "eligibility"),
    ("aoa", "greeting"),
])
def test_texting_spellings(text, intent):
    assert detect_intent(text)["intent"] == intent


@pytest.mark.parametrize("text", ["aaj mausam kaisa ha", "bachon ka school kab khulega"])
def test_off_topic_stays_unclear(text):
    assert detect_intent(text)["intent"] == "unclear"   # 'aoa' used to match any 'ha'


def test_english_mode_understands_roman_urdu():
    assert english_intent("mujay darkhuwast deni ha")["intent"] == "how_to_apply"
    assert not looks_roman_urdu("Why was my claim turned down?")   # real English never goes to the Urdu engine
