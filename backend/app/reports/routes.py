from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import require_owner
from app.contracts.report import Decisions, Interpretation, Job, Part, Report
from app.db.session import get_db
from app.models import FeedbackEvent, ReportGenerationJob, ReportVersion

router = APIRouter()


def _not_found() -> None:
    raise HTTPException(status_code=404, detail="not found")


def _versions(report: ReportVersion) -> dict:
    return {"questionVersion": report.question_version_id, "ruleVersion": report.rule_version_id,
            "jobTemplateVersion": report.job_template_version_id, "knowledgeIndexVersion": report.knowledge_index_version_id,
            "promptVersion": report.prompt_version_id, "modelName": report.model_name,
            "embeddingModelVersion": report.embedding_model_version, "profileSnapshotId": report.profile_snapshot_id}


def _part(data, model, *, report_status: str):
    if data is not None:
        model.model_validate(data)
        return {"status": "ready", "data": data, "errorCode": None}
    # A partial report is only published when at least one partition failed;
    # missing partitions therefore remain visibly failed for the UI to retry.
    status = "failed" if report_status in ("partial", "failed") else "pending"
    return {"status": status, "data": None, "errorCode": "REPORT_GENERATION_FAILED" if status == "failed" else None}


def _envelope(report: ReportVersion) -> dict:
    core = report.core
    decisions = report.decisions
    interpretation = report.interpretation
    if report.status == "ready" and not (core and decisions and interpretation):
        report_status = "partial"
    else:
        report_status = report.status
    payload = {
        "id": report.id, "assessmentId": report.assessment_id, "version": report.version,
        "demo": bool(report.demo), "status": report_status, "reviewStatus": report.review_status,
        "sourceVersions": _versions(report), "inputHash": report.input_hash,
        "createdAt": (report.created_at or datetime.now(timezone.utc)).isoformat(),
        "core": _part(core, __import__("app.contracts.report", fromlist=["Core"]).Core, report_status=report_status),
        "decisions": _part(decisions, Decisions, report_status=report_status),
        "interpretation": _part(interpretation, Interpretation, report_status=report_status),
        "tracking": {"status": "preview", "nodes": [{"day": 7, "label": "7天复盘"}, {"day": 30, "label": "30天行动"}, {"day": 90, "label": "90天复盘"}]},
    }
    return Report.model_validate(payload).model_dump(mode="json")


def _job_payload(job: ReportGenerationJob) -> dict:
    completed = []
    failed = []
    if job.report_id:
        # Completion is inferred from persisted report partitions.
        report = getattr(job, "_report_for_api", None)
        if report:
            completed = [k for k in ("core", "decisions", "interpretation") if getattr(report, k) is not None]
            failed = [k for k in ("core", "decisions", "interpretation") if getattr(report, k) is None and job.status == "failed"]
    stage = "complete" if job.status == "ready" else ("generate" if job.attempt_count else "validate")
    return Job.model_validate({"id": job.id, "status": job.status, "stage": stage, "reportId": job.report_id,
        "completedParts": completed, "failedParts": failed, "retryable": job.status == "failed" and job.attempt_count < 3,
        "attemptCount": job.attempt_count, "errorCode": job.error_code}).model_dump(mode="json")


