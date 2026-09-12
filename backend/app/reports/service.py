from __future__ import annotations

import asyncio
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.provider import ProviderUnavailable
from app.contracts.report import Core, Decisions, Interpretation, SourceVersions
from app.jobs.store import claim_next_job, complete_job
from app.matching.service import build_decisions
from app.models import ActionItem, EvidenceItem, GenerationAttempt, JobMatch as JobMatchRecord, ReportGenerationJob, ReportVersion
from app.scoring.service import build_core, score_answers


_PROMISE_RE = re.compile(
    r"(保证|必然|一定|100\s*%|\b\d{2,3}\s*%|拿到.?offer|offer率|绩效提升|"
    r"(?:适配度|匹配度|胜任度|得分|分数|评分)\s*[:：=]?\s*\d{1,3})",
    re.I,
)
_SECTION_KEYS = ["core_judgment", "job_impact", "uncertainty", "validation"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sync(value: Any) -> Any:
    if not asyncio.iscoroutine(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    # run_once is synchronous by contract. A worker thread keeps it usable
    # when called from an async host without nesting an event loop.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, value).result()


def _claim(identifier: str, text: str, kind: str = "recommendation", refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"id": identifier, "text": text, "claimType": kind, "references": refs or []}


def _fallback(core: dict[str, Any], decisions: dict[str, Any], notice: str) -> dict[str, Any]:
    refs = []
    for claim in core.get("judgments", []):
        refs.extend(claim.get("references", []))
    state = core.get("keySummaries", {}).get("state") or _claim("fallback-state", "当前结论基于已提交的证据。", "to_validate", refs)
    job_claim = _claim("fallback-job", "岗位影响需结合真实任务进一步验证。", "to_validate", refs)
    uncertainty = _claim("fallback-uncertainty", "当前报告不补造数值评分、人才类型或录用承诺。", "to_validate", [])
    validation = _claim("fallback-validation", "记录一次目标岗位相关任务结果并复盘。", "recommendation", refs)
    return {
        "sections": [
            {"key": "core_judgment", "claims": [state]},
            {"key": "job_impact", "claims": [job_claim]},
            {"key": "uncertainty", "claims": [uncertainty]},
            {"key": "validation", "claims": [validation]},
        ],
        "aiUsageNotice": notice,
        "reviewItems": ["报告内容请结合本人实际经历复核。"],
    }


def _validate_interpretation(raw: Any, snapshot: dict[str, Any], knowledge: list[dict[str, Any]], versions: dict[str, Any]) -> dict[str, Any] | None:
    try:
        parsed = Interpretation.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        return None
    answer_ids = set()
    evidence_ids = set()
    for item in snapshot.get("answers", []):
        if isinstance(item, dict):
            answer_ids.update(str(x) for x in (item.get("answerId"), item.get("id")) if x)
            evidence_ids.add(str(item.get("id")))
    knowledge_ids = {str(item.get("id")) for item in knowledge if item.get("id")}
    for section in parsed.sections:
        for claim in section.claims:
            if _PROMISE_RE.search(claim.text):
                return None
            for ref in claim.references:
                if ref.source == "answer" and ref.id not in answer_ids | evidence_ids:
                    return None
                if ref.source == "knowledge" and (ref.id not in knowledge_ids or ref.version != str(versions.get("knowledgeIndexVersion"))):
                    return None
                if ref.source == "method" and ref.version != str(versions.get("ruleVersion")):
                    return None
                if ref.source == "job_source" and (not ref.id or ref.version != str(versions.get("jobTemplateVersion"))):
                    return None
                if ref.source == "profile" and (not versions.get("profileSnapshotId") or ref.version != str(versions.get("profileSnapshotId"))):
                    return None
    return parsed.model_dump(mode="json")


def _next_report_version(db: Session, assessment_id: str) -> int:
    current = db.scalar(select(func.max(ReportVersion.version)).where(ReportVersion.assessment_id == assessment_id))
    return int(current or 0) + 1


def _persist_partitions(db: Session, report: ReportVersion, core: dict[str, Any], decisions: dict[str, Any], interpretation: dict[str, Any], snapshot: dict[str, Any]) -> None:
    report.core, report.decisions, report.interpretation = core, decisions, interpretation
    for evidence in core.get("evidence", []):
        record_id = f"{report.id}:evidence:{evidence['id']}"
        if not db.get(EvidenceItem, record_id):
            db.add(EvidenceItem(id=record_id, report_id=report.id, payload=deepcopy(evidence)))
    for match in decisions.get("jobMatches", []) + decisions.get("explicitTargets", []):
        record_id = f"{report.id}:job:{match['id']}"
        if not db.get(JobMatchRecord, record_id):
            db.add(JobMatchRecord(id=record_id, report_id=report.id, job_template_version_id=match.get("jobVersion"), match_status=match.get("evidenceStatus"), tier=None, tasks=match.get("tasks"), gaps=match.get("gaps"), risks=match.get("risks"), validation_task=match.get("validationTask"), industry_context=match.get("industryContext"), contract_version="v1", structured_payload=deepcopy(match)))
    for action in decisions.get("actions", []):
        record_id = f"{report.id}:action:{action['id']}"
        if not db.get(ActionItem, record_id):
            db.add(ActionItem(id=record_id, report_id=report.id, payload=deepcopy(action), status=action.get("status", "pending"), revision=0))


def run_once(db: Session, provider: Any = None, retriever: Any = None, worker_id: str = "report-worker") -> bool:
    job = claim_next_job(db, worker_id)
    if job is None:
        return False
    snapshot = deepcopy(job.input_snapshot)
    versions = SourceVersions.model_validate(snapshot["sourceVersions"]).model_dump(mode="json")
    report = None
    try:
        report = db.get(ReportVersion, job.report_id) if job.report_id else None
        if report is None:
            report = ReportVersion(id=str(uuid.uuid4()), owner_id=job.owner_id, assessment_id=job.assessment_id, version=_next_report_version(db, job.assessment_id), demo=bool(snapshot.get("contentBundle", {}).get("metadata", {}).get("mode") == "demo"), status="generating", review_status="pending", input_hash=job.input_hash, question_version_id=versions["questionVersion"], rule_version_id=versions["ruleVersion"], job_template_version_id=versions["jobTemplateVersion"], knowledge_index_version_id=versions["knowledgeIndexVersion"], prompt_version_id=versions["promptVersion"], model_name=versions["modelName"], embedding_model_version=versions["embeddingModelVersion"], profile_snapshot_id=versions.get("profileSnapshotId"))
            db.add(report)
            db.flush()
            job.report_id = report.id
            db.commit()

        rules = snapshot.get("sourcePayloads", {}).get("rules", {})
        scored = score_answers(snapshot.get("answers", []), rules)
        core = build_core(scored)
        Core.model_validate(core)
        templates = snapshot.get("sourcePayloads", {}).get("jobTemplates", []) or []
        decisions = build_decisions(core, templates, explicit_target_ids=snapshot.get("explicitTargetIds"))
        Decisions.model_validate(decisions)
        knowledge: list[dict[str, Any]] = []
        if retriever is not None:
            query = " ".join(str(item.get("quote", "")) for item in snapshot.get("answers", []) if isinstance(item, dict))[:2000]
            result = _sync(retriever.retrieve(versions["knowledgeIndexVersion"], query, [], limit=6))
            knowledge = [dict(item) for item in (result or [])[:6] if isinstance(item, dict)]
        interpretation = None
        attempts = 0
        for attempt_no in (1, 2):
            if provider is None:
                break
            attempts = attempt_no
            attempt = GenerationAttempt(id=str(uuid.uuid4()), job_id=job.id, attempt_number=attempt_no, status="running")
            db.add(attempt)
            db.commit()
            try:
                generation_payload = {
                    "sourceVersions": deepcopy(versions),
                    "core": deepcopy(core),
                    "decisions": deepcopy(decisions),
                    "answers": deepcopy(snapshot.get("answers", [])),
                    "knowledge": deepcopy(knowledge),
                    "prompt": deepcopy(snapshot.get("sourcePayloads", {}).get("prompt", {})),
                }
                raw = _sync(provider.generate_report(generation_payload))
                interpretation = _validate_interpretation(raw, snapshot, knowledge, versions)
                attempt.status = "succeeded" if interpretation else "rejected"
                if interpretation:
                    db.commit()
                    break
                attempt.error_code = "REFERENCE_INVALID"
            except Exception as exc:
                attempt.status = "failed"
                attempt.error_code = "PROVIDER_UNAVAILABLE" if isinstance(exc, ProviderUnavailable) else "GENERATION_FAILED"
            db.commit()
        if interpretation is None:
            interpretation = _fallback(core, decisions, "AI 服务当前不可用或输出未通过校验，以下为规则模板解释，请人工复核。")
        Interpretation.model_validate(interpretation)
        _persist_partitions(db, report, core, decisions, interpretation, snapshot)
        report.status = "ready"
        db.commit()
        complete_job(db, job.id, worker_id, job.lease_token, report.id)
        db.commit()
        return True
    except Exception:
        db.rollback()
        if report is not None:
            report.status = "partial" if report.core else "failed"
            db.add(report)
        current = db.get(ReportGenerationJob, job.id)
        if current is not None:
            current.status = "failed"
            current.error_code = "REPORT_GENERATION_FAILED"
            current.lease_owner = None
            current.lease_until = None
        db.commit()
        return True
