import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, text

from app.contracts.report import Core, Decisions, JobMatch
from app.db.session import build_engine
from app.models.report import JobMatch as JobMatchRecord


def claim(identifier="c1"):
    return {"id": identifier, "text": "待验证", "claimType": "to_validate", "references": []}


def action():
    return {"id": "a1", "title": "验证", "reason": claim(), "firstStep": "记录结果", "methodReferences": [], "status": "pending"}


def job_match():
    dimensions = [
        "core_task", "industry_qualification", "hard_skill", "service_chain", "responsibility_environment"
    ]
    return {
        "id": "j1", "name": "待核实岗位", "jobSourceId": None, "jobVersion": None,
        "sourceStatus": "unknown", "tasks": [], "eligibility": "explore",
        "strategyLabel": None, "strategyStatus": "pending_method",
        "taskCoverage": {"behavior": None, "verified": None}, "evidenceStatus": "unknown",
        "requirementComparisons": [], "hardGates": [],
        "transfer": {"level": "unknown", "provisional": False, "dimensions": [
            {"key": key, "status": "unknown", "evidenceIds": [], "requirementIds": [], "references": []}
            for key in dimensions
        ], "reason": claim("transfer")},
        "reason": claim(), "evidenceIds": [], "gaps": [], "risks": [],
        "validationTask": action(), "industryContext": {"point": claim("p"), "line": claim("l"), "plane": claim("pl"), "system": claim("s"), "asOf": None, "references": []},
    }


def test_evidence_only_core_allows_null_type_and_radar():
    data = Core.model_validate({"type": None, "keySummaries": {"state": claim(), "advantage": claim(), "risk": claim()}, "radar": None, "evidence": [], "strengths": [], "weaknesses": [], "risk": None, "judgments": []})
    assert data.type is data.radar is None


def test_decisions_limit_recommendations_and_explicit_targets_separately():
    match = job_match()
    with pytest.raises(ValidationError):
        Decisions.model_validate({"jobMatches": [match] * 4, "explicitTargets": [], "preferredDirection": None, "alternativeDirection": None, "actions": [], "actionPlan": [], "preparationSuggestions": [], "counterEvidenceConditions": []})


def test_pending_strategy_and_transfer_source_semantics():
    pending = job_match()
    pending["strategyLabel"] = "steady"
    with pytest.raises(ValidationError):
        JobMatch.model_validate(pending)
    provisional = job_match()
    provisional["sourceStatus"] = "template_provisional"
    provisional["jobSourceId"] = "template-r1"
    provisional["jobVersion"] = "templates-v1"
    provisional["transfer"]["provisional"] = True
    provisional["transfer"]["level"] = "medium"
    with pytest.raises(ValidationError):
        JobMatch.model_validate(provisional)


def test_job_match_migration_preserves_legacy_and_accepts_evidence_payload(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "upgrade.db"
    import subprocess

    def upgrade(revision):
        command = [str(backend.parent / ".venv/bin/alembic"), "-c", str(backend / "alembic.ini"), "-x", f"database_url=sqlite:///{database}", "upgrade", revision]
        return subprocess.run(command, cwd=backend, text=True, capture_output=True)

    result = upgrade("7b8d4a2f6c10")
    assert result.returncode == 0, result.stderr
    engine = build_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, created_at) VALUES ('owner-1', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO assessment_sessions (id, owner_id, question_version_id, status, revision, created_at) VALUES ('session-1', 'owner-1', 'questions-v1', 'completed', 0, CURRENT_TIMESTAMP)"))
        connection.execute(text("""INSERT INTO report_versions
            (id, owner_id, assessment_id, version, demo, status, review_status, input_hash,
             question_version_id, rule_version_id, job_template_version_id, knowledge_index_version_id,
             prompt_version_id, model_name, embedding_model_version, created_at)
            VALUES ('report-1', 'owner-1', 'session-1', 1, 0, 'ready', 'pending', 'hash',
                    'questions-v1', 'rules-v1', 'jobs-v1', 'knowledge-v1', 'prompt-v1', 'model',
                    'embedding', CURRENT_TIMESTAMP)"""))
        connection.execute(text("""INSERT INTO job_matches
            (id, report_id, job_template_version_id, match_status, evidence_sufficiency,
             current_basis, potential_basis, tasks, gaps, risks, validation_task, industry_context)
            VALUES ('legacy-1', 'report-1', 'jobs-v1', 'matched', 'sufficient',
                    'legacy current', 'legacy potential', '[]', '[]', '[]', '{}', '{}')"""))

    result = upgrade("c4e0d19a73b2")
    assert result.returncode == 0, result.stderr
    columns = {column["name"]: column for column in inspect(engine).get_columns("job_matches")}
    assert columns["contract_version"]["nullable"] is True
    assert columns["structured_payload"]["nullable"] is True
    legacy_columns = {
        "job_template_version_id", "match_status", "evidence_sufficiency", "current_basis",
        "potential_basis", "tasks", "gaps", "risks", "validation_task", "industry_context",
    }
    assert all(columns[name]["nullable"] for name in legacy_columns)
    assert all(JobMatchRecord.__table__.c[name].nullable == columns[name]["nullable"] for name in columns)

    with engine.begin() as connection:
        legacy = connection.execute(text("SELECT match_status, current_basis, contract_version FROM job_matches WHERE id='legacy-1'"),).one()
        assert legacy == ("matched", "legacy current", None)
        connection.execute(text("""INSERT INTO job_matches
            (id, report_id, contract_version, structured_payload)
            VALUES ('evidence-1', 'report-1', 'evidence-v2', '{"sourceStatus":"unknown"}')"""))
        inserted = connection.execute(text("SELECT match_status, contract_version FROM job_matches WHERE id='evidence-1'"),).one()
        assert inserted == (None, "evidence-v2")
