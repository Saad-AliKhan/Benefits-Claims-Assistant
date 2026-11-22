"""Volunteer voice recordings for testing: consent required, no names, saved with the situation."""
import json

from app.routers import collect
from tools import claim_runner


def test_recordings_need_consent_and_are_saved_with_their_situation(env, monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "DIR", tmp_path)
    u = claim_runner.claimant(env.db, env.scenario("S01"))
    h = env.H(u)
    sits = env.c.get("/voice/collect/situations", headers=h).json()
    assert len(sits) >= 35 and {"_yes", "_no", "payment_status"} <= {s["id"] for s in sits}
    audio = {"audio": ("rec.webm", b"\x1a\x45\xdf\xa3" + b"x" * 500, "audio/webm")}
    r = env.c.post("/voice/collect", headers=h, files=audio,
                   data={"situation": "payment_status", "speaker": "v01", "consent": "false"})
    assert r.status_code == 422
    r = env.c.post("/voice/collect", headers=h, files=audio,
                   data={"situation": "payment_status", "speaker": "Fatima Bibi!", "consent": "true", "gender": "F"})
    assert r.status_code == 200 and r.json()["saved"].startswith("FatimaBibi/")
    row = json.loads((tmp_path / "index.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["situation"] == "payment_status" and (tmp_path / row["file"]).is_file()
    assert env.c.post("/voice/collect", files=audio, data={"situation": "x", "speaker": "v", "consent": "true"}).status_code == 401
