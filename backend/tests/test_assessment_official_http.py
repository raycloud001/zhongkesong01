import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import create_app
from app.models import AssessmentSession, ReportGenerationJob, VersionPointer
from app.seed.official import import_official_evidence


ROOT=Path(__file__).resolve().parents[2]


def official_value(question):
    if question["id"] == "Q37":
        return {"status":"no_experience"}
    if question["type"] == "compound":
        value={}
        for field in question.get("fields",[]):
            if not field.get("required") or field.get("condition"):
                continue
            if field["type"] == "single": value[field["id"]]=field["options"][0]["id"]
            elif field["type"] == "multiple": value[field["id"]]=[field["options"][0]["id"]]
            elif field["type"] == "integer": value[field["id"]]=field.get("min",1)
            else: value[field["id"]]="x"
        return value
    if question["type"] == "single": return question["options"][0]["id"]
    if question["type"] == "multiple": return [question["options"][0]["id"]]
    if question["type"] == "scale": return question["min"]
    return "x"


def build_client(monkeypatch,tmp_path,name):
    origin="https://assessment.test"
    monkeypatch.setenv("FRONTEND_ORIGIN",origin)
    monkeypatch.setenv("MODELSCOPE_MODEL_NAME","")
    monkeypatch.setenv("MODELSCOPE_EMBEDDING_MODEL","   ")
    engine=build_engine(f"sqlite:///{tmp_path/name}")
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    asset=ROOT/"backend/seed/official-questionnaire.json"
    with factory() as db:
        question_version=import_official_evidence(db,json.loads(asset.read_text()),source_path=asset.parent/"sources/题目与AI报告生成规则.md",activate=True)
        rule_version=db.scalar(select(VersionPointer.version_id).where(VersionPointer.kind=="rule"))
        db.commit()
    app=create_app()
    def override_db():
        with factory() as db: yield db
    app.dependency_overrides[get_db]=override_db
    client=TestClient(app)
    identity=client.post("/api/v1/identity/anonymous",headers={"Origin":origin})
    assert identity.status_code==201
    headers={"Origin":origin,"X-CSRF-Token":identity.json()["csrfToken"]}
    return engine,factory,client,headers,question_version,rule_version


def fill_official_over_http(client,headers,session):
    revision=0
    for question in session["questions"]:
        if question["id"]=="Q39": continue
        response=client.put(f"/api/v1/sessions/{session['id']}/answers/{question['id']}",headers=headers,json={"value":official_value(question),"revision":revision})
        assert response.status_code==200,(question["id"],response.text)
        revision=response.json()["revision"]
    assert revision==39


def test_authenticated_http_partial_compound_restore(monkeypatch,tmp_path):
    origin="https://assessment.test"
    monkeypatch.setenv("FRONTEND_ORIGIN",origin)
    engine=build_engine(f"sqlite:///{tmp_path/'official-http.db'}")
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    asset=ROOT/"backend/seed/official-questionnaire.json"
    with factory() as db:
        import_official_evidence(db,json.loads(asset.read_text()),source_path=asset.parent/"sources/题目与AI报告生成规则.md",activate=True)
        db.commit()
    app=create_app()
    def override_db():
        with factory() as db: yield db
    app.dependency_overrides[get_db]=override_db
    client=TestClient(app)
    identity=client.post("/api/v1/identity/anonymous",headers={"Origin":origin})
    assert identity.status_code==201
    csrf=identity.json()["csrfToken"]
    created=client.post("/api/v1/sessions",headers={"Origin":origin,"X-CSRF-Token":csrf},json={"mode":"evidence_only"})
    assert created.status_code==201
    session=created.json()
    assert session["questions"][24]["id"]=="Q25"
    saved=client.put(f"/api/v1/sessions/{session['id']}/answers/Q25",headers={"Origin":origin,"X-CSRF-Token":csrf},json={"value":{"choice":"A"},"revision":0})
    assert saved.status_code==200
    current=client.get("/api/v1/sessions/current?mode=evidence_only").json()["session"]
    assert current["answers"]==[{"questionId":"Q25","value":{"choice":"A"}}]
    rejected=client.put(f"/api/v1/sessions/{session['id']}/answers/Q39",headers={"Origin":origin,"X-CSRF-Token":csrf},json={"value":{"audio":"fake"},"revision":1})
    assert rejected.status_code==422
    engine.dispose()


def test_authenticated_http_submits_all_required_official_answers_with_frozen_provenance(monkeypatch,tmp_path):
    engine,factory,client,headers,question_version,rule_version=build_client(monkeypatch,tmp_path,"official-submit.db")
    try:
        created=client.post("/api/v1/sessions",headers=headers,json={"mode":"evidence_only"})
        assert created.status_code==201
        session=created.json()
        fill_official_over_http(client,headers,session)
        submitted=client.post(f"/api/v1/sessions/{session['id']}/submit",headers={**headers,"Idempotency-Key":"official-http-39"})
        assert submitted.status_code==202
        with factory() as db:
            job=db.get(ReportGenerationJob,submitted.json()["jobId"])
            assert job is not None
            versions=job.input_snapshot["sourceVersions"]
            assert versions=={
                "questionVersion":question_version,
                "ruleVersion":rule_version,
                "jobTemplateVersion":"evidence-unavailable-job-template",
                "knowledgeIndexVersion":"evidence-unavailable-knowledge-index",
                "promptVersion":"evidence-unavailable-prompt",
                "modelName":"evidence-unavailable-model",
                "embeddingModelVersion":"evidence-unavailable-embedding",
                "profileSnapshotId":None,
            }
            answers=job.input_snapshot["answers"]
            assert len(answers)==39
            assert "Q39" not in {answer["questionId"] for answer in answers}
            assert job.input_snapshot["sourcePayloads"]["jobTemplates"]=={"mode":"evidence_only","available":False}
            assert job.input_snapshot["sourcePayloads"]["prompt"]=={"mode":"evidence_only","available":False}
            assert job.input_snapshot["sourcePayloads"]["knowledgeIndex"]=={"mode":"evidence_only","available":False}
    finally:
        engine.dispose()


def test_missing_published_rule_returns_503_and_leaves_authenticated_session_draft(monkeypatch,tmp_path):
    engine,factory,client,headers,_,_=build_client(monkeypatch,tmp_path,"official-missing-rule.db")
    try:
        created=client.post("/api/v1/sessions",headers=headers,json={"mode":"evidence_only"}).json()
        fill_official_over_http(client,headers,created)
        with factory() as db:
            db.execute(delete(VersionPointer).where(VersionPointer.kind=="rule")); db.commit()
        submitted=client.post(f"/api/v1/sessions/{created['id']}/submit",headers={**headers,"Idempotency-Key":"missing-rule"})
        assert submitted.status_code==503
        assert submitted.json()["error"]["code"]=="PROVIDER_UNAVAILABLE"
        with factory() as db:
            assert db.get(AssessmentSession,created["id"]).status=="draft"
            assert db.scalar(select(ReportGenerationJob).where(ReportGenerationJob.assessment_id==created["id"])) is None
    finally:
        engine.dispose()
