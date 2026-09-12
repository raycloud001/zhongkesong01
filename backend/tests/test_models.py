from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.jobs.store import LeaseLostError, claim_next_job, complete_job, enqueue_job
from app.models import (
    AssessmentAnswer,
    AssessmentSession,
    ContentVersion,
    ReportGenerationJob,
    ReportVersion,
    User,
    VersionPointer,
)


@pytest.fixture()
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_owner_and_session(db: Session):
    owner = User(id="owner-1")
    db.add(owner)
    db.flush()
    assessment = AssessmentSession(
        id="assessment-1", owner_id=owner.id, question_version_id="questions-v1"
    )
    db.add(assessment)
    db.commit()
    return owner, assessment


def snapshot():
    return {
        "assessmentId": "assessment-1",
        "inputHash": "hash-1",
        "sourceVersions": {
            "questionVersion": "questions-v1",
            "ruleVersion": "rules-v1",
            "jobTemplateVersion": "jobs-v1",
            "knowledgeIndexVersion": "knowledge-v1",
            "promptVersion": "prompt-v1",
            "modelName": "model-v1",
            "embeddingModelVersion": "embedding-v1",
            "profileSnapshotId": None,
        },
        "answers": [{"questionId": "q-1", "value": "demo"}],
        "profileSnapshotId": None,
    }


