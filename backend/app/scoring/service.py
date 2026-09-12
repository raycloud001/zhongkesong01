"""Evidence normalization and deterministic coverage calculations.

The input to this module is deliberately permissive because Task 5b stores
answers as JSON and later tasks may add a confirmed profile/fact envelope.
The output is conservative: only explicitly supplied provenance is retained,
no free text is converted into a task, and no numeric aptitude score is
invented while the scoring anchors are pending.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_STATUSES = {
    "verified_result",
    "confirmed_self_report",
    "behavior",
    "preference",
    "missing",
    "conflict",
}
BEHAVIOR_STATUSES = {"verified_result", "confirmed_self_report", "behavior"}
VERIFIED_STATUSES = {"verified_result"}
_STATUS_ALIASES = {
    "verified": "verified_result",
    "verified_result": "verified_result",
    "result": "verified_result",
    "confirmed": "confirmed_self_report",
    "self_report": "confirmed_self_report",
    "confirmed_self_report": "confirmed_self_report",
    "behavior": "behavior",
    "behaviour": "behavior",
    "preference": "preference",
    "prefer": "preference",
    "missing": "missing",
    "unknown": "missing",
    "conflict": "conflict",
}
_CANDIDATE_STATUSES = {"candidate", "suggestion", "semantic_candidate", "proposed"}
_Q39 = "Q39"
_OFFICIAL_BEHAVIOR_QUESTIONS = {"Q15", "Q20"}
_OFFICIAL_SELF_REPORT_QUESTIONS = {"Q27", "Q30", "Q31", "Q37"}
_RAW_MAPPING_GATED_QUESTIONS = {"Q27", "Q30", "Q31", "Q37"}
_TARGET_ONLY_QUESTIONS = {"Q38"}


def _canonical(value: Any) -> Any:
    """Return a stable, JSON-compatible representation for hashing."""

    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_canonical(item) for item in value]
        # Lists in answers can be order-sensitive (e.g. a selected sequence),
        # so only sets are sorted.  Callers that need order-insensitivity sort
        # at the boundary before invoking this helper.
        return values
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return re.sub(r"\s+", " ", text).strip().lower()


def _digest(prefix: str, value: Any) -> str:
    payload = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return [value]


def _answer_items(answers: Any) -> list[dict[str, Any]]:
    """Unwrap the few envelopes used by the session/profile layers."""

    if answers is None:
        return []
    if isinstance(answers, Mapping):
        for key in ("answers", "facts", "evidence", "items"):
            value = answers.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
        # A single normalized fact is also a valid input.
        return [dict(answers)]
    return [dict(item) for item in answers if isinstance(item, Mapping)]


def _raw_status(item: Mapping[str, Any], question_id: str | None) -> str:
    value = item.get("sourceStatus", item.get("source_status", item.get("status")))
    if value is None:
        # Raw question answers are clues, never implicit verified results.  The
        # few structured evidence questions are retained as self-report;
        # situational answers remain preference/behavior clues only when the
        # caller explicitly labels them.
        if question_id in _OFFICIAL_BEHAVIOR_QUESTIONS:
            return "behavior"
        if question_id in _OFFICIAL_SELF_REPORT_QUESTIONS:
            return "confirmed_self_report"
        if question_id == _Q39:
            return "preference"
        return "preference"
    normalized = _STATUS_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())
    if normalized in _CANDIDATE_STATUSES:
        return normalized
    return normalized if normalized in EVIDENCE_STATUSES else "missing"


def _question_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("questionId", item.get("question_id", item.get("question")))
    return str(value) if value is not None else None


def _answer_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("answerId", item.get("answer_id", item.get("id")))
    return str(value) if value is not None else None


def _task_ids(item: Mapping[str, Any]) -> list[str]:
    value = item.get("taskIds", item.get("task_ids", item.get("tasks")))
    output: list[str] = []
    for task in _as_list(value):
        if isinstance(task, Mapping):
            task = task.get("id", task.get("taskId"))
        if task is not None and str(task).strip():
            output.append(str(task))
    return sorted(set(output))


def _confirmed_task_mapping(item: Mapping[str, Any]) -> bool:
    """Return whether a caller explicitly confirmed a task mapping.

    Raw questionnaire answers are not allowed to promote a free-text answer
    into structured task evidence.  Normalized facts use ``fact_key`` /
    ``claim_hash`` as their identity and are already an explicit mapping
    envelope; questionnaire records may opt in with a confirmation marker.
    """

    for key in (
        "taskMappingConfirmed",
        "task_mapping_confirmed",
        "mappingConfirmed",
        "mapping_confirmed",
        "confirmedMapping",
        "confirmed_mapping",
        "normalizedFact",
        "normalized_fact",
    ):
        if item.get(key) is True:
            return True
    for key in ("mappingStatus", "mapping_status"):
        if str(item.get(key, "")).strip().lower() in {"confirmed", "verified"}:
            return True
    return False


def _evidence_task_ids(item: Mapping[str, Any], question_id: str | None) -> list[str]:
    task_ids = _task_ids(item)
    if not task_ids:
        return []
    # Q38 is a target-calibration answer, never a competence fact.
    if question_id in _TARGET_ONLY_QUESTIONS:
        return []
    # Raw experience/tool/transfer answers need an explicit confirmation
    # before their task labels can affect coverage or matching.  A structured
    # fact without a question id is the normalized input form used by the
    # profile/evidence layers and may carry its declared task ids.
    if question_id in _RAW_MAPPING_GATED_QUESTIONS and not (
        _confirmed_task_mapping(item)
        or any(key in item for key in ("fact_key", "factKey", "claim_hash", "claimHash", "factComponents", "fact_components"))
    ):
        return []
    return task_ids


def _quote(item: Mapping[str, Any]) -> str:
    value = item.get("quote", item.get("text", item.get("content")))
    if value is None:
        value = item.get("value", item.get("answer"))
    if isinstance(value, Mapping):
        return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"))
    return "" if value is None else str(value)


def _claim_payload(item: Mapping[str, Any]) -> Any:
    claim = item.get("claim")
    if claim is not None:
        return claim
    # These are the only fields that may identify a normalized fact.  We do
    # not infer a task from prose and we intentionally omit question ids from
    # this payload when an explicit claim hash was supplied.
    fields = {}
    for key in (
        "action",
        "actions",
        "result",
        "outcome",
        "responsibility",
        "scope",
        "role",
        "timeWindow",
        "time_window",
    ):
        if key in item:
            fields[key] = item[key]
    return fields or _quote(item)


def _fact_key(item: Mapping[str, Any], task_ids: Sequence[str], claim_hash: str) -> str | None:
    explicit = item.get("fact_key", item.get("factKey"))
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    # A normalized profile fact may provide components instead of a key.
    components = item.get("factComponents") or item.get("fact_components")
    if isinstance(components, Mapping):
        values = [components.get(name) for name in ("userId", "projectId", "taskId", "timeWindow")]
        if any(value not in (None, "") for value in values):
            return ":".join(_normalize_text(value) for value in values)
    # Raw answers are question-specific facts.  Giving each one a question
    # namespace prevents Q07 and Q40 from becoming a false conflict.
    question_id = _question_id(item)
    if question_id:
        return f"answer:{question_id}:{claim_hash}"
    if task_ids:
        return f"task:{','.join(sorted(task_ids))}:{claim_hash}"
    return None


def _claim_hash(item: Mapping[str, Any], question_id: str | None) -> str:
    explicit = item.get("claim_hash", item.get("claimHash"))
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    payload = _claim_payload(item)
    # Raw answers from different questions are intentionally distinct even if
    # their visible text happens to match.
    if question_id and "claim" not in item and not any(key in item for key in ("action", "result", "responsibility", "scope", "role")):
        payload = {"questionId": question_id, "value": payload}
    return _digest("claim", payload)


def _source_ids(item: Mapping[str, Any], answer_id: str | None) -> list[str]:
    values = item.get("sourceIds", item.get("source_ids"))
    ids = [str(value) for value in _as_list(values) if value not in (None, "")]
    if answer_id:
        ids.append(answer_id)
    return sorted(set(ids))


def _verification_source(item: Mapping[str, Any]) -> str | None:
    value = item.get("verificationSource", item.get("verification_source"))
    if value is None:
        value = item.get("verifier", item.get("verifiedBy"))
    if isinstance(value, Mapping):
        value = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value) if value not in (None, "") else None


def _normalize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    question_id = _question_id(item)
    answer_id = _answer_id(item)
    task_ids = _evidence_task_ids(item, question_id)
    claim_hash = _claim_hash(item, question_id)
    explicit_claim_fields = item.get("claim") is not None or any(
        key in item for key in ("action", "actions", "result", "outcome", "responsibility", "scope", "role")
    )
    claim_signature = _digest("claim-sig", _claim_payload(item)) if explicit_claim_fields else None
    fact_key = _fact_key(item, task_ids, claim_hash)
    status = _raw_status(item, question_id)
    # Explicit empty/skip markers are missing evidence, never a negative
    # ability score.  A caller can still override this with a normalized
    # sourceStatus when a real source exists.
    value = item.get("value", item.get("answer"))
    value_marker = _normalize_text(value)
    quote_marker = _normalize_text(item.get("quote", item.get("text", item.get("content"))))
    missing_marker = value_marker in {"", "暂无", "跳过", "缺失", "missing", "skip"} or quote_marker in {"暂无", "跳过", "缺失", "missing", "skip"}
    # Q15/Q20 encode the no-experience option as E/D respectively.  The
    # option is a missing-evidence marker, not a low ability result.
    if question_id == "Q15" and (value == ["E"] or value == "E"):
        missing_marker = True
    if question_id == "Q20" and value == "D":
        missing_marker = True
    if "sourceStatus" not in item and "source_status" not in item and missing_marker:
        status = "missing"
    return {
        "id": str(item.get("id") or answer_id or _digest("evidence", {"factKey": fact_key, "claimHash": claim_hash})),
        "questionId": question_id,
        "answerId": answer_id,
        "quote": _quote(item),
        "taskIds": task_ids,
        "sourceStatus": status,
        "verificationSource": _verification_source(item),
        "gaps": sorted({str(gap) for gap in _as_list(item.get("gaps")) if gap not in (None, "")}),
        "conflictGroupId": None,
        "fact_key": fact_key,
        "claim_hash": claim_hash,
        "factKey": fact_key,
        "claimHash": claim_hash,
        "claimSignature": claim_signature,
        "sourceIds": _source_ids(item, answer_id),
        "claim": deepcopy(item.get("claim")) if item.get("claim") is not None else None,
        "rawStatus": item.get("status") if item.get("status") in _CANDIDATE_STATUSES else None,
    }


def _union_find(size: int) -> tuple[list[int], Any]:
    parent = list(range(size))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    return parent, (find, union)


def _merge_group(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(items, key=lambda value: (str(value.get("id", "")), str(value.get("answerId", ""))))
    primary = ordered[0]
    statuses = [item["sourceStatus"] for item in ordered]
    # Explicit verification provenance is required before accepting the
    # verified_result label.  This blocks a raw self-report from silently
    # becoming a verified result while still accepting a source-backed fact.
    if "conflict" in statuses:
        status = "conflict"
    elif any(status == "verified_result" and item.get("verificationSource") for status, item in zip(statuses, ordered)):
        status = "verified_result"
    else:
        precedence = ["confirmed_self_report", "behavior", "preference", "missing"]
        status = next((candidate for candidate in precedence if candidate in statuses), "missing")
    return {
        **primary,
        "id": str(primary["id"]),
        "questionId": next((item["questionId"] for item in ordered if item["questionId"] is not None), None),
        "answerId": next((item["answerId"] for item in ordered if item["answerId"] is not None), None),
        "quote": next((item["quote"] for item in ordered if item["quote"]), ""),
        "taskIds": sorted({task for item in ordered for task in item["taskIds"]}),
        "sourceStatus": status,
        "verificationSource": next((item["verificationSource"] for item in ordered if item["verificationSource"]), None),
        "gaps": sorted({gap for item in ordered for gap in item["gaps"]}),
        "conflictGroupId": None,
        "sourceIds": sorted({source for item in ordered for source in item["sourceIds"]}),
        "sourceItems": [item["id"] for item in ordered],
        "claim": next((item["claim"] for item in ordered if item.get("claim") is not None), None),
        "claimSignature": next((item["claimSignature"] for item in ordered if item.get("claimSignature")), None),
    }


def deduplicate_evidence(answers: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize, deduplicate and conflict-group evidence.

    Returns ``(evidence, candidates)``.  Candidates are intentionally kept
    separate so a later AI task can display them without allowing them into
    deterministic coverage calculations.
    """

    raw_items = [_normalize_item(item) for item in _answer_items(answers)]
    candidates = [item for item in raw_items if item["sourceStatus"] in _CANDIDATE_STATUSES or item.get("rawStatus")]
    formal = [item for item in raw_items if item not in candidates]
    if not formal:
        return [], sorted(candidates, key=lambda item: str(item["id"]))

    parent, (find, union) = _union_find(len(formal))
    by_identity: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(formal):
        # The source rule defines a duplicate as the same fact_key *and* the
        # same claim_hash.  A hash is not globally unique: the same action
        # summary can legitimately occur in different projects or time
        # windows.  Unkeyed records have no safe fact identity, so they only
        # merge when they carry the same source answer id.
        fact_key = item.get("fact_key")
        identity_key = fact_key or f"unkeyed:{item.get('answerId') or item.get('id')}"
        by_identity[(identity_key, item["claim_hash"], "fact" if fact_key else "source")].append(index)
    for indexes in by_identity.values():
        for index in indexes[1:]:
            union(indexes[0], index)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, item in enumerate(formal):
        grouped[find(index)].append(item)
    merged = [_merge_group(items) for _, items in sorted(grouped.items(), key=lambda pair: min(str(i["id"]) for i in pair[1]))]

    fact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in merged:
        if item.get("fact_key"):
            fact_groups[item["fact_key"]].append(item)
    for fact_key, groups in fact_groups.items():
        claim_signatures = {
            (group["claim_hash"], group.get("claimSignature"))
            for group in groups
        }
        if len(claim_signatures) < 2:
            continue
        conflict_id = _digest("conflict", fact_key)
        for group in groups:
            group["sourceStatus"] = "conflict"
            group["conflictGroupId"] = conflict_id

    merged.sort(key=lambda item: (str(item.get("id", "")), str(item.get("fact_key", "")), str(item.get("claim_hash", ""))))
    candidates.sort(key=lambda item: str(item.get("id", "")))
    return merged, candidates


