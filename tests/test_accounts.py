"""Live accounts: citizen sign-up by mobile code + PIN, lockout, PIN reset, staff accounts made by an admin."""
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, SmsMessage, User


def signup(env, name="Amina Bibi", cnic="35202-1112223-4", phone="0301 2345678", pin="4826"):
    r = env.c.post("/auth/signup/start", json={"full_name": name, "cnic": cnic, "phone": phone})
    assert r.status_code == 200, r.text
    code = r.json()["code_on_screen"]
    r = env.c.post("/auth/signup/finish", json={"phone": phone, "code": code, "pin": pin})
    assert r.status_code == 201, r.text
    return r.json()


def test_citizen_signs_up_with_a_code_and_logs_in_with_mobile_and_pin(env):
    s = signup(env)
    assert s["user"]["role"] == "citizen" and s["user"]["phone"] == "0301-2345678" and s["user"]["home"] == "/assistant"
    me = env.c.get("/auth/me", headers={"Authorization": "Bearer " + s["access_token"]})
    assert me.status_code == 200 and me.json()["cnic"] == "35202-1112223-4"
    r = env.c.post("/auth/login/phone", json={"phone": "+92 301 2345678", "pin": "4826"})
    assert r.status_code == 200
    sms = env.db.scalar(select(SmsMessage).where(SmsMessage.kind == "code_signup"))
    assert "آسرا" in sms.text_ur
    for row in env.db.scalars(select(AuditLog)):        # the code and the PIN are never in the audit log
        assert "4826" not in str(row.details)


def test_signup_checks(env):
    bad = env.c.post("/auth/signup/start", json={"full_name": "Amina", "cnic": "123", "phone": "0301 2345678"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_cnic"
    bad = env.c.post("/auth/signup/start", json={"full_name": "Amina", "cnic": "35202-1112223-4", "phone": "042 123456"})
    assert bad.json()["detail"]["code"] == "bad_phone"
    signup(env)
    dup = env.c.post("/auth/signup/start", json={"full_name": "X Y", "cnic": "35202-1112223-4", "phone": "0333 1111111"})
    assert dup.status_code == 409
    r = env.c.post("/auth/signup/start", json={"full_name": "Zara Khan", "cnic": "35202-9998887-6", "phone": "0333 1111111"})
    weak = env.c.post("/auth/signup/finish", json={"phone": "0333 1111111", "code": r.json()["code_on_screen"], "pin": "1234"})
    assert weak.json()["detail"]["code"] == "weak_pin"
    for _ in range(5):
        env.c.post("/auth/signup/finish", json={"phone": "0333 1111111", "code": "000000", "pin": "4826"})
    late = env.c.post("/auth/signup/finish", json={"phone": "0333 1111111", "code": r.json()["code_on_screen"], "pin": "4826"})
    assert late.status_code == 422   # 5 wrong codes: that code is dead, ask for a new one


def test_five_wrong_pins_lock_the_account(env):
    signup(env)
    for _ in range(settings.max_failed_logins):
        assert env.c.post("/auth/login/phone", json={"phone": "03012345678", "pin": "9999"}).status_code == 401
    locked = env.c.post("/auth/login/phone", json={"phone": "03012345678", "pin": "4826"})
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "locked"


def test_pin_reset_logs_out_old_devices(env):
    old = signup(env)["access_token"]
    unknown = env.c.post("/auth/pin-reset/start", json={"phone": "0345 0000000"})
    assert unknown.status_code == 200 and "code_on_screen" not in unknown.json()   # does not reveal accounts
    code = env.c.post("/auth/pin-reset/start", json={"phone": "0301 2345678"}).json()["code_on_screen"]
    new = env.c.post("/auth/pin-reset/finish", json={"phone": "0301 2345678", "code": code, "pin": "7391"})
    assert new.status_code == 200
    assert env.c.get("/auth/me", headers={"Authorization": "Bearer " + old}).status_code == 401
    assert env.c.post("/auth/login/phone", json={"phone": "0301 2345678", "pin": "7391"}).status_code == 200


def test_admin_creates_staff_who_must_change_the_temporary_password(env):
    a = env.H(env.admin)
    r = env.c.post("/admin/users", headers=a, json={"full_name": "Hina Qureshi", "email": "Hina@Welfare.pk", "role": "officer"})
    assert r.status_code == 201, r.text
    temp = r.json()["temporary_password"]
    s = env.c.post("/auth/login", json={"email": "hina@welfare.pk", "password": temp}).json()
    assert s["user"]["must_change_password"] is True
    h = {"Authorization": "Bearer " + s["access_token"]}
    short = env.c.post("/auth/change-password", headers=h, json={"current": temp, "new": "short1"})
    assert short.status_code == 422
    ok = env.c.post("/auth/change-password", headers=h, json={"current": temp, "new": "queue-officer-2026"})
    assert ok.status_code == 200 and ok.json()["user"]["must_change_password"] is False
    assert env.c.get("/auth/me", headers=h).status_code == 401          # old token logged out
    assert env.c.post("/admin/users", headers=a, json={"full_name": "X", "email": "x@x.pk", "role": "citizen"}).status_code == 422
    assert env.c.post("/admin/users", headers=env.H(env.officer), json={"full_name": "Xyz", "email": "y@y.pk", "role": "officer"}).status_code == 403


def test_deactivate_and_last_admin_guard(env):
    a = env.H(env.admin)
    off = env.H(env.officer)
    assert env.c.get("/officer/queue", headers=off).status_code == 200
    r = env.c.post(f"/admin/users/{env.officer.id}/active", headers=a, json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    assert env.c.get("/officer/queue", headers=off).status_code == 401
    assert env.c.post(f"/admin/users/{env.admin.id}/active", headers=a, json={"active": False}).status_code == 422
    t = env.c.post(f"/admin/users/{env.auditor.id}/reset-password", headers=a).json()["temporary_password"]
    assert env.c.post("/auth/login", json={"email": "auditor@demo.pk", "password": t}).status_code == 200


def test_login_page_options(env):
    o = env.c.get("/auth/options").json()
    assert o["demo_mode"] is True and o["codes_on_screen"] is True
