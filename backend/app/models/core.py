from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ContentVersion(Base):
    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("kind", "revision", name="uq_content_kind_revision"),
        CheckConstraint("kind IN ('question','rule','prompt','job_template','knowledge_index')", name="ck_content_kind"),
        CheckConstraint("status IN ('draft','published','retired')", name="ck_content_status"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VersionPointer(Base):
    __tablename__ = "version_pointers"
    __table_args__ = (UniqueConstraint("kind", name="uq_current_pointer_kind"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_session_id_owner"),
        CheckConstraint("status IN ('draft','submitted','generating','completed')", name="ck_session_status"),
        CheckConstraint("revision >= 0", name="ck_session_revision"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_version_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"
    __table_args__ = (UniqueConstraint("session_id", "question_id", name="uq_answer_session_question"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_date: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("index_version_id", "chunk_key", name="uq_index_chunk"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    index_version_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_key: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# Public domain names backed by the typed generic version table.
QuestionVersion = ContentVersion
RuleVersion = ContentVersion
PromptTemplateVersion = ContentVersion
JobTemplateVersion = ContentVersion
KnowledgeIndexVersion = ContentVersion


@event.listens_for(ContentVersion, "before_update")
def prevent_published_version_update(_mapper, _connection, target: ContentVersion) -> None:
    state = inspect(target)
    old_status = state.attrs.status.history.deleted
    was_published = "published" in old_status
    if not old_status and target.status == "published":
        was_published = _connection.execute(
            ContentVersion.__table__.select()
            .with_only_columns(ContentVersion.__table__.c.status)
            .where(ContentVersion.__table__.c.id == target.id)
        ).scalar_one() == "published"
    if was_published and any(attribute.history.has_changes() for attribute in state.attrs if attribute.key != "published_at"):
        raise ValueError("published content versions are immutable")
