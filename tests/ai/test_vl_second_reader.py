# -*- coding: utf-8 -*-
"""PaddleOCR-VL-1.6 as the second reader (ocr_core/vl.py), with a stand-in for the model (the real one is ~2 GB
and slow on CPU; it is measured on the laptop with tools/ocr/evaluate_vl.py).

What must hold: it never changes a value silently; agreement raises confidence; disagreement sends the value to a
person; Urdu names are added (and fill an old green card's empty names) but always for review; it is skipped when
it cannot help; and if it breaks, the main reading stands."""
import pytest

from ocr_core import vl
from ocr_core.datatypes import Extraction, Field, Flag

GREEN_CARD_TEXT = """اسلامی جمہوریہ پاکستان
قومی شناختی کارڈ
نام
رخسانہ بی بی
شوہر کا نام
محمد اسلم
شناختی نشان تل دائیں گال پر
35202-1234567-2
12.03.1975"""


def cnic_ex(value="35202-1234567-2", conf=0.7, review=True, dob="1975-03-12", card="smart", name="Rukhsana Bibi"):
    f = {"card.type": Field(card, 0.9), "cnic": Field(value, conf, review, value, "reread_vote"),
         "date_of_birth": Field(dob, 0.95 if dob else 0.0, dob is None, dob),
         "name": Field(name, 0.9) if name else Field(None, 0.0, method="urdu_only_on_card"),
         "father_or_husband_name": Field(None, 0.0, method="urdu_only_on_card"),
         "father_or_husband.relation": Field(None, 0.0, method="not_determined")}
    flags = [Flag("URDU_ONLY_FIELDS", "info", "old green card")] if card == "old_green" else []
    return Extraction("cnic", f, flags, {}, ("cnic", "date_of_birth"))


# ---- reading its text
def test_urdu_names_old_green_card_layout():
    assert vl.urdu_names(GREEN_CARD_TEXT) == {"name": "رخسانہ بی بی", "relative": "محمد اسلم", "relation": "Husband"}


@pytest.mark.parametrize("text, want", [
    ("نام: رخسانہ بی بی\nوالد کا نام: غلام رسول", ("رخسانہ بی بی", "غلام رسول", "Father")),
    ("نام: رخسانہ بی بی\nوالد / شوہر کا نام: محمد اسلم", ("رخسانہ بی بی", "محمد اسلم", None)),
    ("<p>نام</p><p>نسرین اختر</p>", ("نسرین اختر", None, None)),
    ("Name\nRukhsana Bibi\nGender F / عورت", (None, None, None)),        # English only: nothing invented
    ("نام\nاسلامی جمہوریہ پاکستان", (None, None, None)),                  # a heading is not a name
])
def test_urdu_names_variants(text, want):
    r = vl.urdu_names(text)
    assert (r["name"], r["relative"], r["relation"]) == want


def test_numbers_and_dates_in_its_text():
    assert vl.cnic_numbers("Identity Number 35202-1234567-2 and ۳۵۲۰۲۱۲۳۴۵۶۷۸") == ["35202-1234567-2",
                                                                                   "35202-1234567-8"]
    assert vl.dates("12.03.1975 01.02.2015 01.02.2025") == ["1975-03-12", "2015-02-01", "2025-02-01"]


# ---- folding it into a reading
def test_agreement_raises_confidence_and_clears_review():
    ex = cnic_ex(conf=0.7)
    rep = vl.apply_cnic(ex, "35202-1234567-2 12.03.1975")
    c = ex.fields["cnic"]
    assert rep["cnic"] == "agree" and c.confidence > 0.9 and not c.needs_review and "vl_agree" in c.method


def test_disagreement_goes_to_a_person_and_keeps_the_value():
    ex = cnic_ex(conf=0.9, review=False)
    rep = vl.apply_cnic(ex, "35202-1234567-8")
    c = ex.fields["cnic"]
    assert rep["cnic"] == "differ" and c.value == "35202-1234567-2"
    assert c.needs_review and c.confidence <= 0.7 and "35202-1234567-8" in c.note


def test_earlier_dispute_stays_for_review():
    ex = cnic_ex(conf=0.7)
    ex.fields["cnic"].note = "two readings differ: 35202-1234567-2 vs 35202-1234567-3"
    vl.apply_cnic(ex, "35202-1234567-2")
    assert ex.fields["cnic"].needs_review


def test_missing_date_of_birth_is_filled_for_review_only():
    ex = cnic_ex(dob=None)
    ex.flags.append(Flag("MISSING_KEY_FIELD", "warning", "date_of_birth could not be read"))
    vl.apply_cnic(ex, "12.03.1975 01.02.2015 01.02.2025")
    d = ex.fields["date_of_birth"]
    assert d.value == "1975-03-12" and d.needs_review and d.confidence <= 0.6
    assert not any(f.code == "MISSING_KEY_FIELD" for f in ex.flags)


