"""Shared test setup: a throw-away in-memory database with the roles and rule version 1, the fake
people from data/, mock OCR/voice (no models), and helpers to log in as any role."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.mock_services import store
from app.models import Role, RuleVersion
from app.rules import DEFAULT_RULES
from app.security import create_access_token
from tools import claim_runner


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ocr_mock", True)
    monkeypatch.setattr(settings, "voice_mock", True)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    for r in ("citizen", "helper", "officer", "admin", "auditor"):
        db.add(Role(name=r, label=r, description=r))
    db.add(RuleVersion(version=1, config=dict(DEFAULT_RULES), note="test"))
    db.commit()
    store.reload()

    def override():
        yield db
    app.dependency_overrides[get_db] = override
    client = TestClient(app)

    class Env:
        pass
    e = Env()
    e.db, e.c = db, client
    e.user = lambda email, role="citizen", name=None, cnic=None: claim_runner.ensure_user(db, email, name or email, role, cnic)
    e.H = lambda u, acting=None: {"Authorization": "Bearer " + create_access_token(u.id, u.role, u.token_version or 0),
                                  **({"X-Acting-For": str(acting)} if acting else {})}
    e.scenario = lambda sid: next(s for s in claim_runner.scenarios() if s["id"] == sid)
    e.officer = e.user("officer@demo.pk", "officer")
    e.admin = e.user("admin@demo.pk", "admin")
    e.auditor = e.user("auditor@demo.pk", "auditor")
    yield e
    app.dependency_overrides.clear()