def normalize_evidence(answers: Any) -> list[dict[str, Any]]:
    """Public normalization API returning deterministic evidence only."""

    return deduplicate_evidence(answers)[0]


def _target_task_ids(core_tasks: Any) -> list[str]:
    if isinstance(core_tasks, Mapping):
        for key in ("coreTasks", "core_tasks", "tasks", "targetTasks", "target_tasks"):
            if key in core_tasks:
                return _target_task_ids(core_tasks[key])
        return []
    result: list[str] = []
    for task in _as_list(core_tasks):
        if isinstance(task, Mapping):
            if task.get("core") is False or task.get("isCore") is False:
                continue
            task = task.get("id", task.get("taskId"))
        if task not in (None, ""):
            result.append(str(task))
    return sorted(set(result))


def compute_task_coverage(evidence: Sequence[Mapping[str, Any]], core_tasks: Any) -> dict[str, float | None]:
    """Compute self-report/behavior and verified coverage by unique task.

    ``behavior`` includes explicit behavior, confirmed self-report and
    verified results.  Preferences and missing/conflict records never count;
    they can support an ``explore`` direction but cannot establish task
    competence.  Ratios are in ``0..1`` and ``None`` when no target tasks are
    supplied.
    """

    target_ids = set(_target_task_ids(core_tasks))
    if not target_ids:
        return {"behavior": None, "verified": None}
    behavior_tasks: set[str] = set()
    verified_tasks: set[str] = set()
    behavior_evidence_seen = False
    verified_evidence_seen = False
    for item in evidence:
        status = item.get("sourceStatus", item.get("source_status"))
        if status in {"conflict", "missing", "preference"}:
            continue
        tasks = set(_task_ids(item)) & target_ids
        if status in BEHAVIOR_STATUSES:
            if tasks:
                behavior_evidence_seen = True
            behavior_tasks.update(tasks)
        if status in VERIFIED_STATUSES:
            if tasks:
                verified_evidence_seen = True
            verified_tasks.update(tasks)
    denominator = len(target_ids)
    return {
        "behavior": min(1.0, len(behavior_tasks) / denominator) if behavior_evidence_seen else None,
        "verified": min(1.0, len(verified_tasks) / denominator) if verified_evidence_seen else None,
    }


