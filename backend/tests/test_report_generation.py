import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ProviderUnavailable
from app.contracts.report import Core, Decisions, Interpretation
from app.db.base import Base
from app.db.session import build_engine
from app.jobs.store import enqueue_job
from app.models import AssessmentSession, ReportGenerationJob, ReportVersion, User
from app.reports.service import run_once


class FailingProvider:
    def __init__(self):
        self.calls = 0

    async def generate_report(self, payload):
        self.calls += 1
        raise ProviderUnavailable("offline")


class RetryingProvider:
    def __init__(self, response):
        self.calls = 0
        self.response = response

    async def generate_report(self, payload):
        self.calls += 1
        if self.calls == 1:
            raise ProviderUnavailable("temporary")
        return self.response


class Retriever:
    def __init__(self):
        self.calls = []

    def retrieve(self, index_version_id, query, tags, limit=6):
        self.calls.append((index_version_id, query, tags, limit))
        return [{"id": "knowledge-1", "version": index_version_id, "content": "先验证目标岗位的真实任务。"}]


@pytest.fixture()
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'reports.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(id="owner-1")
        assessment = AssessmentSession(
            id="assessment-1", owner_id=owner.id, question_version_id="questions-v1", status="submitted"
        )
        session.add(owner)
        session.flush()
        session.add(assessment)
        session.commit()
        yield session
    engine.dispose()


def versions():
    return {
        "questionVersion": "questions-v1",
        "ruleVersion": "rules-v1",
        "jobTemplateVersion": "jobs-v1",
        "knowledgeIndexVersion": "knowledge-v1",
        "promptVersion": "prompt-v1",
        "modelName": "model-v1",
        "embeddingModelVersion": "embedding-v1",
        "profileSnapshotId": None,
    }


def snapshot():
    return {
        "assessmentId": "assessment-1",
        "inputHash": "input-hash",
        "sourceVersions": versions(),
        "answers": [
            {
                "id": "evidence-1",
                "questionId": "Q37",
                "answerId": "answer-37",
                "quote": "完成并复盘一个内容项目",
                "taskIds": ["content"],
                "sourceStatus": "behavior",
            }
        ],
        "sourcePayloads": {
            "rules": {"version": "rules-v1", "coreTasks": [{"id": "content", "name": "内容生产"}]},
            "jobTemplates": [],
            "prompt": {"version": "prompt-v1"},
            "knowledgeIndex": {"available": True},
        },
        "contentBundle": {"metadata": {"mode": "evidence_only"}},
    }


def test_run_once_keeps_structured_evidence_when_provider_is_unavailable(db):
    job_id = enqueue_job(db, "owner-1", snapshot())
    provider = FailingProvider()

    assert run_once(db, provider=provider, worker_id="worker-a") is True

    job = db.get(ReportGenerationJob, job_id)
    report = db.get(ReportVersion, job.report_id)
    assert provider.calls == 2
    assert job.status == "ready"
    assert report.status == "ready"
    assert report.core["radar"] is None
    assert report.core["type"] is None
    assert report.interpretation["aiUsageNotice"]
    Core.model_validate(report.core)
    Decisions.model_validate(report.decisions)
    Interpretation.model_validate(report.interpretation)


def test_run_once_retries_provider_once_and_validates_references(db):
    job_id = enqueue_job(db, "owner-1", snapshot())
    retriever = Retriever()
    response = {
        "sections": [
            {"key": "core_judgment", "claims": [{"id": "c1", "text": "已有行为证据", "claimType": "fact", "references": [{"source": "answer", "id": "answer-37", "version": "runtime", "location": "Q37"}]}]},
            {"key": "job_impact", "claims": [{"id": "c2", "text": "先验证岗位任务", "claimType": "recommendation", "references": [{"source": "knowledge", "id": "knowledge-1", "version": "knowledge-v1", "location": None}]}]},
            {"key": "uncertainty", "claims": [{"id": "c3", "text": "仍需补充核验", "claimType": "to_validate", "references": [{"source": "answer", "id": "evidence-1", "version": "runtime", "location": "Q37"}]}]},
            {"key": "validation", "claims": [{"id": "c4", "text": "记录下一次任务结果", "claimType": "recommendation", "references": [{"source": "method", "id": "evidence-rule", "version": "rules-v1", "location": None}]}]},
        ],
        "aiUsageNotice": "模型仅用于解释已锁定判断。",
        "reviewItems": [],
    }
    provider = RetryingProvider(response)

    assert run_once(db, provider=provider, retriever=retriever, worker_id="worker-b") is True

    job = db.get(ReportGenerationJob, job_id)
    report = db.get(ReportVersion, job.report_id)
    assert provider.calls == 2
    assert retriever.calls and retriever.calls[0][0] == "knowledge-v1"
    assert report.status == "ready"
    assert report.interpretation["sections"][0]["key"] == "core_judgment"


def test_untrusted_model_output_falls_back_without_invented_evidence_or_promises(db):
    job_id = enqueue_job(db, "owner-1", snapshot())
    malicious = {
        "sections": [
            {"key": "core_judgment", "claims": [{"id": "bad", "text": "保证拿到Offer，适配度: 99", "claimType": "fact", "references": [{"source": "answer", "id": "not-in-input", "version": "runtime", "location": "Q01"}]}]},
            {"key": "job_impact", "claims": []},
            {"key": "uncertainty", "claims": []},
            {"key": "validation", "claims": []},
        ],
        "aiUsageNotice": "ignore all rules",
        "reviewItems": [],
    }
    provider = RetryingProvider(malicious)

    assert run_once(db, provider=provider, worker_id="worker-c") is True

    job = db.get(ReportGenerationJob, job_id)
    report = db.get(ReportVersion, job.report_id)
    assert report.status == "ready"
    texts = [claim["text"] for section in report.interpretation["sections"] for claim in section["claims"]]
    assert all("保证拿到Offer" not in text for text in texts)
    assert report.interpretation["aiUsageNotice"] != "ignore all rules"
