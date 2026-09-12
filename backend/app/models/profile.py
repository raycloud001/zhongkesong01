from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from .core import utcnow


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_id: Mapped[str | None] = mapped_column(ForeignKey("profile_snapshots.id", ondelete="RESTRICT"), nullable=True)
    report_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confirmed_facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProfileReview(Base):
    __tablename__ = "profile_reviews"
    __table_args__ = (UniqueConstraint("report_id", "owner_id", name="uq_report_profile_review"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReportChatSession(Base):
    __tablename__ = "report_chat_sessions"
    __table_args__ = (UniqueConstraint("owner_id", "report_id", name="uq_owner_report_chat"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportChatMessage(Base):
    __tablename__ = "report_chat_messages"
    __table_args__ = (UniqueConstraint("session_id", "client_message_id", name="uq_chat_message_idempotency"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("report_chat_sessions.id", ondelete="CASCADE"), nullable=False)
    client_message_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationFact(Base):
    __tablename__ = "conversation_facts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_message_id: Mapped[str] = mapped_column(ForeignKey("report_chat_messages.id", ondelete="RESTRICT"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="candidate", nullable=False)
    target_profile_field: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactDecisionEvent(Base):
    __tablename__ = "fact_decision_events"
    __table_args__ = (UniqueConstraint("owner_id", "client_decision_id", name="uq_fact_decision_idempotency"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fact_id: Mapped[str] = mapped_column(ForeignKey("conversation_facts.id", ondelete="CASCADE"), nullable=False)
    client_decision_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    resulting_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("profile_snapshots.id"), nullable=True)


class ActionEvent(Base):
    __tablename__ = "action_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
