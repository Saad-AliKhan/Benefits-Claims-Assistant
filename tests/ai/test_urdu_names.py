"""Names in Urdu and English script are the same name (2026-11-23): the English one is converted into Urdu
and the two are compared there."""
import pytest

from app.name_match import match_name, name_score
from app.urdu_names import same_name_score, to_urdu

RULES = {"name_match_auto_min": 0.92, "name_match_review_min": 0.75}


@pytest.mark.parametrize("english,urdu", [
    ("Rukhsana Bibi", "رخسانہ بی بی"), ("Ruksana Bibi", "رخسانہ بی بی"), ("Mohammad Aslam", "محمد اسلم"),
    ("Shazia Perveen", "شازیہ پروین"), ("Fatimah Bibi", "فاطمہ بی بی"), ("Saima Rashid", "سائمہ راشد"),
    ("Hina Batool", "حنا بتول"), ("Mohd Yousaf", "محمد یوسف"),
])
def test_same_name_in_two_scripts(english, urdu):
    assert name_score(english, urdu) >= RULES["name_match_auto_min"]
    assert name_score(urdu, english) >= RULES["name_match_auto_min"]


@pytest.mark.parametrize("english,urdu", [
    ("Rukhsana Bibi", "نسرین بی بی"), ("Muhammad Aslam", "محمد اکرم"), ("Kausar Begum", "کلثوم بیگم"),
    ("Arshad Mahmood", "راشد محمود"), ("Asif Khan", "عائشہ خان"),
])
def test_different_people_are_never_an_automatic_match(english, urdu):
    assert name_score(english, urdu) < RULES["name_match_auto_min"]


def test_registration_in_english_card_in_urdu():
    r = match_name("رخسانہ بی بی", "35202-7654321-2", [{"name": "Rukhsana Bibi", "cnic": "35202-7654321-2"}], RULES)
    assert r["status"] == "match" and r["action"] == "auto"


def test_to_urdu():
    assert to_urdu("Rukhsana Bibi") == "رخسانہ بی بی"
    assert to_urdu("Muhammad Aslam") == "محمد اسلم"
    assert to_urdu("رخسانہ بی بی") == "رخسانہ بی بی"
    assert same_name_score("Rukhsana Bibi", "Ruksana Bibi") == 1.0
