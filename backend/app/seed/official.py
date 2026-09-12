"""Validation and explicit local import for the source-backed evidence questionnaire."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentVersion, VersionPointer
from app.seed.questionnaire_source import build


EVIDENCE_POLICY = {
    "mode": "evidence_only",
    "numericScoring": "pending_method",
    "classification": "pending_method",
    "strategy": "pending_method",
    "evidenceStatuses": ["verified_result", "confirmed_self_report", "behavior", "preference", "missing", "conflict"],
    "transferDimensions": ["core_task", "industry_qualification", "hard_skill", "service_chain", "responsibility_environment"],
    "transferPriority": ["unknown", "high", "medium", "low"],
}


def validate_official_evidence(payload: dict[str, Any], source_path: Path) -> list[str]:
    errors: set[str] = set()
    if not isinstance(payload, dict):
        return ["PAYLOAD"]
    metadata = payload.get("metadata")
    questions = payload.get("questions")
    if not isinstance(metadata, dict) or metadata.get("mode") != "evidence_only" or metadata.get("synthetic") is not False or metadata.get("scoringStatus") != "pending_method":
        errors.add("METADATA")
    if not source_path.is_file() or not isinstance(metadata, dict) or metadata.get("sourceSha256") != hashlib.sha256(source_path.read_bytes()).hexdigest():
        errors.add("SOURCE_DIGEST")
    ids = [question.get("id") for question in questions if isinstance(question, dict)] if isinstance(questions, list) else []
    if not isinstance(questions, list) or len(questions) != 40 or ids != [f"Q{number:02d}" for number in range(1, 41)]:
        errors.add("QUESTION_SET")
    forbidden = {"weight", "score", "scoringAnchors", "talentTypes", "jobThresholds", "sampleAnswers"}
    question_items = questions if isinstance(questions, list) else []
    if forbidden.intersection(payload) or any(forbidden.intersection(question) for question in question_items if isinstance(question, dict)):
        errors.add("UNDEFINED_NUMERIC_METHOD")
    if source_path.is_file():
        try:
            expected = build(source_path)
        except (UnicodeDecodeError, ValueError):
            errors.add("SOURCE_MAPPING")
        else:
            if payload != expected:
                errors.add("SOURCE_MAPPING")
    return sorted(errors)


def import_official_evidence(
    db: Session,
    payload: dict[str, Any],
    *,
    source_path: Path,
    activate: bool = False,
) -> str:
    errors = validate_official_evidence(payload, source_path)
    if errors:
        raise ValueError("invalid official evidence asset: " + ",".join(errors))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    version_id = f"official-evidence-questions-{digest[:16]}"
    existing = db.get(ContentVersion, version_id)
    if existing is None:
        db.add(ContentVersion(
            id=version_id,
            kind="question",
            revision=f"evidence-{digest[:16]}",
            payload=payload,
            status="published",
            change_reason="Source-backed evidence-only questionnaire import",
        ))
        db.flush()
    rule_payload = {
        **EVIDENCE_POLICY,
        "sourceSha256": payload["metadata"]["sourceSha256"],
        "sourceSections": ["4", "6.3", "7.2", "8"],
    }
    rule_json = json.dumps(rule_payload, sort_keys=True, separators=(",", ":"))
    rule_digest = hashlib.sha256(rule_json.encode()).hexdigest()
    rule_id = f"official-evidence-rules-{rule_digest[:16]}"
    if db.get(ContentVersion, rule_id) is None:
        db.add(ContentVersion(
            id=rule_id,
            kind="rule",
            revision=f"evidence-{rule_digest[:16]}",
            payload=rule_payload,
            status="published",
            change_reason="Defined deterministic evidence policy import",
        ))
        db.flush()
    if activate:
        for kind, active_version_id in (("question", version_id), ("rule", rule_id)):
            pointer = db.execute(select(VersionPointer).where(VersionPointer.kind == kind)).scalar_one_or_none()
            if pointer is None:
                db.add(VersionPointer(id=str(uuid.uuid4()), kind=kind, version_id=active_version_id))
            else:
                pointer.version_id = active_version_id
        db.flush()
    return version_id
