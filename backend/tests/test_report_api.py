from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth.service import require_owner
from app.contracts.report import Report
from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import create_app
from app.models import AssessmentSession, FeedbackEvent, ReportGenerationJob, ReportVersion, User


def _versions():
    return {
        "questionVersion": "q-v1", "ruleVersion": "r-v1", "jobTemplateVersion": "j-v1",
        "knowledgeIndexVersion": "k-v1", "promptVersion": "p-v1", "modelName": "demo",
        "embeddingModelVersion": "emb-v1", "profileSnapshotId": None,
    }


def _core():
    claim = {"id": "c1", "text": "基于行为证据", "claimType": "fact", "references": []}
    return {"type": None, "keySummaries": {"state": claim, "advantage": claim, "risk": claim}, "radar": None,
            "evidence": [], "strengths": [], "weaknesses": [], "risk": None, "judgments": [claim]}


def _decisions():
    return {"jobMatches": [], "explicitTargets": [], "preferredDirection": None, "alternativeDirection": None,
            "actions": [], "actionPlan": [], "preparationSuggestions": [], "counterEvidenceConditions": []}


def _interpretation():
    return {"sections": [{"key": k, "claims": []} for k in ("core_judgment", "job_impact", "uncertainty", "validation")],
            "aiUsageNotice": "规则模板", "reviewItems": []}


@pytest.fixture()
def api(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(id="owner-1")); db.flush()
        db.add(AssessmentSession(id="assessment-1", owner_id="owner-1", question_version_id="q-v1", status="submitted"))
        db.add(ReportVersion(id="report-1", owner_id="owner-1", assessment_id="assessment-1", version=1, demo=True,
            status="ready", review_status="pending", input_hash="hash", question_version_id="q-v1", rule_version_id="r-v1",
            job_template_version_id="j-v1", knowledge_index_version_id="k-v1", prompt_version_id="p-v1",
            model_name="demo", embedding_model_version="emb-v1", core=_core(), decisions=_decisions(), interpretation=_interpretation()))
        db.flush()
        db.add(ReportGenerationJob(id="job-1", owner_id="owner-1", assessment_id="assessment-1", input_hash="hash",
            source_versions=_versions(), input_snapshot={"assessmentId": "assessment-1", "inputHash": "hash", "sourceVersions": _versions()},
            status="ready", attempt_count=1, report_id="report-1"))
        db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield from ())
    def override_db():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_owner] = lambda: "owner-1"
    client = TestClient(app)
    yield client, factory, engine
    engine.dispose()


def test_report_read_and_part_are_contract_valid(api):
    client, _, _ = api
    response = client.get("/api/v1/reports/report-1")
    assert response.status_code == 200
    Report.model_validate(response.json())
    assert client.get("/api/v1/reports/report-1/parts/core").json()["status"] == "ready"
    assert client.get("/api/v1/reports/report-1/parts/decisions").json()["data"] == _decisions()


def test_review_requires_ready_and_feedback_is_idempotent(api):
    client, factory, _ = api
    assert client.post("/api/v1/reports/report-1/review", json={"status": "confirmed"}).json() == {"reviewStatus": "confirmed"}
    payload = {"rating": "accurate", "clientEventId": "evt-1", "text": "ok"}
    first = client.post("/api/v1/reports/report-1/feedback", json=payload)
    second = client.post("/api/v1/reports/report-1/feedback", json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json() == second.json()
    with factory() as db:
        assert db.query(FeedbackEvent).count() == 1


def test_retry_failed_job_preserves_snapshot_and_ready_job_conflicts(api):
    client, factory, _ = api
    assert client.post("/api/v1/jobs/job-1/retry").status_code == 409
    with factory() as db:
        job = db.get(ReportGenerationJob, "job-1")
        job.status = "failed"; job.error_code = "PROVIDER_UNAVAILABLE"; db.commit()
    response = client.post("/api/v1/jobs/job-1/retry")
    assert response.status_code == 202
    retry_id = response.json()["jobId"]
    with factory() as db:
        retry = db.get(ReportGenerationJob, retry_id)
        assert retry.input_snapshot["sourceVersions"] == _versions()
        assert retry.status == "queued"


def test_owner_isolation_returns_404(api):
    client, _, _ = api
    client.app.dependency_overrides[require_owner] = lambda: "other-owner"
    assert client.get("/api/v1/reports/report-1").status_code == 404
