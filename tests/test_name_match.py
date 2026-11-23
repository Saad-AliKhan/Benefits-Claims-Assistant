from app.name_match import match_name, name_score
from app.rules import DEFAULT_RULES as R

PEOPLE = [
    {"name": "Mohammad Ali", "cnic": "42101-1111111-1"},
    {"name": "Ayesha Bibi", "cnic": "42101-2222222-2"},
    {"name": "Muhammad Asif", "cnic": "42101-3333333-3"},
    {"name": "Ali Raza", "cnic": "42101-4444444-4"},
]


def test_muhammad_variants_all_match():
    for q in ["Muhammad Ali", "Muhammed Ali", "Mohammed Ali", "Mohammad Ali", "Muhamad Ali", "M. Ali"]:
        r = match_name(q, None, PEOPLE, R)
        assert r["status"] == "match", (q, r["status"], r["confidence"])
        assert r["best"]["cnic"] == "42101-1111111-1"


def test_word_order_and_spelling():
    assert match_name("Ali Muhammad", None, PEOPLE, R)["status"] == "match"
    assert match_name("Aisha Bibi", None, PEOPLE, R)["status"] == "match"


def test_different_people_do_not_match():
    assert match_name("Muhammad Asif", None, PEOPLE[:1], R)["status"] == "no_match"
    assert name_score("Ali Khan", "Ali Raza") < R["name_match_review_min"]


def test_two_people_same_name_is_ambiguous_never_guessed():
    people = [{"name": "Muhammad Ali", "cnic": "42101-1111111-1"},
              {"name": "Mohammad Ali", "cnic": "42101-9999999-9"}]
    r = match_name("Muhammed Ali", None, people, R)
    assert r["status"] == "ambiguous" and r["action"] == "human"


def test_same_cnic_duplicate_rows_collapse():
    people = [{"name": "Mohammad Ali", "cnic": "4210111111111"},
              {"name": "Muhammad Ali", "cnic": "42101-1111111-1"}]
    r = match_name("Muhammad Ali", None, people, R)
    assert r["status"] == "match" and r["duplicates_collapsed"] == 1


def test_cnic_conflict_goes_to_human():
    r = match_name("Muhammad Ali", "42101-5555555-5", PEOPLE, R)
    assert r["status"] == "cnic_conflict" and r["action"] == "human"


def test_cnic_equal_but_name_wrong_goes_to_human():
    r = match_name("Zubaida Khan", "42101-1111111-1", PEOPLE, R)
    assert r["status"] == "cnic_match_name_mismatch" and r["action"] == "human"


def test_cnic_equal_resolves_ambiguity():
    people = [{"name": "Muhammad Ali", "cnic": "42101-1111111-1"},
              {"name": "Mohammad Ali", "cnic": "42101-9999999-9"}]
    r = match_name("Muhammad Ali", "42101-9999999-9", people, R)
    assert r["status"] == "match" and r["best"]["cnic"] == "42101-9999999-9"


def test_near_match_goes_to_human_and_threshold_is_live():
    r = match_name("Muhammad Alee Khan", None, [{"name": "Muhammad Ali Khanzada"}], R)
    assert r["status"] in ("near_match", "no_match")
    strict = {**R, "name_match_auto_min": 0.99}
    assert match_name("Mohammad Aly", None, [{"name": "Muhammad Ali"}], strict)["action"] != "auto"


def test_empty_inputs():
    assert match_name("", None, PEOPLE, R)["action"] == "ask_more"
    assert match_name("Muhammad Ali", None, [], R)["status"] == "no_match"