def _reference(evidence: Mapping[str, Any], *, version: str = "runtime") -> dict[str, Any]:
    return {
        "source": "answer",
        "id": str(evidence.get("answerId") or evidence.get("id")),
        "version": version,
        "location": evidence.get("questionId"),
    }


def _claim(identifier: str, text: str, claim_type: str, evidence: Sequence[Mapping[str, Any]], *, version: str = "runtime") -> dict[str, Any]:
    references = []
    for item in evidence:
        source_ids = item.get("sourceIds") or [item.get("answerId") or item.get("id")]
        for source_id in sorted({str(value) for value in source_ids if value not in (None, "")}):
            source_item = dict(item)
            source_item["answerId"] = source_id
            references.append(_reference(source_item, version=version))
    return {
        "id": identifier,
        "text": text,
        "claimType": claim_type,
        "references": references,
        # Kept for consumers of the scoring service that have not migrated to
        # the Ref shape yet; build_core strips this compatibility key.
        "evidenceIds": [str(item.get("id")) for item in evidence],
    }


def _contract_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "questionId",
        "answerId",
        "quote",
        "taskIds",
        "sourceStatus",
        "verificationSource",
        "gaps",
        "conflictGroupId",
    )
    return {key: deepcopy(item.get(key)) for key in allowed}


