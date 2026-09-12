from copy import deepcopy
from datetime import datetime, timedelta, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.contracts.report import SourceVersions
from app.models.generation import ReportGenerationJob


class LeaseLostError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_job(db: Session, owner_id: str, snapshot: dict) -> str:
    frozen = deepcopy(snapshot)
    versions = SourceVersions.model_validate(frozen["sourceVersions"])
    from app.models import AssessmentSession
    assessment_owner = db.execute(
        select(AssessmentSession.owner_id).where(AssessmentSession.id == frozen["assessmentId"])
    ).scalar_one_or_none()
    if assessment_owner != owner_id:
        raise ValueError("job owner must own the assessment")
    job_id = str(uuid.uuid4())
    job = ReportGenerationJob(
        id=job_id,
        owner_id=owner_id,
        assessment_id=frozen["assessmentId"],
        input_hash=frozen["inputHash"],
        source_versions=versions.model_dump(mode="json"),
        input_snapshot=frozen,
        profile_snapshot_id=versions.profileSnapshotId,
        status="queued",
        available_at=_utcnow(),
    )
    db.add(job)
    db.flush()
    return job_id


def claim_next_job(db: Session, worker_id: str, lease_seconds: int = 60) -> ReportGenerationJob | None:
    now = _utcnow()
    exhausted = db.execute(
        update(ReportGenerationJob)
        .where(
            ReportGenerationJob.status == "running",
            ReportGenerationJob.attempt_count >= 3,
            ReportGenerationJob.lease_until < now,
        )
        .values(status="failed", error_code="MAX_ATTEMPTS_EXCEEDED", lease_owner=None, lease_until=None)
        .execution_options(synchronize_session=False)
    )
    candidate_id = db.execute(
        select(ReportGenerationJob.id)
        .where(
            ReportGenerationJob.attempt_count < 3,
            ReportGenerationJob.available_at <= now,
            or_(
                ReportGenerationJob.status == "queued",
                (ReportGenerationJob.status == "running") & (ReportGenerationJob.lease_until < now),
            ),
        )
        .order_by(ReportGenerationJob.available_at, ReportGenerationJob.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if candidate_id is None:
        if exhausted.rowcount:
            db.commit()
        return None
    result = db.execute(
        update(ReportGenerationJob)
        .where(
            ReportGenerationJob.id == candidate_id,
            or_(
                ReportGenerationJob.status == "queued",
                (ReportGenerationJob.status == "running") & (ReportGenerationJob.lease_until < now),
            ),
        )
        .values(
            status="running",
            lease_owner=worker_id,
            lease_until=now + timedelta(seconds=lease_seconds),
            lease_token=ReportGenerationJob.lease_token + 1,
            attempt_count=ReportGenerationJob.attempt_count + 1,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return db.get(ReportGenerationJob, candidate_id)


def complete_job(db: Session, job_id: str, worker_id: str, lease_token: int, report_id: str) -> None:
    from app.models import ReportVersion
    now = _utcnow()
    ownership = db.execute(
        select(ReportGenerationJob.owner_id, ReportGenerationJob.assessment_id).where(
            ReportGenerationJob.id == job_id,
            ReportGenerationJob.status == "running",
            ReportGenerationJob.lease_owner == worker_id,
            ReportGenerationJob.lease_token == lease_token,
            ReportGenerationJob.lease_until >= now,
        )
    ).one_or_none()
    if ownership is None:
        raise LeaseLostError("generation job lease no longer belongs to this worker")
    report_matches = ownership is not None and db.execute(
        select(ReportVersion.id).where(
            ReportVersion.id == report_id,
            ReportVersion.owner_id == ownership.owner_id,
            ReportVersion.assessment_id == ownership.assessment_id,
        )
    ).scalar_one_or_none()
    if report_matches is None:
        raise ValueError("report must belong to the generation job owner and assessment")
    result = db.execute(
        update(ReportGenerationJob)
        .where(
            ReportGenerationJob.id == job_id,
            ReportGenerationJob.status == "running",
            ReportGenerationJob.lease_owner == worker_id,
            ReportGenerationJob.lease_token == lease_token,
            ReportGenerationJob.lease_until >= now,
        )
        .values(status="ready", report_id=report_id, lease_owner=None, lease_until=None, error_code=None)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise LeaseLostError("generation job lease no longer belongs to this worker")
    db.flush()