def test_sqlite_foreign_keys_are_enabled(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'foreign-keys.db'}")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_one_answer_per_session_question(db):
    add_owner_and_session(db)
    db.add_all(
        [
            AssessmentAnswer(id="a-1", session_id="assessment-1", question_id="q-1", value={"value": 1}),
            AssessmentAnswer(id="a-2", session_id="assessment-1", question_id="q-1", value={"value": 2}),
        ]
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_only_one_current_pointer_per_content_kind(db):
    db.add_all([
        ContentVersion(id="v1", kind="question", revision="1", payload={}, status="published"),
        ContentVersion(id="v2", kind="question", revision="2", payload={}, status="published"),
    ])
    db.flush()
    db.add_all(
        [
            VersionPointer(id="ptr-1", kind="question", version_id="v1"),
            VersionPointer(id="ptr-2", kind="question", version_id="v2"),
        ]
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_historical_report_keeps_versions_when_pointer_changes(db):
    owner, assessment = add_owner_and_session(db)
    for identifier in ("rules-v1", "rules-v2"):
        db.add(ContentVersion(id=identifier, kind="rule", revision=identifier[-1], payload={"demo": True}, status="published"))
    db.add(VersionPointer(id="rule-current", kind="rule", version_id="rules-v1"))
    report = ReportVersion(
        id="report-1",
        owner_id=owner.id,
        assessment_id=assessment.id,
        version=1,
        status="ready",
        review_status="pending",
        input_hash="hash",
        question_version_id="questions-v1",
        rule_version_id="rules-v1",
        job_template_version_id="jobs-v1",
        knowledge_index_version_id="knowledge-v1",
        prompt_version_id="prompt-v1",
        model_name="model-v1",
        embedding_model_version="embedding-v1",
    )
    db.add(report)
    db.commit()
    pointer = db.get(VersionPointer, "rule-current")
    pointer.version_id = "rules-v2"
    db.commit()
    db.refresh(report)
    assert report.rule_version_id == "rules-v1"


def test_enqueue_snapshot_is_immutable_and_claim_is_atomic(db):
    add_owner_and_session(db)
    payload = snapshot()
    job_id = enqueue_job(db, "owner-1", payload)
    payload["answers"][0]["value"] = "changed"
    job = db.get(ReportGenerationJob, job_id)
    assert job.input_snapshot["answers"][0]["value"] == "demo"
    claimed = claim_next_job(db, "worker-a", lease_seconds=30)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.attempt_count == 1
    assert claimed.lease_token == 1
    assert claim_next_job(db, "worker-b", lease_seconds=30) is None


def test_expired_worker_cannot_complete_released_job(db):
    add_owner_and_session(db)
    job_id = enqueue_job(db, "owner-1", snapshot())
    first = claim_next_job(db, "worker-a", lease_seconds=30)
    token = first.lease_token
    first.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    second = claim_next_job(db, "worker-b", lease_seconds=30)
    assert second.lease_token == token + 1
    with pytest.raises(LeaseLostError):
        complete_job(db, job_id, "worker-a", token, "report-stale")


def test_expired_worker_cannot_complete_before_job_is_reclaimed(db):
    add_owner_and_session(db)
    job_id = enqueue_job(db, "owner-1", snapshot())
    claimed = claim_next_job(db, "worker-a", lease_seconds=30)
    claimed.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    with pytest.raises(LeaseLostError):
        complete_job(db, job_id, "worker-a", claimed.lease_token, "report-stale")


def test_complete_job_sets_report_and_ready_together(db):
    owner, assessment = add_owner_and_session(db)
    job_id = enqueue_job(db, owner.id, snapshot())
    claimed = claim_next_job(db, "worker-a", lease_seconds=30)
    report = ReportVersion(
        id="report-1",
        owner_id=owner.id,
        assessment_id=assessment.id,
        version=1,
        status="ready",
        review_status="pending",
        input_hash="hash-1",
        question_version_id="questions-v1",
        rule_version_id="rules-v1",
        job_template_version_id="jobs-v1",
        knowledge_index_version_id="knowledge-v1",
        prompt_version_id="prompt-v1",
        model_name="model-v1",
        embedding_model_version="embedding-v1",
    )
    db.add(report)
    db.flush()
    complete_job(db, job_id, "worker-a", claimed.lease_token, report.id)
    db.commit()
    ready = db.get(ReportGenerationJob, job_id)
    assert (ready.status, ready.report_id) == ("ready", "report-1")


def test_published_version_payload_cannot_be_updated(db):
    version = ContentVersion(id="questions-v1", kind="question", revision="1", payload={"count": 40}, status="published")
    db.add(version)
    db.commit()
    version.payload = {"count": 1}
    with pytest.raises(ValueError, match="immutable"):
        db.commit()


def test_draft_version_can_be_published_once(db):
    version = ContentVersion(id="questions-draft", kind="question", revision="draft-1", payload={"count": 40}, status="draft")
    db.add(version)
    db.commit()
    version.status = "published"
    db.commit()
    assert version.status == "published"


def test_enqueued_job_must_share_assessment_owner(db):
    add_owner_and_session(db)
    db.add(User(id="owner-2"))
    db.commit()
    with pytest.raises(ValueError, match="owner"):
        enqueue_job(db, "owner-2", snapshot())


def test_submission_snapshot_fields_cannot_be_replaced(db):
    add_owner_and_session(db)
    job_id = enqueue_job(db, "owner-1", snapshot())
    db.commit()
    db.expire_all()
    job = db.get(ReportGenerationJob, job_id)
    job.input_snapshot = {"changed": True}
    with pytest.raises(ValueError, match="immutable"):
        db.commit()


def test_third_expired_lease_transitions_job_to_failed(db):
    add_owner_and_session(db)
    job_id = enqueue_job(db, "owner-1", snapshot())
    job = db.get(ReportGenerationJob, job_id)
    job.status = "running"
    job.attempt_count = 3
    job.lease_owner = "dead-worker"
    job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert claim_next_job(db, "worker-b") is None
    db.refresh(job)
    assert (job.status, job.error_code) == ("failed", "MAX_ATTEMPTS_EXCEEDED")


def test_third_expired_lease_failure_persists_for_a_new_session(db):
    add_owner_and_session(db)
    job_id = enqueue_job(db, "owner-1", snapshot())
    job = db.get(ReportGenerationJob, job_id)
    job.status = "running"
    job.attempt_count = 3
    job.lease_owner = "dead-worker"
    job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert claim_next_job(db, "worker-b") is None
    bind = db.get_bind()
    db.close()
    with Session(bind) as fresh:
        persisted = fresh.get(ReportGenerationJob, job_id)
        assert (persisted.status, persisted.error_code) == ("failed", "MAX_ATTEMPTS_EXCEEDED")


def test_complete_job_rejects_report_from_another_owner(db):
    owner, assessment = add_owner_and_session(db)
    db.add(User(id="owner-2"))
    db.commit()
    job_id = enqueue_job(db, owner.id, snapshot())
    claimed = claim_next_job(db, "worker-a")
    report = ReportVersion(
        id="report-other", owner_id="owner-2", assessment_id=assessment.id, version=1,
        status="ready", review_status="pending", input_hash="hash-1",
        question_version_id="questions-v1", rule_version_id="rules-v1",
        job_template_version_id="jobs-v1", knowledge_index_version_id="knowledge-v1",
        prompt_version_id="prompt-v1", model_name="model-v1", embedding_model_version="embedding-v1",
    )
    db.add(report)
    with pytest.raises(IntegrityError):
        db.flush()


def test_complete_job_rejects_report_for_another_assessment(db):
    owner, assessment = add_owner_and_session(db)
    other = AssessmentSession(id="assessment-2", owner_id=owner.id, question_version_id="questions-v1")
    db.add(other)
    db.commit()
    job_id = enqueue_job(db, owner.id, snapshot())
    claimed = claim_next_job(db, "worker-a")
    report = ReportVersion(
        id="report-other-assessment", owner_id=owner.id, assessment_id=other.id, version=1,
        status="ready", review_status="pending", input_hash="hash-1",
        question_version_id="questions-v1", rule_version_id="rules-v1",
        job_template_version_id="jobs-v1", knowledge_index_version_id="knowledge-v1",
        prompt_version_id="prompt-v1", model_name="model-v1", embedding_model_version="embedding-v1",
    )
    db.add(report)
    db.flush()
    with pytest.raises(ValueError, match="report"):
        complete_job(db, job_id, "worker-a", claimed.lease_token, report.id)


def test_alembic_upgrade_builds_schema_with_foreign_keys(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database = tmp_path / "migrated.db"
    result = subprocess.run(
        [
            str(backend_dir.parent / ".venv" / "bin" / "alembic"),
            "-c",
            str(backend_dir / "alembic.ini"),
            "-x",
            f"database_url=sqlite:///{database}",
            "upgrade",
            "head",
        ],
        cwd=backend_dir,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    engine = build_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert set(Base.metadata.tables).issubset(set(engine.dialect.get_table_names(connection)))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    second = subprocess.run(result.args, cwd=backend_dir, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
