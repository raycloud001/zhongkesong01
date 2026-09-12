"""add owned authentication sessions and persisted login attempts

Revision ID: 3f0e2c1a9b74
Revises: 9d92db037fab
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3f0e2c1a9b74"
down_revision: Union[str, None] = "9d92db037fab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_login_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("client_key", sa.String(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_login_attempt_lookup",
        "admin_login_attempts",
        ["username", "client_key", "attempted_at"],
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("csrf_hash", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("admin_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(owner_id IS NOT NULL AND admin_id IS NULL) OR (owner_id IS NULL AND admin_id IS NOT NULL)",
            name="ck_auth_session_one_principal",
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_session_admin_id", "auth_sessions", ["admin_id"])
    op.create_index("ix_auth_session_owner_id", "auth_sessions", ["owner_id"])
    op.create_index("ix_auth_session_token_hash", "auth_sessions", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_table("admin_login_attempts")