def score_answers(answers: Any, rule: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Produce the evidence-first deterministic scoring payload.

    Numeric dimensions, radar values, talent type and strategy thresholds are
    deliberately absent/``None`` until the published scoring method supplies
    them.  ``rule`` may contain a task list and metadata, but is never treated
    as permission to infer facts from free prose.
    """

    rule = dict(rule or {})
    evidence, candidates = deduplicate_evidence(answers)
    tasks = _target_task_ids(rule)
    coverage = compute_task_coverage(evidence, tasks)
    conflict_groups = sorted({item["conflictGroupId"] for item in evidence if item.get("conflictGroupId")})
    q39_review = any(item.get("questionId") == _Q39 for item in evidence)
    missing_answers = sorted(
        str(item.get("questionId"))
        for item in evidence
        if item.get("sourceStatus") == "missing" and item.get("questionId")
    )
    # Keep the output order independent from input order.  This is useful for
    # reproducible report generation and idempotent queue retries.
    evidence = sorted(evidence, key=lambda item: str(item["id"]))
    judgments = []
    for item in evidence:
        if item["sourceStatus"] == "conflict":
            text = "同一事实存在互斥陈述，需澄清后再判断。"
            claim_type = "to_validate"
        elif item["sourceStatus"] in {"verified_result", "behavior", "confirmed_self_report"}:
            text = "该任务有用户提供的经历证据，核验范围仍需按来源确认。"
            claim_type = "fact"
        elif item["sourceStatus"] == "preference":
            text = "该记录是偏好线索，不能单独证明任务胜任。"
            claim_type = "inference"
        else:
            text = "该信息缺失，暂不能判断。"
            claim_type = "to_validate"
        judgments.append(_claim(f"judgment-{item['id']}", text, claim_type, [item], version=str(rule.get("version", "runtime"))))

    result = {
        "type": None,
        "radar": None,
        "evidence": [_contract_evidence(item) for item in evidence],
        "evidenceLedger": evidence,
        "candidateEvidence": candidates,
        "taskCoverage": coverage,
        "judgments": judgments,
        "quality": {
            "missingAnswers": missing_answers,
            "conflictGroups": conflict_groups,
            "q39ReviewRequired": q39_review,
            "q39PenaltyApplied": False,
            "consent": bool(rule.get("consent", True)),
        },
        "numericScoringStatus": "pending_method",
        "classificationStatus": "pending_method",
        "strategyStatus": "pending_method",
    }
    # Consumers at the report boundary can use this directly; keeping the
    # standalone fields above preserves the small score_answers API used by
    # earlier task prototypes.
    result["core"] = build_core(result)
    return result


def build_core(scored: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a scoring payload to the current ``Core`` report contract."""

    evidence = list(scored.get("evidence", []))
    ledger = list(scored.get("evidenceLedger", evidence))
    usable = [item for item in ledger if item.get("sourceStatus") in BEHAVIOR_STATUSES]
    conflicted = [item for item in ledger if item.get("sourceStatus") == "conflict"]
    version = str(scored.get("ruleVersion", "runtime"))
    if usable:
        state = _claim("core-state", "当前报告基于已提供的任务证据，仍需按来源范围理解。", "fact", usable, version=version)
        advantage = _claim("core-advantage", "已有任务证据可用于进一步比较目标岗位。", "inference", usable, version=version)
    else:
        state = _claim("core-state", "暂无足够证据形成当前任务判断。", "to_validate", [], version=version)
        advantage = _claim("core-advantage", "补充一个可追溯任务结果后再比较岗位。", "recommendation", [], version=version)
    if conflicted:
        risk = _claim("core-risk", "存在互斥事实，需先完成澄清。", "to_validate", conflicted, version=version)
    else:
        # The risk statement remains provisional, but cites the same supplied
        # evidence so consumers can inspect the basis instead of treating it
        # as an unsupported personality judgement.
        risk = _claim("core-risk", "暂无足够证据判断风险边界。", "to_validate", usable, version=version)
    def strip_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
        return {key: deepcopy(value) for key, value in claim.items() if key != "evidenceIds"}

    judgments = [strip_claim(claim) for claim in scored.get("judgments", [])]
    return {
        "type": None,
        "keySummaries": {
            "state": strip_claim(state),
            "advantage": strip_claim(advantage),
            "risk": strip_claim(risk),
        },
        "radar": None,
        "evidence": [_contract_evidence(item) if any(key in item for key in ("fact_key", "claim_hash", "sourceIds")) else deepcopy(item) for item in evidence],
        "strengths": [],
        "weaknesses": [],
        "risk": strip_claim(risk) if conflicted else None,
        "judgments": judgments,
    }


# Backwards-compatible aliases used by early Task 6 prototypes.
normalize_facts = normalize_evidence
calculate_task_coverage = compute_task_coverage
