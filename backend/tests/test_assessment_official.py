import json
from pathlib import Path

from app.assessment.service import DomainError, _valid_value, _version_payload, create_assessment, save_answer, submit_assessment
from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.seed.official import import_official_evidence
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "backend/seed/official-questionnaire.json"
SOURCE = ASSET.parent / "sources/题目与AI报告生成规则.md"


def db_with_official(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'official-assessment.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(User(id="owner-official"))
    payload = json.loads(ASSET.read_text())
    import_official_evidence(db, payload, source_path=SOURCE, activate=True)
    db.commit()
    return engine, db


def test_official_create_exposes_fields_and_preserves_compound_schema(tmp_path):
    engine, db = db_with_official(tmp_path)
    try:
        created = create_assessment(db, "owner-official")
        assert created["demo"] is False
        assert [question["id"] for question in created["questions"]] == [f"Q{i:02d}" for i in range(1, 41)]
        q25 = next(question for question in created["questions"] if question["id"] == "Q25")
        assert q25["type"] == "compound"
        assert {field["id"] for field in q25["fields"]} == {"choice", "reason"}
        assert "evidenceRule" not in json.dumps(created["questions"], ensure_ascii=False)
    finally:
        db.close(); engine.dispose()


def test_official_compound_values_validate_and_q39_is_optional(tmp_path):
    engine, db = db_with_official(tmp_path)
    try:
        created = create_assessment(db, "owner-official")
        revision, _ = save_answer(db, "owner-official", created["id"], "Q25", {"choice": "A", "reason": "因为经常跳过"}, 0)
        assert revision == 1
        revision, _ = save_answer(db, "owner-official", created["id"], "Q30", {"name": "SQL", "frequency": "每周", "typicalTask": "查询", "independence": 3}, revision)
        assert revision == 2
        try:
            save_answer(db, "owner-official", created["id"], "Q25", {"choice": "A", "reason": "这段文字超过二十个字符限制一定会失败啊啊啊啊啊"}, revision)
        except Exception as error:
            assert getattr(error, "code", None) == "INPUT_INVALID"
        else:
            raise AssertionError("overlong Q25 reason was accepted")
    finally:
        db.close(); engine.dispose()


def test_official_source_rules_reject_invalid_supplied_values():
    questions={q["id"]:q for q in json.loads(ASSET.read_text())["questions"]}
    assert not _valid_value(questions["Q04"],["A","B","C"])
    assert not _valid_value(questions["Q36"],{"choice":"C"},final=True)
    assert _valid_value(questions["Q37"],{"status":"no_experience"},final=True)
    assert not _valid_value(questions["Q39"],{"audio":"fake"})


def test_q37_draft_enforces_combined_max_but_final_enforces_min_and_trimmed_required_text():
    questions={q["id"]:q for q in json.loads(ASSET.read_text())["questions"]}
    assert _valid_value(questions["Q37"],{"status":"has_experience","goal":"短目标","action":"短动作"})
    assert not _valid_value(questions["Q37"],{"status":"has_experience","goal":"甲"*101,"action":"乙"*100})
    assert not _valid_value(questions["Q37"],{"status":"has_experience","goal":"短目标","action":"短动作"},final=True)
    assert not _valid_value(questions["Q37"],{"status":"has_experience","goal":" "*50,"action":"乙"*50},final=True)
    assert not _valid_value(questions["Q25"],{"choice":"A","reason":"   "},final=True)
    assert not _valid_value(questions["Q36"],{"choice":"C","reason":"\t"},final=True)
    required_experience={"type":"experience","required":True,"maxLength":500}
    assert _valid_value(required_experience,"   ",final=False)
    assert not _valid_value(required_experience,"   ",final=True)


def test_non_evidence_production_bundle_keeps_provider_gate(tmp_path):
    engine, db = db_with_official(tmp_path)
    try:
        from types import SimpleNamespace
        bundle = SimpleNamespace(payload={"metadata":{"mode":"production"}})
        with __import__("pytest").raises(DomainError) as error:
            _version_payload(db,"job_template",bundle,"evidence-unavailable-job-template")
        assert (error.value.status_code,error.value.code)==(503,"PROVIDER_UNAVAILABLE")
    finally:
        db.close(); engine.dispose()


def test_official_submission_accepts_39_required_answers_without_q39(tmp_path):
    engine, db = db_with_official(tmp_path)
    try:
        created = create_assessment(db, "owner-official")
        revision = 0
        for question in created["questions"]:
            if question["id"] == "Q39":
                continue
            field_values = {}
            for field in question.get("fields", []):
                if field.get("required"):
                    if field["type"] == "single": field_values[field["id"]] = field["options"][0]["id"]
                    elif field["type"] == "multiple": field_values[field["id"]] = [field["options"][0]["id"]]
                    elif field["type"] == "integer": field_values[field["id"]] = field.get("min", 1)
                    else: field_values[field["id"]] = "x" * 50 if question["id"] == "Q37" else "x"
            value = field_values if question["type"] == "compound" else (question["options"][0]["id"] if question["type"] == "single" else [question["options"][0]["id"]] if question["type"] == "multiple" else "x")
            revision, _ = save_answer(db, "owner-official", created["id"], question["id"], value, revision)
        job_id = submit_assessment(db, "owner-official", created["id"], "official-39")
        assert job_id
    finally:
        db.close(); engine.dispose()
