import json
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assessment.service import (
    DomainError,
    create_assessment,
    record_event,
    save_answer,
    submit_assessment,
)
from app.auth.service import require_owner
from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import create_app
from app.models import AssessmentSession, ContentVersion, ReportGenerationJob, User, VersionPointer
from app.seed.service import import_seed


@pytest.fixture()
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'assessment.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        payload = json.loads((Path(__file__).resolve().parents[1] / "seed" / "demo.json").read_text())
        session.add(User(id="owner-a"))
        session.add(User(id="owner-b"))
        import_seed(session, payload, "demo")
        session.commit()
        yield session
    engine.dispose()


def fill_all_answers(db: Session, session_id: str, owner_id: str = "owner-a") -> int:
    revision = 0
    for number in range(1, 41):
        question_id = f"demo-Q{number:02d}"
        if number <= 12:
            value = 3
        elif number <= 22:
            value = "clarify" if number == 13 else db.get(AssessmentSession, session_id).question_version_id
            question = db.get(ContentVersion, db.get(AssessmentSession, session_id).question_version_id).payload["questions"][number - 1]
            value = question["options"][0]["id"]
        elif number <= 32:
            question = db.get(ContentVersion, db.get(AssessmentSession, session_id).question_version_id).payload["questions"][number - 1]
            value = [question["options"][0]["id"]]
        else:
            value = f"demo experience {number}"
        revision, _ = save_answer(db, owner_id, session_id, question_id, value, revision)
    return revision


def test_create_exposes_40_public_questions_without_scoring_material(db):
    created = create_assessment(db, "owner-a")
    assert created["revision"] == 0
    assert len(created["questions"]) == 40
    assert created["demo"] is True
    assert created["status"] == "draft"
    assert created["answers"] == []
    assert created["jobId"] is None
    serialized = json.dumps(created["questions"])
    for private_key in ("weight", "reverse", "dimensionIds", "rules", "jobTemplates"):
        assert private_key not in serialized


def test_save_restore_validates_values_and_optimistic_revision(db):
    created = create_assessment(db, "owner-a")
    revision, count = save_answer(db, "owner-a", created["id"], "demo-Q01", 4, 0)
    assert (revision, count) == (1, 1)
    revision, count = save_answer(db, "owner-a", created["id"], "demo-Q23", ["breakdown"], 1)
    assert (revision, count) == (2, 2)
    with pytest.raises(DomainError) as stale:
        save_answer(db, "owner-a", created["id"], "demo-Q02", 3, 0)
    assert stale.value.code == "REVISION_CONFLICT"
    with pytest.raises(DomainError) as invalid:
        save_answer(db, "owner-a", created["id"], "demo-Q01", 9, 2)
    assert invalid.value.code == "INPUT_INVALID"


def test_incomplete_submission_does_not_lock_or_queue(db):
    created = create_assessment(db, "owner-a")
    save_answer(db, "owner-a", created["id"], "demo-Q01", 3, 0)
    with pytest.raises(DomainError) as error:
        submit_assessment(db, "owner-a", created["id"], "submit-1")
    assert error.value.code == "INPUT_INVALID"
    assert db.get(AssessmentSession, created["id"]).status == "draft"
    assert db.query(ReportGenerationJob).count() == 0


def test_submit_freezes_demo_bundle_and_is_idempotent(db):
    created = create_assessment(db, "owner-a")
    fill_all_answers(db, created["id"])
    job_id = submit_assessment(db, "owner-a", created["id"], "submit-1")
    assert submit_assessment(db, "owner-a", created["id"], "submit-1") == job_id
    job = db.get(ReportGenerationJob, job_id)
    version_id = created["questionVersion"]
    assert job.status == "queued"
    assert job.source_versions == {
        "questionVersion": version_id,
        "ruleVersion": version_id,
        "jobTemplateVersion": version_id,
        "knowledgeIndexVersion": "demo-unavailable-knowledge-index",
        "promptVersion": "demo-unavailable-prompt",
        "modelName": "demo-unavailable-provider",
        "embeddingModelVersion": "demo-unavailable-embedding",
        "profileSnapshotId": None,
    }
    assert len(job.input_snapshot["answers"]) == 40
    assert job.input_snapshot["contentBundle"]["metadata"]["mode"] == "demo"
    with pytest.raises(DomainError) as locked:
        save_answer(db, "owner-a", created["id"], "demo-Q01", 5, 40)
    assert locked.value.code == "ALREADY_SUBMITTED"
    restored = __import__("app.assessment.service", fromlist=["session_detail"]).session_detail(db, "owner-a", created["id"])
    assert restored["status"] == "submitted"
    assert restored["jobId"] == job_id


