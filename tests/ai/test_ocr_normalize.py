from datetime import date

import pytest

from ocr_core.normalize import (clean_address, clean_name, cnic_gender, normalize_relation, parse_card_date,
                                parse_cnic, parse_date)


@pytest.mark.parametrize("raw,want", [
    ("35202-0858542-8", "35202-0858542-8"),
    ("3520208585428", "35202-0858542-8"),
    ("35202-O858542-8", "35202-0858542-8"),      # letter O read for zero
    ("32103-9963008~2", "32103-9963008-2"),
    ("32103-99630080", None),                     # a dash lost and a digit misread: refuse, don't guess
    ("12345", None),
    ("", None),
])
def test_parse_cnic(raw, want):
    assert parse_cnic(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("14-Jun-2015", date(2015, 6, 14)),
    ("O1-Jan-1954", date(1954, 1, 1)),
    ("04-ul-2025", date(2025, 7, 4)),             # J missing
    ("14-Jun2015", date(2015, 6, 14)),
    ("July 13, 1986", date(1986, 7, 13)),
    ("July 13.1986", date(1986, 7, 13)),
    ("29-11-2012", date(2012, 11, 29)),
    ("29.11.2012", date(2012, 11, 29)),
    ("07-0ct-1967", date(1967, 10, 7)),           # zero read for O
    ("05-Ju1-2020", date(2020, 7, 5)),            # one read for l
    ("05-Ju-2020", None),                         # June or July? refuse
    ("31-Feb-2020", None),                        # impossible date
    ("mly1ey1986", None),                         # garbage must not become a date
    ("00Days00Months00Years", None),
])
def test_parse_date(raw, want):
    assert parse_date(raw) == want


def test_cnic_gender():
    assert cnic_gender("35202-0858542-8") == "Female"
    assert cnic_gender("35202-1234567-1") == "Male"
    assert cnic_gender("123") is None


@pytest.mark.parametrize("raw,want", [
    ("Tahlra Naseem", "Tahira Naseem"),   # l read for i
    ("Noseem Balg", "Naseem Baig"),
    ("BasheerAhmad Khan", "Basheer Ahmad Khan"),  # missing space restored
    ("Anees Bano", "Anees Bano"),
])
def test_clean_name(raw, want):
    assert clean_name(raw)[0] == want


def test_unknown_name_is_kept_and_marked():
    value, notes, unknown = clean_name("Zorbex Khan")
    assert value == "Zorbex Khan" and unknown and not notes


def test_relation_and_address():
    assert normalize_relation("Daughter") == "Daughter"
    assert normalize_relation("Daughtr") == "Daughter"
    assert normalize_relation("xyz") is None
    assert clean_address("TOWN,CltyLahore") == "TOWN,City Lahore"


@pytest.mark.parametrize("raw,want", [
    ("26.09.2019", "2019-09-26"), ("Lifetime", "lifetime"), ("Lifetlme", "lifetime"), ("1955", "1955"),
    ("l955", "1955"), ("01:01.1973", "1973-01-01"), ("01011973", "1973-01-01"), ("01.01,1969", "1969-01-01"),
    ("Pakistan", None), ("", None),
])
def test_parse_card_date(raw, want):
    assert parse_card_date(raw) == want


# ---- death certificate numbers: the formats seen on real and sample certificates ----
import pytest  # noqa: E402

from ocr_core.death_certificate import tracking_id  # noqa: E402


@pytest.mark.parametrize("text,want", [
    (": 91100067591436", "91100067591436"),
    (": 91-100076542318", "91100076542318"),
    ("92 - 110007845612", "92110007845612"),
    ("9110OO67591436", "91100067591436"),        # O read for 0
    ("DC-2507-913284", "DC-2507-913284"),
    ("TRK20261100143", "TRK20261100143"),
    ("EXM-2026-001245", "EXM-2026-001245"),
    ("DR-0004587", "DR-0004587"),
    ("Islam", None), ("12345", None), ("", None),
])
def test_tracking_id_formats(text, want):
    assert tracking_id(text) == want
