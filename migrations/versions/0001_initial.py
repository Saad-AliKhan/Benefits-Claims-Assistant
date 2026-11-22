"""All tables of the merged app; seeds the 5 roles and rule version 1.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels = None
depends_on = None

ROLES = [
    ("citizen", "Citizen", "Starts and follows her own claim; sees and withdraws her permissions."),
    ("helper", "Helper", "Acts for a family only while that family allows it (Helper Mode)."),
    ("officer", "Officer", "Reviews claims the system sent to a person; approves or rejects."),
    ("admin", "Admin", "Changes the decision rules (new version each time), manages API keys."),
    ("auditor", "Auditor", "Reads everything, changes nothing: audit log, decision traces, evaluation."),
]
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    roles = op.create_table("roles", sa.Column("name", sa.String(20), primary_key=True),
                            sa.Column("label", sa.String(50), nullable=False),
                            sa.Column("description", sa.String(300), nullable=False))
    op.bulk_insert(roles, [{"name": n, "label": l, "description": d} for n, l, d in ROLES])

    op.create_table("users",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
                    sa.Column("full_name", sa.String(200), nullable=False),
                    sa.Column("cnic", sa.String(15), index=True),
                    sa.Column("role", sa.String(20), sa.ForeignKey("roles.name"), nullable=False),
                    sa.Column("password_hash", sa.String(255), nullable=False),
                    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
                    sa.Column("created_at", TS, nullable=False))
    op.create_table("consents",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("citizen_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
                    sa.Column("purpose", sa.String(40), nullable=False, index=True),
                    sa.Column("grantee", sa.String(20), nullable=False),
                    sa.Column("grantee_user_id", sa.Integer, sa.ForeignKey("users.id")),
                    sa.Column("status", sa.String(12), nullable=False, index=True),
                    sa.Column("granted_at", TS, nullable=False),
                    sa.Column("withdrawn_at", TS))
    op.create_table("cases",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("citizen_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
                    sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
                    sa.Column("benefit", sa.String(100), nullable=False),
                    sa.Column("amount", sa.Integer, nullable=False),
                    sa.Column("status", sa.String(20), nullable=False, index=True),
                    sa.Column("step", sa.String(20), nullable=False),
                    sa.Column("data", sa.JSON, nullable=False),
                    sa.Column("assigned_officer_id", sa.Integer, sa.ForeignKey("users.id")),
                    sa.Column("outcome", sa.String(10)),
                    sa.Column("confidence", sa.Float),
                    sa.Column("resolution_note", sa.String(500)),
                    sa.Column("payment_ref", sa.String(40)),
                    sa.Column("paid_at", TS),
                    sa.Column("created_at", TS, nullable=False),
                    sa.Column("updated_at", TS, nullable=False))
    op.create_table("audit_log",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("created_at", TS, nullable=False, index=True),
                    sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id")),
                    sa.Column("actor_role", sa.String(20), nullable=False),
                    sa.Column("action", sa.String(100), nullable=False, index=True),
                    sa.Column("case_id", sa.Integer, sa.ForeignKey("cases.id"), index=True),
                    sa.Column("details", sa.JSON, nullable=False))
    rv = op.create_table("rule_versions",
                         sa.Column("id", sa.Integer, primary_key=True),
                         sa.Column("version", sa.Integer, nullable=False, unique=True, index=True),
                         sa.Column("config", sa.JSON, nullable=False),
                         sa.Column("note", sa.String(300), nullable=False),
                         sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
                         sa.Column("created_at", TS, nullable=False))
    from datetime import datetime, timezone
    from app.rules import DEFAULT_RULES
    op.bulk_insert(rv, [{"version": 1, "config": DEFAULT_RULES, "note": "initial rules",
                         "created_at": datetime.now(timezone.utc)}])
    op.create_table("decisions",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("case_id", sa.Integer, sa.ForeignKey("cases.id"), nullable=False, index=True),
                    sa.Column("rule_version", sa.Integer, nullable=False, index=True),
                    sa.Column("outcome", sa.String(10), nullable=False),
                    sa.Column("confidence", sa.Float, nullable=False),
                    sa.Column("reason_user", sa.Text, nullable=False),
                    sa.Column("trace", sa.JSON, nullable=False),
                    sa.Column("idem_key", sa.String(64), index=True),
                    sa.Column("created_at", TS, nullable=False))
    op.create_table("documents",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("case_id", sa.Integer, sa.ForeignKey("cases.id"), nullable=False, index=True),
                    sa.Column("doc_type", sa.String(30), nullable=False),
                    sa.Column("file_ref", sa.String(300)),
                    sa.Column("source", sa.String(30), nullable=False),
                    sa.Column("outcome", sa.String(20), nullable=False),
                    sa.Column("action", sa.String(10), nullable=False),
                    sa.Column("ocr_json", sa.JSON, nullable=False),
                    sa.Column("ocr_version", sa.String(20)),
                    sa.Column("overall_confidence", sa.Float),
                    sa.Column("status", sa.String(20), nullable=False),
                    sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id")),
                    sa.Column("request_id", sa.String(64)),
                    sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id")),
                    sa.Column("created_at", TS, nullable=False))
    op.create_table("api_keys",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("name", sa.String(100), nullable=False),
                    sa.Column("prefix", sa.String(12), nullable=False),
                    sa.Column("key_hash", sa.String(64), nullable=False, unique=True, index=True),
                    sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("created_at", TS, nullable=False),
                    sa.Column("last_used_at", TS),
                    sa.Column("revoked_at", TS))
    op.create_table("mock_transfers",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("transfer_id", sa.String(30), nullable=False, unique=True),
                    sa.Column("cnic", sa.String(15), nullable=False, index=True),
                    sa.Column("amount", sa.Integer, nullable=False),
                    sa.Column("idempotency_key", sa.String(80), nullable=False, unique=True),
                    sa.Column("status", sa.String(20), nullable=False),
                    sa.Column("created_at", TS, nullable=False))


def downgrade() -> None:
    for t in ("mock_transfers", "api_keys", "documents", "decisions", "rule_versions", "audit_log", "cases",
              "consents", "users", "roles"):
        op.drop_table(t)
