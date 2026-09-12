from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from .core import utcnow


class ReportGenerationJob(Base):
    __tablename__ = "report_generation_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','ready','failed')", name="ck_generation_job_status"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="ck_generation_attempt_count"),
        CheckConstraint("lease_token >= 0", name="ck_generation_lease_token"),
        UniqueConstraint("report_id", name="uq_generation_job_report"),
        ForeignKeyConstraint(
            ["assessment_id", "owner_id"],
            ["assessment_sessions.id", "assessment_sessions.owner_id"],
            ondelete="CASCADE",
            name="fk_generation_job_assessment_owner",
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    source_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("report_versions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GenerationAttempt(Base):
    __tablename__ = "generation_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_number", name="uq_job_attempt"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("report_generation_jobs.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(ReportGenerationJob, "before_update")
def prevent_snapshot_replacement(_mapper, _connection, target: ReportGenerationJob) -> None:
    immutable = ("owner_id", "assessment_id", "input_hash", "source_versions", "input_snapshot", "profile_snapshot_id")
    state = inspect(target)
    if any(state.attrs[name].history.has_changes() for name in immutable):
        raise ValueError("generation job submission snapshot is immutable")
