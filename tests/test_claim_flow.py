"""Steps 2-4 through the API: the step-by-step claim, the three zones, handoff with notes, payment,
officer decisions, consent withdrawal that really blocks, versioned rules, Helper Mode."""
import io
import json

import pytest
from PIL import Image
from sqlalchemy import select

from app import ai_engines
from app.consent import CLAIM_PURPOSES
from app.models import AuditLog, Decision, MockTransfer
from tools import claim_runner


def jpg():
    b = io.BytesIO()
    Image.new("RGB", (900, 600), (235, 240, 230)).save(b, "JPEG")
    return b.getvalue()


def claim(env, sid, consent=CLAIM_PURPOSES, photo=None, cert=None, message=None, decide=True):
    """Do a scenario's claim through the HTTP API, as the citizen's phone would."""
    s = env.scenario(sid)
    u = claim_runner.claimant(env.db, s)
    h = env.H(u)
    cid = env.c.post("/claims", headers=h).json()["case_id"]
    r = env.c.post(f"/claims/{cid}/consent", headers=h, json={"purposes": list(consent)})
    assert r.status_code == 200, r.text
    files = {"photo": ("cnic.jpg", photo, "image/jpeg")} if photo else None
    r = env.c.post(f"/claims/{cid}/identity", headers=h, data={"cnic": s["claimant"]["cnic"]}, files=files)
    assert r.status_code == 200, r.text
    files = {"certificate": ("cert.jpg", cert, "image/jpeg")} if cert else None
    r = env.c.post(f"/claims/{cid}/eligibility", headers=h, data={"deceased_cnic": s["deceased_cnic"], "relation": s["relation"]},
                   files=files)
    assert r.status_code == 200, r.text
    if decide:
        r = env.c.post(f"/claims/{cid}/decide", headers=h, json={"message": message or s.get("message")})
        assert r.status_code == 200, r.text
    return u, cid, r.json()


def test_widow_completes_a_claim_with_plain_buttons_and_is_paid(env):
    u, cid, view = claim(env, "S01")
    assert view["status"] == "paid" and view["decision"]["outcome"] == "green" and view["payment_ref"].startswith("MOCKPAY-")
    assert view["decision"]["reason_ur"]  # a simple reason in Urdu too
    assert env.db.scalar(select(MockTransfer)).amount == 25000
    # progress was saved after each step
    steps = [a.details.get("step") for a in env.db.scalars(select(AuditLog).where(AuditLog.action == "claim.step_done"))]
    assert steps == ["consent", "identity", "eligibility"]


@pytest.mark.parametrize("sid", ["S02", "S06", "S07", "S08", "S09", "S10", "S11", "S12", "S14", "S15", "S16", "S17",
                                 "S18", "S19", "S20", "S21", "S22"])
def test_same_flow_three_zones_depending_on_the_data(env, sid):
    _, _, view = claim(env, sid)
    assert view["decision"]["outcome"] == env.scenario(sid)["expected"]


def test_red_goes_to_an_officer_with_notes_then_approve_pays(env):
    u, cid, view = claim(env, "S12")  # amount above the automatic limit
    assert view["status"] == "escalated"
    q = env.c.get("/officer/queue", headers=env.H(env.officer)).json()["items"]
    assert [i["case_id"] for i in q] == [cid]
    d = env.c.get(f"/officer/cases/{cid}", headers=env.H(env.officer)).json()
    assert "Please check" in d["notes"][0]["note"] and "amount" in d["notes"][0]["note"]
    assert d["decision"]["trace"]["checks"]  # the full trace
    assert env.c.post(f"/officer/cases/{cid}/decision", headers=env.H(env.officer), json={"approve": True}).status_code == 409
    assert env.c.post(f"/officer/cases/{cid}/assign", headers=env.H(env.officer)).status_code == 200
    r = env.c.post(f"/officer/cases/{cid}/decision", headers=env.H(env.officer), json={"approve": True, "note": "checked the children"})
    assert r.json()["status"] == "paid"
    assert env.c.get(f"/claims/{cid}", headers=env.H(u)).json()["status"] == "paid"


def test_reject_needs_a_note(env):
    _, cid, _ = claim(env, "S16")
    env.c.post(f"/officer/cases/{cid}/assign", headers=env.H(env.officer))
    assert env.c.post(f"/officer/cases/{cid}/decision", headers=env.H(env.officer), json={"approve": False}).status_code == 422
    r = env.c.post(f"/officer/cases/{cid}/decision", headers=env.H(env.officer),
                   json={"approve": False, "note": "applicant on the record is the son"})
    assert r.json()["status"] == "rejected"


