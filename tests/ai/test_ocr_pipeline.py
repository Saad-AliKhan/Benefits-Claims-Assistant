"""The real OCR pipeline on invented SPECIMEN documents (about 5 s per document on 2 CPU cores)."""
import pytest

from ocr_core import BadImage, load_engine, read_document
from tools.ocr.specimens import (as_phone_photo, fake_card, fake_death, render_cnic_back, render_death_certificate,
                             render_smart_cnic, to_jpeg)


@pytest.fixture(scope="module")
def engine():
    return load_engine()


def check(result, expected):
    wrong = {k: (result["fields"][k]["value"], v) for k, v in expected.items() if result["fields"][k]["value"] != v}
    silent = [k for k in wrong if not result["fields"][k]["needs_review"]]
    assert not silent, f"wrong values not marked for review: {wrong}"
    return wrong


def test_death_certificate_scan(engine):
    p = fake_death(11)
    r = read_document(engine, "death_certificate", to_jpeg(render_death_certificate(p)))
    assert not check(r, p.expected())
    assert r["fields"]["deceased.cnic"]["method"] == "ocr+urdu_side_agree"


def test_death_certificate_phone_photo_and_late_flag(engine):
    p = fake_death(12, late=True)
    r = read_document(engine, "death_certificate", to_jpeg(as_phone_photo(render_death_certificate(p), seed=12)))
    check(r, p.expected())
    assert "LATE_REGISTRATION" in {f["code"] for f in r["flags"]}


def test_smart_cnic_photo(engine):
    c = fake_card(21)
    r = read_document(engine, "cnic", to_jpeg(as_phone_photo(render_smart_cnic(c), seed=21)))
    assert r["fields"]["card.type"]["value"] == "smart"
    assert not check(r, c.expected())


def test_wrong_document_is_refused(engine):
    card = to_jpeg(render_smart_cnic(fake_card(22)))
    with pytest.raises(BadImage):
        read_document(engine, "death_certificate", card)


@pytest.mark.parametrize("qr", [True, False], ids=["with_qr", "without_qr"])
def test_cnic_back_is_refused(engine, qr):
    back = to_jpeg(as_phone_photo(render_cnic_back(fake_card(23), qr=qr), seed=23, strength=0.5))
    with pytest.raises(BadImage) as err:
        read_document(engine, "cnic", back)
    assert err.value.reason in ("cnic_back_side", "cnic_front_not_found")
