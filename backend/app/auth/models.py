from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.core import utcnow


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "(owner_id IS NOT NULL AND admin_id IS NULL) OR (owner_id IS NULL AND admin_id IS NOT NULL)",
            name="ck_auth_session_one_principal",
        ),
        Index("ix_auth_session_token_hash", "token_hash", unique=True),
        Index("ix_auth_session_owner_id", "owner_id"),
        Index("ix_auth_session_admin_id", "admin_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminLoginAttempt(Base):
    __tablename__ = "admin_login_attempts"
    __table_args__ = (Index("ix_admin_login_attempt_lookup", "username", "client_key", "attempted_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    client_key: Mapped[str] = mapped_column(String, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
