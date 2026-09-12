from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.core import utcnow


class AssessmentSubmission(Base):
    __tablename__ = "assessment_submissions"
    __table_args__ = (
        UniqueConstraint("owner_id", "session_id", "idempotency_key", name="uq_assessment_submit_key"),
        UniqueConstraint("session_id", name="uq_assessment_submit_session"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("report_generation_jobs.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssessmentEvent(Base):
    __tablename__ = "assessment_events"
    __table_args__ = (UniqueConstraint("owner_id", "client_event_id", name="uq_assessment_event_client"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