@router.get("/reports/{report_id}")
def get_report(report_id: str, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    report = db.scalar(select(ReportVersion).where(ReportVersion.id == report_id, ReportVersion.owner_id == owner_id))
    if report is None: _not_found()
    return _envelope(report)


@router.get("/reports/{report_id}/parts/{part}")
def get_part(report_id: str, part: Literal["core", "decisions", "interpretation"], owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    report = db.scalar(select(ReportVersion).where(ReportVersion.id == report_id, ReportVersion.owner_id == owner_id))
    if report is None: _not_found()
    payload = _envelope(report)
    return payload[part]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    job = db.scalar(select(ReportGenerationJob).where(ReportGenerationJob.id == job_id, ReportGenerationJob.owner_id == owner_id))
    if job is None: _not_found()
    if job.report_id:
        job._report_for_api = db.get(ReportVersion, job.report_id)
    return _job_payload(job)


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "confirmed", "disputed"]
    comment: str | None = None


@router.post("/reports/{report_id}/review")
def review(report_id: str, payload: ReviewPayload, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    report = db.scalar(select(ReportVersion).where(ReportVersion.id == report_id, ReportVersion.owner_id == owner_id))
    if report is None: _not_found()
    if payload.status == "confirmed" and report.status != "ready":
        raise HTTPException(status_code=409, detail="report not ready")
    report.review_status = payload.status
    db.commit()
    return {"reviewStatus": report.review_status}


class FeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["accurate", "partly_accurate", "partial", "inaccurate"]
    clientEventId: str
    text: str | None = None


@router.post("/reports/{report_id}/feedback", status_code=201)
def submit_feedback(report_id: str, payload: FeedbackPayload, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    report = db.scalar(select(ReportVersion).where(ReportVersion.id == report_id, ReportVersion.owner_id == owner_id))
    if report is None: _not_found()
    existing = db.scalar(select(FeedbackEvent).where(FeedbackEvent.owner_id == owner_id, FeedbackEvent.client_event_id == payload.clientEventId))
    if existing is not None:
        return {"feedbackId": existing.id}
    item = FeedbackEvent(id=str(uuid.uuid4()), owner_id=owner_id, report_id=report_id, client_event_id=payload.clientEventId, rating=payload.rating, text=payload.text)
    db.add(item); db.commit()
    return {"feedbackId": item.id}


@router.get("/reports/{report_id}/feedback")
def list_feedback(report_id: str, owner_id: str = Depends(require_owner), db: Session = Depends(get_db), limit: int = Query(20, ge=1, le=100)):
    report = db.scalar(select(ReportVersion).where(ReportVersion.id == report_id, ReportVersion.owner_id == owner_id))
    if report is None: _not_found()
    items = db.scalars(select(FeedbackEvent).where(FeedbackEvent.owner_id == owner_id, FeedbackEvent.report_id == report_id).order_by(FeedbackEvent.id).limit(limit)).all()
    return {"items": [{"feedbackId": x.id, "rating": x.rating, "text": x.text, "clientEventId": x.client_event_id} for x in items], "nextCursor": None}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, owner_id: str = Depends(require_owner), db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    job = db.scalar(select(ReportGenerationJob).where(ReportGenerationJob.id == job_id, ReportGenerationJob.owner_id == owner_id))
    if job is None: _not_found()
    if job.status in ("ready", "queued", "running"):
        raise HTTPException(status_code=409, detail="job is not retryable")
    # A retry reuses the immutable submission hash/snapshot.  Repeated retry
    # requests while the clone is queued/running resolve to that same clone;
    # this provides idempotency without adding mutable fields to the frozen job.
    marker = db.scalar(select(ReportGenerationJob).where(
        ReportGenerationJob.owner_id == owner_id,
        ReportGenerationJob.assessment_id == job.assessment_id,
        ReportGenerationJob.input_hash == job.input_hash,
        ReportGenerationJob.status.in_(["queued", "running"]),
    ).order_by(ReportGenerationJob.created_at.desc()))
    if marker:
        return {"jobId": marker.id}
    retry = ReportGenerationJob(id=str(uuid.uuid4()), owner_id=job.owner_id, assessment_id=job.assessment_id,
        input_hash=job.input_hash, source_versions=dict(job.source_versions), input_snapshot=dict(job.input_snapshot),
        profile_snapshot_id=job.profile_snapshot_id, status="queued", attempt_count=0)
    db.add(retry); db.commit()
    return {"jobId": retry.id}

class ChatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clientMessageId: str
    content: str

@router.post("/reports/{report_id}/chat")
def chat(report_id: str, payload: ChatPayload, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    report = db.scalar(select(ReportVersion).where(ReportVersion.id == report_id, ReportVersion.owner_id == owner_id))
    if report is None: _not_found()
    session = db.scalar(select(__import__('app.models', fromlist=['ReportChatSession']).ReportChatSession).where(__import__('app.models', fromlist=['ReportChatSession']).ReportChatSession.owner_id == owner_id, __import__('app.models', fromlist=['ReportChatSession']).ReportChatSession.report_id == report_id))
    if session is None:
        session = __import__('app.models', fromlist=['ReportChatSession']).ReportChatSession(id=str(uuid.uuid4()), owner_id=owner_id, report_id=report_id); db.add(session); db.flush()
    msg_model = __import__('app.models', fromlist=['ReportChatMessage']).ReportChatMessage
    existing = db.scalar(select(msg_model).where(msg_model.session_id == session.id, msg_model.client_message_id == payload.clientMessageId))
    if existing: return {"id": existing.id, "role": existing.role, "content": existing.content.get('text','')}
    user = msg_model(id=str(uuid.uuid4()), session_id=session.id, client_message_id=payload.clientMessageId, role='user', content={'text': payload.content}); db.add(user)
    reply = msg_model(id=str(uuid.uuid4()), session_id=session.id, client_message_id=f"reply-{payload.clientMessageId}", role='assistant', content={'text': f'我已记录你的补充：“{payload.content}”。确认后可更新个人档案。'}); db.add(reply); db.commit()
    return {"id": reply.id, "role": "assistant", "content": reply.content['text']}

@router.get("/profile/history")
def profile_history(owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    Snapshot = __import__('app.models', fromlist=['ProfileSnapshot']).ProfileSnapshot
    items = db.scalars(select(Snapshot).where(Snapshot.owner_id == owner_id).order_by(Snapshot.created_at.desc())).all()
    return {"items": [{"id": x.id, "createdAt": x.created_at.isoformat(), "changeReason": x.change_reason, "confirmedFacts": [f.get('content', '') for f in x.confirmed_facts], "reportIds": x.report_ids} for x in items]}
