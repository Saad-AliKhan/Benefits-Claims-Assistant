"""Database tables. Changes go through alembic migrations (migrations/versions)."""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        event)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    """The 5 roles. Permissions are enforced in code (deps.require_role); this table names and explains them."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)  # citizen helper officer admin auditor
    label: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(300))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    cnic: Mapped[str | None] = mapped_column(String(15), index=True)  # fake numbers only
    phone: Mapped[str | None] = mapped_column(String(20))  # where SMS updates go (mock)
    role: Mapped[str] = mapped_column(String(20), ForeignKey("roles.name"))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Consent(Base):
    """One permission a citizen gave, for one purpose (see app/consent.py PURPOSES).
    Withdrawing sets status='withdrawn' and withdrawn_at; the row is kept as a record."""

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    citizen_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    grantee: Mapped[str] = mapped_column(String(20))  # platform | officer | helper
    grantee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # the helper, for helper_access
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active | withdrawn
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Case(Base):
    """One claim. `step` is where the citizen is in the claim flow (progress is saved after every step);
    `status` is where the claim is in its life (see app/claims.py)."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    citizen_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    benefit: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    step: Mapped[str] = mapped_column(String(20), default="consent")
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # what each step found (inputs and checks)
    assigned_officer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    outcome: Mapped[str | None] = mapped_column(String(10))       # latest decision: green | yellow | red
    confidence: Mapped[float | None] = mapped_column(Float)
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    payment_ref: Mapped[str | None] = mapped_column(String(40))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """Append-only: the ORM refuses to change or delete a saved row (see the listeners below)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(100), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _audit_is_append_only(mapper, connection, target):
    raise RuntimeError("audit_log rows can never be changed or deleted")


class RuleVersion(Base):
    """Append-only. Every admin change creates a NEW row; the active rules are the highest version."""

    __tablename__ = "rule_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    config: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Decision(Base):
    """One decision-engine run on a claim, with the rule version it used and the full trace."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer, index=True)
    outcome: Mapped[str] = mapped_column(String(10))  # green | yellow | red
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason_user: Mapped[str] = mapped_column(Text, default="")  # simple sentence for the citizen
    trace: Mapped[dict] = mapped_column(JSON, default=dict)     # full trace for the officer and auditor
    idem_key: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    """One uploaded document photo and what the OCR engine (or the fallback reader) made of it.
    The photo is in settings.upload_dir; `ocr_json` is the checked result, never the raw OCR text."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(30))  # cnic | death_certificate
    file_ref: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(30))    # ocr_engine | local_tesseract | none
    outcome: Mapped[str] = mapped_column(String(20))   # ok | retake | unavailable
    action: Mapped[str] = mapped_column(String(10))    # auto | ask_more | human
    ocr_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ocr_version: Mapped[str | None] = mapped_column(String(20))
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | retake | confirmed | corrected
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    """Keys for the public API (/api/v1). Only a hash is stored; the key is shown once, at creation."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MockTransfer(Base):
    """The mock payment service's ledger (pretends to be a bank / Raast). No real money moves."""

    __tablename__ = "mock_transfers"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[str] = mapped_column(String(30), unique=True)
    cnic: Mapped[str] = mapped_column(String(15), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SmsMessage(Base):
    """The mock SMS gateway's outbox: every text the system 'sent' to a citizen (or helper)."""

    __tablename__ = "sms_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"))
    phone: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(30))
    text_ur: Mapped[str] = mapped_column(Text)
    text_en: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent_mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentSession(Base):
    """One conversation with the assistant (web voice screen now, WhatsApp later). The state is saved after
    every turn, so a dropped signal resumes at the same step."""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)       # who is talking
    citizen_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)    # whose claim (helper mode)
    channel: Mapped[str] = mapped_column(String(20), default="web")
    lang: Mapped[str | None] = mapped_column(String(5))
    state: Mapped[str] = mapped_column(String(30), default="lang")
    tries: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    last_turn: Mapped[dict] = mapped_column(JSON, default=dict)
    ended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
