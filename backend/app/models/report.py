from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from .core import utcnow


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (
        UniqueConstraint("assessment_id", "version", name="uq_report_assessment_version"),
        ForeignKeyConstraint(
            ["assessment_id", "owner_id"],
            ["assessment_sessions.id", "assessment_sessions.owner_id"],
            ondelete="RESTRICT",
            name="fk_report_assessment_owner",
        ),
        CheckConstraint("version >= 1", name="ck_report_version"),
        CheckConstraint("status IN ('generating','partial','ready','failed')", name="ck_report_status"),
        CheckConstraint("review_status IN ('pending','confirmed','disputed')", name="ck_report_review_status"),
        CheckConstraint("NOT (review_status = 'confirmed' AND status != 'ready')", name="ck_confirm_only_ready_report"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    demo: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    review_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    question_version_id: Mapped[str] = mapped_column(String, nullable=False)
    rule_version_id: Mapped[str] = mapped_column(String, nullable=False)
    job_template_version_id: Mapped[str] = mapped_column(String, nullable=False)
    knowledge_index_version_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version_id: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String, nullable=False)
    profile_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    core: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    decisions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    interpretation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class JobMatch(Base):
    __tablename__ = "job_matches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False)
    job_template_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    match_status: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_sufficiency: Mapped[str | None] = mapped_column(String, nullable=True)
    tier: Mapped[str | None] = mapped_column(String, nullable=True)
    current_fit: Mapped[float | None] = mapped_column(nullable=True)
    potential_fit: Mapped[float | None] = mapped_column(nullable=True)
    current_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    potential_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    tasks: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    gaps: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    risks: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    validation_task: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    industry_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    contract_version: Mapped[str | None] = mapped_column(String, nullable=True)
    structured_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ActionItem(Base):
    __tablename__ = "action_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=0)


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"
    __table_args__ = (UniqueConstraint("owner_id", "client_event_id", name="uq_feedback_idempotency"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[str] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
