import hashlib
import json
import math
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentVersion, VersionPointer


QUESTION_TYPES = {"single", "multiple", "scale", "experience"}


def validate_seed(payload: dict[str, Any]) -> list[str]:
    errors: set[str] = set()
    questions = payload.get("questions")
    dimensions = payload.get("dimensions")
    jobs = payload.get("jobTemplates")
    rules = payload.get("rules")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        errors.add("METADATA")
    if not isinstance(questions, list) or len(questions) != 40:
        errors.add("QUESTION_COUNT")
    if not isinstance(dimensions, list) or not dimensions:
        errors.add("DIMENSIONS")
        dimension_ids: set[str] = set()
    else:
        valid_dimension_ids = [
            item.get("id") for item in dimensions
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        ]
        dimension_ids = set(valid_dimension_ids)
        if len(dimension_ids) != len(dimensions):
            errors.add("DIMENSION_ID")
    if not isinstance(jobs, list) or not jobs or any(
        not isinstance(job, dict) or not isinstance(job.get("id"), str) or not job.get("id")
        or not isinstance(job.get("name"), str) or not job.get("name")
        or not isinstance(job.get("tasks"), list)
        or not isinstance(job.get("capabilities"), list)
        or any(ref not in dimension_ids for ref in job.get("capabilities", []))
        for job in jobs if isinstance(jobs, list)
    ):
        errors.add("JOB_TEMPLATES")
    if not isinstance(rules, dict):
        errors.add("RULES")
    seen: set[str] = set()
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict):
            errors.add("QUESTION_ID")
            continue
        question_id = question.get("id")
        if not isinstance(question_id, str) or not question_id or question_id in seen:
            errors.add("QUESTION_ID")
        else:
            seen.add(question_id)
        if not isinstance(question.get("text"), str) or not question.get("text") or not isinstance(question.get("required"), bool) or not isinstance(question.get("reverse"), bool):
            errors.add("QUESTION_FIELDS")
        kind = question.get("type")
        if not isinstance(kind, str) or kind not in QUESTION_TYPES:
            errors.add("QUESTION_TYPE")
        weight = question.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or not 0 < weight <= 1:
            errors.add("WEIGHT_RANGE")
        refs = question.get("dimensionIds")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in dimension_ids for ref in refs):
            errors.add("DIMENSION_REFERENCE")
        if kind == "scale" and not (
            isinstance(question.get("min"), (int, float)) and not isinstance(question.get("min"), bool)
            and isinstance(question.get("max"), (int, float)) and not isinstance(question.get("max"), bool)
            and math.isfinite(question["min"]) and math.isfinite(question["max"])
            and question["min"] < question["max"]
        ):
            errors.add("QUESTION_RANGE")
        options_for_range = question.get("options")
        if kind == "multiple" and not (
            isinstance(options_for_range, list)
            and
            isinstance(question.get("minSelections"), int)
            and isinstance(question.get("maxSelections"), int)
            and 0 <= question["minSelections"] <= question["maxSelections"] <= len(options_for_range)
        ):
            errors.add("QUESTION_RANGE")
        if kind == "experience" and (not isinstance(question.get("maxLength"), int) or isinstance(question.get("maxLength"), bool) or question["maxLength"] <= 0):
            errors.add("QUESTION_RANGE")
        if isinstance(kind, str) and kind in {"single", "multiple"}:
            options = question.get("options")
            valid_options = isinstance(options, list) and bool(options) and all(
                isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
                and isinstance(item.get("label"), str) and item.get("label") for item in options
            )
            option_ids = [item["id"] for item in options] if valid_options else []
            if not valid_options or len(set(option_ids)) != len(option_ids):
                errors.add("QUESTION_OPTIONS")
    anchors = rules.get("scoringAnchors") if isinstance(rules, dict) else None
    question_ids = {item.get("id") for item in questions if isinstance(item, dict) and isinstance(item.get("id"), str)} if isinstance(questions, list) else set()
    valid_anchors = isinstance(anchors, list) and len(anchors) == 40 and all(
        isinstance(anchor, dict)
        and isinstance(anchor.get("id"), str) and anchor.get("id")
        and anchor.get("questionId") in question_ids
        and isinstance(anchor.get("method"), str) and anchor.get("method")
        and isinstance(anchor.get("range"), list) and len(anchor["range"]) == 2
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in anchor["range"])
        and anchor["range"][0] < anchor["range"][1]
        for anchor in anchors if isinstance(anchors, list)
    )
    if valid_anchors:
        anchor_ids = [anchor["id"] for anchor in anchors]
        anchor_question_ids = [anchor["questionId"] for anchor in anchors]
        valid_anchors = (
            len(set(anchor_ids)) == len(anchor_ids)
            and len(set(anchor_question_ids)) == len(anchor_question_ids)
            and set(anchor_question_ids) == question_ids
        )
    if anchors is not None and not valid_anchors:
        errors.add("SCORING_ANCHORS")
    talent_types = payload.get("talentTypes")
    if not isinstance(talent_types, list) or not talent_types or any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str) or not item.get("id")
        or not isinstance(item.get("name"), str) or not item.get("name")
        or not isinstance(item.get("dimensionIds"), list) or not item.get("dimensionIds")
        or any(ref not in dimension_ids for ref in item.get("dimensionIds", []))
        for item in talent_types if isinstance(talent_types, list)
    ):
        errors.add("TALENT_TYPES")
    sample_answers = payload.get("sampleAnswers")
    if not isinstance(sample_answers, list) or len(sample_answers) < 2:
        errors.add("SAMPLE_ANSWERS")
    else:
        for sample in sample_answers:
            answers = sample.get("answers") if isinstance(sample, dict) else None
            answer_ids = [answer.get("questionId") for answer in answers if isinstance(answer, dict)] if isinstance(answers, list) else []
            if (
                not isinstance(sample, dict)
                or not isinstance(sample.get("ownerId"), str) or not sample.get("ownerId")
                or not isinstance(answers, list) or len(answers) != 40
                or len(answer_ids) != 40 or len(set(answer_ids)) != 40 or set(answer_ids) != question_ids
                or any("value" not in answer for answer in answers if isinstance(answer, dict))
            ):
                errors.add("SAMPLE_ANSWERS")
    if isinstance(metadata, dict) and metadata.get("mode") == "production" and metadata.get("expertConfirmed") is True:
        nested_synthetic = any(
            isinstance(item, dict) and item.get("synthetic") is True
            for collection in (anchors, jobs, talent_types)
            for item in (collection if isinstance(collection, list) else [])
        )
        if metadata.get("synthetic") is not False or not isinstance(rules, dict) or rules.get("demo") is not False or nested_synthetic:
            errors.add("PRODUCTION_SYNTHETIC")
        if not valid_anchors:
            errors.add("SCORING_ANCHORS")
    return sorted(errors)


def import_seed(db: Session, payload: dict[str, Any], mode: str) -> str:
    errors = validate_seed(payload)
    if errors:
        raise ValueError("invalid seed: " + ",".join(errors))
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("invalid seed: METADATA")
    if mode == "production" and (metadata.get("mode") != "production" or metadata.get("expertConfirmed") is not True):
        raise ValueError("production import requires expert-confirmed production content")
    if mode not in {"demo", "production"}:
        raise ValueError("mode must be demo or production")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    revision = f"{mode}-{digest[:16]}"
    existing = db.execute(
        select(ContentVersion).where(ContentVersion.kind == "question", ContentVersion.revision == revision)
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    version_id = f"{mode}-questions-{digest[:16]}"
    version = ContentVersion(
        id=version_id,
        kind="question",
        revision=revision,
        payload=payload,
        status="published",
        change_reason="Synthetic demo seed import" if mode == "demo" else "Expert-confirmed production seed import",
    )
    db.add(version)
    db.flush()
    pointer = db.execute(select(VersionPointer).where(VersionPointer.kind == "question")).scalar_one_or_none()
    if pointer is None:
        db.add(VersionPointer(id=str(uuid.uuid4()), kind="question", version_id=version_id))
        db.flush()
    return version_id
