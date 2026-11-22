"""Step 1: JWT login, 5 roles, server-side role checks, audit log of every action."""
import pytest
from sqlalchemy import select

from app.models import AuditLog


def test_login_with_jwt_and_each_role_lands_on_its_own_page(env):
    for email, role, home in [("rukhsana@demo.pk", "citizen", "/assistant"), ("officer@demo.pk", "officer", "/officer"),
                              ("auditor@demo.pk", "auditor", "/auditor"), ("admin@demo.pk", "admin", "/admin")]:
        env.user(email, role)
        r = env.c.post("/auth/login", json={"email": email, "password": "demo1234"})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["home"] == home
        token = r.json()["access_token"]
        assert env.c.get("/auth/me", headers={"Authorization": "Bearer " + token}).json()["role"] == role
    assert env.c.post("/auth/login", json={"email": "officer@demo.pk", "password": "wrong"}).status_code == 401
    assert env.c.get("/auth/me").status_code == 401
    assert env.c.get("/auth/me", headers={"Authorization": "Bearer forged.token.here"}).status_code == 401


def test_each_role_sees_different_things(env):
    citizen = env.user("c@t.pk", "citizen")
    cases = {  # path -> roles allowed
        ("GET", "/claims"): {"citizen"},
        ("GET", "/officer/queue"): {"officer", "admin"},
        ("GET", "/audit/log"): {"auditor", "admin"},
        ("POST", "/admin/rules"): {"admin"},
        ("GET", "/admin/api-keys"): {"admin"},
    }
    who = {"citizen": citizen, "officer": env.officer, "admin": env.admin, "auditor": env.auditor}
    for (method, path), allowed in cases.items():
        for role, u in who.items():
            r = env.c.request(method, path, headers=env.H(u), json={"changes": {"max_auto_amount": 40000}})
            assert (r.status_code != 403) == (role in allowed), (method, path, role, r.status_code)


def test_audit_log_records_every_action_and_refusal(env):
    citizen = env.user("c@t.pk", "citizen")
    env.c.post("/auth/login", json={"email": "c@t.pk", "password": "demo1234"})
    env.c.post("/auth/login", json={"email": "c@t.pk", "password": "nope"})
    env.c.get("/officer/queue", headers=env.H(citizen))                 # refused
    env.c.post("/claims", headers=env.H(citizen))                       # a change
    actions = [a.action for a in env.db.scalars(select(AuditLog))]
    for a in ("auth.login", "auth.login_failed", "access.denied", "http.refused", "claim.created", "http.request"):
        assert a in actions, a
    assert all("password" not in str(a.details).lower() or "[hidden]" in str(a.details) for a in env.db.scalars(select(AuditLog)))


def test_audit_rows_can_never_be_changed_or_deleted(env):
    env.user("c@t.pk", "citizen")
    env.c.post("/auth/login", json={"email": "c@t.pk", "password": "demo1234"})
    row = env.db.scalars(select(AuditLog)).first()
    row.action = "tampered"
    with pytest.raises(RuntimeError):
        env.db.commit()
    env.db.rollback()
    with pytest.raises(RuntimeError):
        env.db.delete(env.db.scalars(select(AuditLog)).first())
        env.db.commit()
    env.db.rollback()
