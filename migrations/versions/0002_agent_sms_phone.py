"""Conversation agent sessions, mock SMS outbox, users.phone

Revision ID: 0002_agent_sms_phone
Revises: 0001_initial
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_agent_sms_phone"
down_revision = "0001_initial"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("phone", sa.String(20)))
    op.create_table("sms_messages",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), index=True),
                    sa.Column("case_id", sa.Integer, sa.ForeignKey("cases.id")),
                    sa.Column("phone", sa.String(20)),
                    sa.Column("kind", sa.String(30), nullable=False),
                    sa.Column("text_ur", sa.Text, nullable=False),
                    sa.Column("text_en", sa.Text, nullable=False),
                    sa.Column("status", sa.String(20), nullable=False),
                    sa.Column("created_at", TS, nullable=False))
    op.create_table("agent_sessions",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
                    sa.Column("citizen_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
                    sa.Column("channel", sa.String(20), nullable=False),
                    sa.Column("lang", sa.String(5)),
                    sa.Column("state", sa.String(30), nullable=False),
                    sa.Column("tries", sa.Integer, nullable=False),
                    sa.Column("data", sa.JSON, nullable=False),
                    sa.Column("last_turn", sa.JSON, nullable=False),
                    sa.Column("ended", sa.Boolean, nullable=False),
                    sa.Column("created_at", TS, nullable=False),
                    sa.Column("updated_at", TS, nullable=False))


def downgrade() -> None:
    op.drop_table("agent_sessions")
    op.drop_table("sms_messages")
    with op.batch_alter_table("users") as b:
        b.drop_column("phone")
