"""Live accounts: citizen sign-up by phone (one-time codes), staff temporary passwords, lockout, token version

Revision ID: 0003_live_accounts
Revises: 0002_agent_sms_phone
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_live_accounts"
down_revision = "0002_agent_sms_phone"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.alter_column("email", existing_type=sa.String(255), nullable=True)
        b.add_column(sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"))
        b.add_column(sa.Column("locked_until", TS))
        b.add_column(sa.Column("last_login_at", TS))
        b.add_column(sa.Column("token_version", sa.Integer, nullable=False, server_default="0"))
        b.create_index("ix_users_phone", ["phone"])
    op.create_table("one_time_codes",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("phone", sa.String(20), nullable=False, index=True),
                    sa.Column("purpose", sa.String(20), nullable=False),
                    sa.Column("code_hash", sa.String(255), nullable=False),
                    sa.Column("payload", sa.JSON, nullable=False),
                    sa.Column("attempts", sa.Integer, nullable=False),
                    sa.Column("used", sa.Boolean, nullable=False),
                    sa.Column("expires_at", TS, nullable=False),
                    sa.Column("created_at", TS, nullable=False))


def downgrade() -> None:
    op.drop_table("one_time_codes")
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_phone")
        for c in ("token_version", "last_login_at", "locked_until", "failed_logins", "must_change_password"):
            b.drop_column(c)