def test_optional_answer_may_be_omitted_from_snapshot(db):
    base = db.scalar(select(ContentVersion).where(ContentVersion.kind == "question"))
    payload = deepcopy(base.payload)
    payload["questions"][-1]["required"] = False
    version = ContentVersion(id="optional-v1", kind="question", revision="optional-1", payload=payload, status="published")
    db.add(version)
    db.scalar(select(VersionPointer).where(VersionPointer.kind == "question")).version_id = version.id
    db.commit()
    created = create_assessment(db, "owner-a")
    revision = 0
    for number in range(1, 40):
        question = version.payload["questions"][number - 1]
        value = 3 if question["type"] == "scale" else question.get("options", [{"id": "demo"}])[0]["id"]
        if question["type"] == "multiple": value = [value]
        if question["type"] == "experience": value = "experience"
        revision, _ = save_answer(db, "owner-a", created["id"], question["id"], value, revision)
    job_id = submit_assessment(db, "owner-a", created["id"], "optional-submit")
    answers = db.get(ReportGenerationJob, job_id).input_snapshot["answers"]
    assert len(answers) == 39
    assert "demo-Q40" not in {answer["questionId"] for answer in answers}


def test_owner_isolation_returns_not_found(db):
    created = create_assessment(db, "owner-a")
    with pytest.raises(DomainError) as error:
        save_answer(db, "owner-b", created["id"], "demo-Q01", 3, 0)
    assert (error.value.status_code, error.value.code) == (404, "NOT_FOUND")


def test_two_database_sessions_cannot_overwrite_same_revision(db):
    created = create_assessment(db, "owner-a")
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    first, second = factory(), factory()
    try:
        assert save_answer(first, "owner-a", created["id"], "demo-Q01", 3, 0) == (1, 1)
        with pytest.raises(DomainError) as stale:
            save_answer(second, "owner-a", created["id"], "demo-Q02", 4, 0)
        assert stale.value.code == "REVISION_CONFLICT"
    finally:
        first.close()
        second.close()


def test_events_allow_only_identifiers_and_status(db):
    created = create_assessment(db, "owner-a")
    record_event(db, "owner-a", created["id"], "event-1", "assessment_start", {"status": "draft"})
    record_event(db, "owner-a", created["id"], "event-1", "assessment_start", {"status": "draft"})
    with pytest.raises(DomainError) as unsafe:
        record_event(db, "owner-a", created["id"], "event-2", "question_answer", {"text": "private answer"})
    assert unsafe.value.code == "INPUT_INVALID"


def test_assessment_routes_restore_current_draft(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    app = create_app()
    def override_db():
        with factory() as route_db:
            yield route_db
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_owner] = lambda: "owner-a"
    client = TestClient(app)
    created = client.post("/api/v1/sessions", headers={"X-CSRF-Token": "test"}).json()
    saved = client.put(
        f"/api/v1/sessions/{created['id']}/answers/demo-Q01",
        headers={"X-CSRF-Token": "test"},
        json={"value": 4, "revision": 0},
    )
    assert saved.json() == {"revision": 1, "answeredCount": 1}
    current = client.get("/api/v1/sessions/current").json()["session"]
    assert current["id"] == created["id"]
    assert current["answers"] == [{"questionId": "demo-Q01", "value": 4}]