def test_blocked_bank_account_goes_to_a_person(env):
    _, cid, view = claim(env, "S13")
    assert view["decision"]["outcome"] == "green" and view["status"] == "payment_failed"
    assert any(i["case_id"] == cid for i in env.c.get("/officer/queue", headers=env.H(env.officer)).json()["items"])


def test_ask_for_proof_then_the_cnic_photo_resolves_it(env, monkeypatch):
    u, cid, view = claim(env, "S09")
    assert view["status"] == "waiting_citizen" and "id_incomplete" in view["decision"]["asks_for"]
    fixture = json.loads(json.dumps(ai_engines._fixture("cnic", "clean")))
    fixture["fields"]["cnic"]["value"] = env.scenario("S09")["claimant"]["cnic"]
    fixture["fields"]["name"]["value"] = "Saima Rashid"
    monkeypatch.setattr(ai_engines, "_fixture", lambda doc_type, scenario: fixture)
    h = env.H(u)
    r = env.c.post(f"/claims/{cid}/identity", headers=h, files={"photo": ("cnic.jpg", jpg(), "image/jpeg")})
    assert r.json()["identity_ok"] == "auto"
    r = env.c.post(f"/claims/{cid}/decide", headers=h, json={})
    assert r.json()["status"] == "paid"
    assert len(env.db.scalars(select(Decision).where(Decision.case_id == cid)).all()) == 2


def test_second_claim_for_the_same_death_goes_to_a_person(env):
    claim(env, "S01")
    _, _, view = claim(env, "S23")
    assert view["decision"]["outcome"] == "red"


def test_withdrawing_consent_really_blocks(env):
    s = env.scenario("S01")
    u = claim_runner.claimant(env.db, s)
    h = env.H(u)
    cid = env.c.post("/claims", headers=h).json()["case_id"]
    env.c.post(f"/claims/{cid}/consent", headers=h, json={"purposes": list(CLAIM_PURPOSES)})
    ident = next(c for c in env.c.get("/consents", headers=h).json()["records"] if c["purpose"] == "identity_check")
    assert env.c.post(f"/consents/{ident['id']}/withdraw", headers=h).json()["status"] == "withdrawn"
    r = env.c.post(f"/claims/{cid}/identity", headers=h, data={"cnic": s["claimant"]["cnic"]})
    assert r.status_code == 403
    assert env.c.post("/consents", headers=h, json={"purpose": "identity_check"}).status_code == 201  # change: allow again
    assert env.c.post(f"/claims/{cid}/identity", headers=h, data={"cnic": s["claimant"]["cnic"]}).status_code == 200


def test_withdrawing_case_share_hides_the_claim_from_officers(env):
    u, cid, _ = claim(env, "S12")
    h = env.H(u)
    assert env.c.get(f"/officer/cases/{cid}", headers=env.H(env.officer)).status_code == 200
    share = next(c for c in env.c.get("/consents", headers=h).json()["records"] if c["purpose"] == "case_share")
    env.c.post(f"/consents/{share['id']}/withdraw", headers=h)
    assert env.c.get(f"/officer/cases/{cid}", headers=env.H(env.officer)).status_code == 403
    assert env.c.get("/officer/queue", headers=env.H(env.officer)).json()["items"] == []
    assert env.c.get(f"/audit/cases/{cid}", headers=env.H(env.auditor)).status_code == 200  # the auditor still sees it


def test_no_payment_permission_means_no_payment(env):
    _, cid, view = claim(env, "S02", consent=("identity_check", "records_check", "case_share"))
    assert view["status"] == "approved" and view["payment_ref"] is None


def test_rule_change_is_used_by_the_next_decision_with_its_version(env):
    r = env.c.post("/admin/rules", headers=env.H(env.admin), json={"changes": {"max_auto_amount": 20000}, "note": "test"})
    assert r.json()["version"] == 2
    _, cid, view = claim(env, "S01")  # 25,000 is now above the limit
    assert view["decision"]["outcome"] == "red"
    d = env.c.get(f"/officer/cases/{cid}", headers=env.H(env.officer)).json()["decision"]
    assert d["rule_version"] == 2
    assert env.c.post("/admin/rules", headers=env.H(env.admin),
                      json={"changes": {"auto_approve_min_confidence": 0.5, "human_review_below_confidence": 0.6}}).status_code == 422
    assert env.c.post("/admin/rules/rollback/1", headers=env.H(env.admin)).json()["version"] == 3