def test_green_card_gets_its_urdu_names_for_review():
    ex = cnic_ex(card="old_green", name=None)
    vl.apply_cnic(ex, GREEN_CARD_TEXT)
    f = ex.fields
    assert f["name"].value == "رخسانہ بی بی" and f["name"].needs_review and f["name"].method == "paddleocr_vl(urdu)"
    assert f["father_or_husband_name"].value == "محمد اسلم"
    assert f["father_or_husband.relation"].value == "Husband" and f["father_or_husband.relation"].needs_review
    assert any(fl.code == "URDU_NAMES_READ" for fl in ex.flags)


def test_smart_card_english_name_is_never_replaced():
    ex = cnic_ex(name="Rukhsana Bibi")
    vl.apply_cnic(ex, "نام: رخسانہ بی بی")
    assert ex.fields["name"].value == "Rukhsana Bibi" and ex.fields["name_ur"].value == "رخسانہ بی بی"


def test_certificate_numbers_confirmed_only_when_found():
    f = {"deceased.cnic": Field("35202-7654321-1", 0.7, True), "applicant.cnic": Field("35202-1234567-2", 0.7, True),
         "deceased.date_of_death": Field("2026-01-05", 0.95), "certificate.tracking_id": Field("A1234567", 0.7, True)}
    ex = Extraction("death_certificate", f, [], {}, tuple(f))
    rep = vl.apply_certificate(ex, "CNIC 35202-7654321-1 ... 05-01-2026 ... Tracking ID: 1234567")
    assert rep == {"deceased.cnic": "agree", "deceased.date_of_death": "agree", "certificate.tracking_id": "agree"}
    assert not f["deceased.cnic"].needs_review
    assert f["applicant.cnic"].needs_review and f["applicant.cnic"].confidence == 0.7   # not found: untouched


# ---- when it runs
def test_when_unsure_mode(monkeypatch):
    monkeypatch.setenv("OCR_VL", "when_unsure")
    assert vl.should_run(cnic_ex(conf=0.7, review=True))
    assert not vl.should_run(cnic_ex(conf=0.99, review=False))
    assert vl.should_run(cnic_ex(conf=0.99, review=False, card="old_green", name=None))
    monkeypatch.setenv("OCR_VL", "off")
    assert not vl.should_run(cnic_ex(conf=0.7))
    monkeypatch.setenv("OCR_VL", "always")
    assert vl.should_run(cnic_ex(conf=0.99, review=False))


class FakeReader:
    name = "fake-vl"

    def __init__(self, text=None, boom=False):
        self.text, self.boom, self.calls = text, boom, 0

    def read(self, image, max_new_tokens=256):
        self.calls += 1
        if self.boom:
            raise RuntimeError("out of memory")
        return self.text


def test_second_opinion_records_what_it_did(monkeypatch):
    monkeypatch.setenv("OCR_VL", "when_unsure")
    r = FakeReader("35202-1234567-2")
    monkeypatch.setattr(vl, "get", lambda: r)
    ex = cnic_ex(conf=0.7)
    vl.second_opinion(ex, None)
    assert r.calls == 1 and ex.quality["second_reader"]["results"]["cnic"] == "agree"


def test_not_installed_or_not_needed_means_not_asked(monkeypatch):
    monkeypatch.setenv("OCR_VL", "when_unsure")
    r = FakeReader("x")
    monkeypatch.setattr(vl, "get", lambda: r)
    vl.second_opinion(cnic_ex(conf=0.99, review=False), None)
    assert r.calls == 0
    monkeypatch.setattr(vl, "get", lambda: None)
    ex = cnic_ex(conf=0.7)
    vl.second_opinion(ex, None)
    assert "second_reader" not in ex.quality and ex.fields["cnic"].confidence == 0.7


def test_a_failure_leaves_the_main_reading(monkeypatch):
    monkeypatch.setenv("OCR_VL", "always")
    monkeypatch.setattr(vl, "get", lambda: FakeReader(boom=True))
    ex = cnic_ex(conf=0.7)
    vl.second_opinion(ex, None)
    assert ex.quality["second_reader"]["error"] and ex.fields["cnic"].confidence == 0.7


def test_off_by_default_when_not_downloaded(monkeypatch, tmp_path):
    monkeypatch.setattr(vl, "FOLDER", tmp_path / "nope")
    monkeypatch.setenv("OCR_VL", "always")
    assert vl.get() is None and vl.status()["downloaded"] is False


def test_whole_pipeline_on_a_specimen_with_the_second_reader(monkeypatch):
    """The real main reader on an invented card + a second reader that agrees: same values, none silently wrong."""
    from ocr_core import load_engine, read_document
    from tools.ocr.specimens import as_phone_photo, fake_card, render_smart_cnic, to_jpeg
    c = fake_card(21)
    monkeypatch.setenv("OCR_VL", "always")
    monkeypatch.setattr(vl, "get", lambda: FakeReader(f"Identity Number {c.expected()['cnic']}"))
    r = read_document(load_engine(), "cnic", to_jpeg(as_phone_photo(render_smart_cnic(c), seed=21)))
    assert r["quality"]["second_reader"]["results"].get("cnic") == "agree"
    for k, want in c.expected().items():
        assert r["fields"][k]["value"] == want or r["fields"][k]["needs_review"], k
