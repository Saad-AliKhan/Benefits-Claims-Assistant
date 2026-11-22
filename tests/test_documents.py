"""The document reader on top of the OCR engine (mock answers from data/ocr_fixtures): rules, fallbacks."""
import io
import json

import pytest
from PIL import Image

from app import ai_engines, decision_engine, doc_check, document_reader
from app.config import settings
from app.rules import DEFAULT_RULES

CLAIMANT, DECEASED = "35202-7654321-2", "35202-1234567-1"


def png():
    b = io.BytesIO()
    Image.new("RGB", (900, 600), "white").save(b, "PNG")
    return b.getvalue()


@pytest.fixture(autouse=True)
def mock_ocr(monkeypatch):
    monkeypatch.setattr(settings, "ocr_mock", True)


def test_clean_cnic_of_the_claimant_is_auto():
    d = document_reader.read_cnic(png(), DEFAULT_RULES, 1, CLAIMANT, filename="card.png")
    assert d["source"] == "ocr_engine" and d["action"] == "auto" and d["confidence"] == pytest.approx(0.96)


@pytest.mark.parametrize("filename, claimed, action, flag", [
    ("card.png", "42101-1234567-1", "human", "printed_account_mismatch"),
    ("flag.png", CLAIMANT, "human", "CARD_EXPIRED"),
    ("retake.png", CLAIMANT, "ask_more", "retake_cnic_number_unreadable"),
])
def test_cnic_rules(filename, claimed, action, flag):
    d = document_reader.read_cnic(png(), DEFAULT_RULES, 1, claimed, filename=filename)
    assert d["action"] == action and flag in d["flags"]


@pytest.mark.parametrize("filename, claimant, action, flag", [
    ("cert.png", CLAIMANT, "auto", None),
    ("cert.png", "42101-1234567-1", "human", "applicant_not_claimant"),
    ("cert.png", DECEASED, "human", "claimant_is_deceased"),
    ("flag.png", CLAIMANT, "human", "QR_UNTRUSTED_DOMAIN"),
    ("retake.png", CLAIMANT, "ask_more", None),
])
def test_death_certificate_rules(filename, claimant, action, flag):
    d = document_reader.read_death_certificate(png(), DEFAULT_RULES, 1, claimant, filename=filename)
    assert d["action"] == action and (flag is None or flag in d["flags"])


def test_engine_not_ready_uses_tesseract_or_a_person(monkeypatch):
    monkeypatch.setattr(settings, "ocr_mock", False)
    monkeypatch.setitem(ai_engines._state, "ocr", None)
    monkeypatch.setattr(settings, "local_ocr_fallback", False)
    d = document_reader.read_cnic(png(), DEFAULT_RULES, 1, CLAIMANT)
    assert d["action"] == "human" and d["flags"] == ["ocr_unavailable"]
    monkeypatch.setattr(settings, "local_ocr_fallback", True)
    try:
        d = document_reader.read_cnic(png(), DEFAULT_RULES, 1, CLAIMANT)
    except doc_check.OcrUnavailable:
        pytest.skip("Tesseract not installed")
    assert d["source"] in ("local_tesseract", "none")


def test_not_an_image_is_refused():
    with pytest.raises(document_reader.BadImage):
        document_reader.read_cnic(b"not an image", DEFAULT_RULES, 1, CLAIMANT)


def test_retake_message_from_the_reader_reaches_the_citizen():
    doc = document_reader.read_cnic(png(), DEFAULT_RULES, 1, CLAIMANT, filename="retake.png")
    ident = {"action": "auto", "confidence": 0.99, "detail": "ok"}
    elig = {"action": "auto", "confidence": 0.99, "problems": [], "detail": "ok"}
    r = decision_engine.decide(25000, ident, elig, None, doc, DEFAULT_RULES, 1)
    assert r["outcome"] == "yellow" and r["reason_user_ur"] == ai_engines._fixture("cnic", "retake")["detail"]["message_ur"]