def test_helper_mode_only_while_the_family_allows_it(env):
    helper = env.user("helper@demo.pk", "helper")
    s = env.scenario("S01")
    u = claim_runner.claimant(env.db, s)
    assert env.c.get("/claims", headers=env.H(helper, acting=u.id)).status_code == 403
    c = env.c.post("/consents", headers=env.H(u), json={"purpose": "helper_access", "helper_email": "helper@demo.pk"}).json()
    assert [f["name"] for f in env.c.get("/helper/families", headers=env.H(helper)).json()] == [u.full_name]
    cid = env.c.post("/claims", headers=env.H(helper, acting=u.id)).json()["case_id"]
    assert env.c.get(f"/claims/{cid}", headers=env.H(helper, acting=u.id)).status_code == 200
    env.c.post(f"/consents/{c['id']}/withdraw", headers=env.H(u))
    assert env.c.get(f"/claims/{cid}", headers=env.H(helper, acting=u.id)).status_code == 403


def test_a_citizen_cannot_see_another_citizens_claim(env):
    _, cid, _ = claim(env, "S01")
    other = claim_runner.claimant(env.db, env.scenario("S02"))
    assert env.c.get(f"/claims/{cid}", headers=env.H(other)).status_code == 404


def test_voice_and_scam(env):
    u = claim_runner.claimant(env.db, env.scenario("S01"))
    r = env.c.post("/voice/understand", headers=env.H(u), files={"audio": ("q.webm", b"x" * 300, "audio/webm")})
    assert r.status_code == 200 and r.json()["action"] == "lookup_payment"
    r = env.c.post("/voice/intent", headers=env.H(u), json={"text": "میں افسر سے بات کرنا چاہتی ہوں"})
    assert r.json()["action"] == "handoff_to_officer"
    log = env.db.scalars(select(AuditLog).where(AuditLog.action == "ai.voice_intent")).all()
    assert len(log) == 2 and "افسر" not in json.dumps([a.details for a in log], ensure_ascii=False)
    r = env.c.post("/ai/scam-check", headers=env.H(u), json={"text": env.scenario("S14")["message"]})
    assert r.json()["label"] == "scam" and 0 <= r.json()["scam_probability"] <= 1


def test_public_api_needs_a_key(env):
    assert env.c.get("/api/v1/ping").status_code == 401
    k = env.c.post("/admin/api-keys", headers=env.H(env.admin), json={"name": "partner bank"}).json()
    hk = {"X-API-Key": k["api_key"]}
    assert env.c.get("/api/v1/ping", headers=hk).status_code == 200
    claim(env, "S01")
    assert env.c.get("/api/v1/stats", headers=hk).json()["claims_by_status"] == {"paid": 1}
    env.c.post(f"/admin/api-keys/{k['id']}/revoke", headers=env.H(env.admin))
    assert env.c.get("/api/v1/ping", headers=hk).status_code == 401


def test_mock_apis_need_staff(env):
    u = claim_runner.claimant(env.db, env.scenario("S01"))
    assert env.c.get("/mock/identity/35202-1234567-1", headers=env.H(u)).status_code == 403
    r = env.c.get("/mock/identity/35202-1234567-1", headers=env.H(env.officer)).json()
    assert r["life_status"] == "deceased" and "_truth_id" not in r
    assert len(env.c.get("/mock/identity?name=Ayesha Khan", headers=env.H(env.officer)).json()["results"]) == 2
    assert env.c.get("/mock/records/death/35202-1234567-1", headers=env.H(env.auditor)).json()["applicant_relation"] == "Wife"


def test_whisper_not_available_lets_the_person_type(env, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "voice_mock", False)
    monkeypatch.setitem(ai_engines._state, "voice_ready", False)
    monkeypatch.setitem(ai_engines._state, "voice_error", "no internet for the first download")
    u = claim_runner.claimant(env.db, env.scenario("S01"))
    r = env.c.post("/voice/understand", headers=env.H(u), files={"audio": ("q.webm", b"x" * 300, "audio/webm")})
    assert r.status_code == 503 and r.json()["detail"]["message_ur"]
    assert env.c.post("/voice/intent", headers=env.H(u), json={"text": "میری درخواست کا کیا بنا"}).json()["action"] == "lookup_claim_status"
    assert env.c.get("/health/ai").json()["voice"]["error"]
