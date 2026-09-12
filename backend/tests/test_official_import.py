import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import ContentVersion, VersionPointer
from app.seed.official import import_official_evidence, validate_official_evidence


ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "backend/seed/official-questionnaire.json"


@pytest.fixture()
def payload():
    return json.loads(ASSET.read_text())


@pytest.fixture()
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'official.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_official_asset_is_evidence_only_without_scores(payload):
    assert validate_official_evidence(payload, ASSET.parent / "sources/题目与AI报告生成规则.md") == []
    forbidden = {"weight", "score", "scoringAnchors", "talentTypes", "jobThresholds"}
    assert forbidden.isdisjoint(payload)


def test_source_digest_tampering_is_rejected(payload, tmp_path):
    source = tmp_path / "source.md"
    source.write_text("tampered")
    assert "SOURCE_DIGEST" in validate_official_evidence(payload, source)


def test_questionnaire_payload_tampering_is_rejected(payload):
    payload["questions"][0]["text"] = "tampered"
    source = ASSET.parent / "sources/题目与AI报告生成规则.md"
    assert "SOURCE_MAPPING" in validate_official_evidence(payload, source)


@pytest.mark.parametrize("malformed", [None, [], {"metadata": {}, "questions": 40}])
def test_malformed_official_payload_returns_errors(malformed):
    source = ASSET.parent / "sources/题目与AI报告生成规则.md"
    assert validate_official_evidence(malformed, source)


def test_import_is_idempotent_without_implicit_pointer_activation(db, payload):
    source = ASSET.parent / "sources/题目与AI报告生成规则.md"
    first = import_official_evidence(db, payload, source_path=source)
    db.commit()
    second = import_official_evidence(db, payload, source_path=source)
    db.commit()
    assert first == second
    assert db.query(ContentVersion).filter_by(kind="question").count() == 1
    assert db.query(ContentVersion).filter_by(kind="rule").count() == 1
    assert db.query(VersionPointer).filter_by(kind="question").count() == 0
    assert db.query(VersionPointer).filter_by(kind="rule").count() == 0
    rule = db.query(ContentVersion).filter_by(kind="rule").one()
    assert rule.payload["sourceSha256"] == payload["metadata"]["sourceSha256"]
    assert rule.payload["sourceSections"] == ["4", "6.3", "7.2", "8"]


def test_activation_is_explicit_and_switches_question_and_rule_pointers(db, payload):
    source = ASSET.parent / "sources/题目与AI报告生成规则.md"
    version_id = import_official_evidence(db, payload, source_path=source, activate=True)
    db.commit()
    assert db.query(VersionPointer).filter_by(kind="question").one().version_id == version_id
    rule = db.query(ContentVersion).filter_by(kind="rule").one()
    assert db.query(VersionPointer).filter_by(kind="rule").one().version_id == rule.id


def test_import_is_idempotent_and_activation_is_explicit(db, payload):
    source = ASSET.parent / "sources/题目与AI报告生成规则.md"
    first = import_official_evidence(db, payload, source_path=source, activate=False)
    db.commit()
    second = import_official_evidence(db, payload, source_path=source, activate=False)
    db.commit()
    assert first == second
    assert db.query(ContentVersion).filter_by(kind="question", id=first).count() == 1
    assert db.query(VersionPointer).filter_by(kind="question").count() == 0


def test_activation_does_not_implicitly_replace_an_existing_pointer(db, payload):
    existing = ContentVersion(id="questions-old", kind="question", revision="old", payload={}, status="published")
    db.add(existing); db.flush()
    db.add(VersionPointer(id="question-pointer", kind="question", version_id=existing.id)); db.commit()
    imported = import_official_evidence(db, payload, source_path=ASSET.parent / "sources/题目与AI报告生成规则.md", activate=False)
    db.commit()
    assert db.query(VersionPointer).filter_by(kind="question").one().version_id == existing.id
    assert imported != existing.id
