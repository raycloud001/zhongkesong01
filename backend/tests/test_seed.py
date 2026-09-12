import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import ContentVersion, VersionPointer
from app.seed.service import validate_seed, import_seed


@pytest.fixture()
def payload():
    path = Path(__file__).resolve().parents[1] / "seed" / "demo.json"
    return json.loads(path.read_text())


@pytest.fixture()
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_incomplete_seed():
    assert "QUESTION_COUNT" in validate_seed({"questions": []})


def test_demo_fixture_has_required_bounded_content(payload):
    assert validate_seed(payload) == []
    assert payload["metadata"] == {"mode": "demo", "expertConfirmed": False, "synthetic": True}
    assert len(payload["questions"]) == 40
    assert len({item["id"] for item in payload["questions"]}) == 40
    assert [item["id"] for item in payload["questions"]] == [f"demo-Q{i:02d}" for i in range(1, 41)]
    assert len(payload["dimensions"]) == 6
    assert len(payload["jobTemplates"]) == 3
    assert {item["type"] for item in payload["questions"]} == {"single", "multiple", "scale", "experience"}


def test_validation_detects_ids_types_ranges_and_references(payload):
    payload["questions"][1]["id"] = "demo-Q01"
    payload["questions"][2]["type"] = "unknown"
    payload["questions"][3]["weight"] = 0
    payload["questions"][4]["dimensionIds"] = ["missing"]
    payload["questions"][5]["min"] = 9
    assert {
        "QUESTION_ID", "QUESTION_TYPE", "WEIGHT_RANGE", "DIMENSION_REFERENCE", "QUESTION_RANGE"
    }.issubset(validate_seed(payload))


def test_production_import_rejects_demo_payload(db, payload):
    with pytest.raises(ValueError, match="expert-confirmed"):
        import_seed(db, payload, "production")


def test_demo_import_is_idempotent_and_does_not_replace_pointer(db, payload):
    first = import_seed(db, payload, "demo")
    db.commit()
    pointer = db.query(VersionPointer).filter_by(kind="question").one()
    assert pointer.version_id == first
    second = import_seed(db, payload, "demo")
    db.commit()
    assert second == first
    assert db.query(ContentVersion).filter_by(kind="question").count() == 1
    assert db.query(VersionPointer).filter_by(kind="question").one().version_id == first


def test_import_does_not_overwrite_existing_active_pointer(db, payload):
    existing = ContentVersion(id="expert-v1", kind="question", revision="expert-1", payload={"expert": True}, status="published")
    db.add(existing)
    db.flush()
    db.add(VersionPointer(id="question-current", kind="question", version_id=existing.id))
    db.commit()
    imported = import_seed(db, payload, "demo")
    db.commit()
    assert imported != existing.id
    assert db.query(VersionPointer).filter_by(kind="question").one().version_id == existing.id


def test_malformed_seed_returns_errors_instead_of_crashing(payload):
    payload["dimensions"][0]["id"] = ["unhashable"]
    payload["questions"][0]["id"] = ["unhashable"]
    payload["questions"][12]["options"] = [None]
    payload["questions"][2]["min"] = True
    payload["questions"][2]["max"] = float("inf")
    payload["questions"][32]["maxLength"] = 0
    errors = validate_seed(payload)
    assert {"DIMENSION_ID", "QUESTION_ID", "QUESTION_OPTIONS", "QUESTION_RANGE"}.issubset(errors)


def test_duplicate_option_ids_and_missing_common_fields_are_invalid(payload):
    payload["questions"][12]["options"][1]["id"] = payload["questions"][12]["options"][0]["id"]
    del payload["questions"][13]["text"]
    payload["questions"][14]["required"] = "yes"
    payload["questions"][15]["reverse"] = 0
    assert {"QUESTION_OPTIONS", "QUESTION_FIELDS"}.issubset(validate_seed(payload))


def test_production_metadata_requires_real_scoring_anchors(db, payload):
    payload["metadata"] = {"mode": "production", "expertConfirmed": True, "synthetic": False}
    payload["rules"]["demo"] = False
    payload["rules"]["scoringAnchors"] = []
    with pytest.raises(ValueError, match="SCORING_ANCHORS"):
        import_seed(db, payload, "production")


def test_malformed_type_and_multiple_options_return_errors(payload):
    payload["questions"][0]["type"] = []
    payload["questions"][22]["options"] = None
    assert {"QUESTION_TYPE", "QUESTION_RANGE", "QUESTION_OPTIONS"}.issubset(validate_seed(payload))


def test_production_rejects_synthetic_flags_placeholder_anchors_and_jobs(db, payload):
    payload["metadata"].update(mode="production", expertConfirmed=True)
    payload["rules"]["scoringAnchors"] = [None]
    payload["jobTemplates"] = [None]
    errors = validate_seed(payload)
    assert {"PRODUCTION_SYNTHETIC", "SCORING_ANCHORS", "JOB_TEMPLATES"}.issubset(errors)
    with pytest.raises(ValueError):
        import_seed(db, payload, "production")


def test_demo_contains_valid_talent_types_anchors_and_two_complete_answer_sets(payload):
    assert validate_seed(payload) == []
    assert len(payload["talentTypes"]) >= 2
    assert len(payload["rules"]["scoringAnchors"]) == 40
    assert len(payload["sampleAnswers"]) == 2
    assert {sample["ownerId"] for sample in payload["sampleAnswers"]} == {"demo-user-a", "demo-user-b"}
    for sample in payload["sampleAnswers"]:
        assert len(sample["answers"]) == 40


def test_none_metadata_returns_error_instead_of_crashing(db, payload):
    payload["metadata"] = None
    assert "METADATA" in validate_seed(payload)
    with pytest.raises(ValueError):
        import_seed(db, payload, "production")


def test_anchors_must_have_unique_ids_and_cover_every_question_once(payload):
    first = payload["rules"]["scoringAnchors"][0]
    payload["rules"]["scoringAnchors"] = [dict(first) for _ in range(40)]
    assert "SCORING_ANCHORS" in validate_seed(payload)


def test_production_rejects_nested_synthetic_business_content(db, payload):
    payload["metadata"] = {"mode": "production", "expertConfirmed": True, "synthetic": False}
    payload["rules"]["demo"] = False
    payload["jobTemplates"][0]["synthetic"] = True
    payload["talentTypes"][0]["synthetic"] = True
    errors = validate_seed(payload)
    assert "PRODUCTION_SYNTHETIC" in errors
    with pytest.raises(ValueError, match="PRODUCTION_SYNTHETIC"):
        import_seed(db, payload, "production")


def test_talent_type_and_sample_answer_references_are_validated(payload):
    payload["talentTypes"][0]["dimensionIds"] = ["missing"]
    payload["sampleAnswers"][0]["answers"][0]["questionId"] = "missing"
    payload["sampleAnswers"][1]["answers"] = payload["sampleAnswers"][1]["answers"][:-1]
    assert {"TALENT_TYPES", "SAMPLE_ANSWERS"}.issubset(validate_seed(payload))
