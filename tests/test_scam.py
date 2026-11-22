# -*- coding: utf-8 -*-
import pytest

from app.rules import DEFAULT_RULES as R
from app.scam_classifier import MODEL_PATH, classify, normalize_text

pytestmark = pytest.mark.skipif(not MODEL_PATH.exists(), reason="run: python -m scripts.train_scam")


def test_urdu_scam_is_blocked():
    r = classify("آپ کی رقم روک دی گئی ہے، ابھی اپنا پن اور شناختی کارڈ نمبر بھیجیں 03001234567", R)
    assert r["label"] == "scam" and r["action"] == "block_and_warn"
    assert r["red_flags"]


def test_roman_urdu_scam_is_blocked():
    r = classify("mubarak! aap ne inaam jeet liya, raqam lene ke liye link par click karein http://bit.ly/ab12", R)
    assert r["label"] == "scam"


def test_genuine_message_is_not_flagged():
    r = classify("آپ کی درخواست موصول ہو گئی ہے۔ ہم جلد آپ کو آگاہ کریں گے۔", R)
    assert r["label"] != "scam"


def test_warning_message_is_not_flagged_as_scam():
    r = classify("کسی کو اپنا او ٹی پی نہ دیں، ہمارا عملہ کبھی نہیں مانگتا", R)
    assert r["label"] != "scam"
    assert r["safe_signals"]


def test_threshold_comes_from_the_rule_version():
    msg = "آپ کی سم بلاک ہو رہی ہے، فوراً رابطہ کریں 03001234567 اور اپنا شناختی کارڈ نمبر بتائیں"
    lenient = {**R, "scam_block_min": 0.999}
    assert classify(msg, lenient, 5)["rule_version"] == 5
    assert classify(msg, lenient)["label"] != "scam"  # same text, stricter bar -> no longer auto-blocked


def test_normalisation_unifies_urdu_letter_variants():
    assert normalize_text("كيا") == normalize_text("کیا")
    assert "urltoken" in normalize_text("click http://bit.ly/abc")