"""Evidence-first job comparison.

This module deliberately does not rank people with a synthetic score.  It
compares explicit task evidence with versioned job requirements and keeps
unknowns visible.  It is safe to call with the JSON snapshots produced by
the assessment queue; no database or model provider is involved.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


_LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
_TRANSFER_KEYS = (
    "core_task",
    "industry_qualification",
    "hard_skill",
    "service_chain",
    "responsibility_environment",
)
_BEHAVIOR = {"verified_result", "confirmed_self_report", "behavior"}
_VERIFIED = {"verified_result"}
_CURRENT_EVIDENCE = {"verified_result", "behavior"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _str(value: Any, default: str = "") -> str:
    return default if value in (None, "") else str(value)


def _claim(identifier: str, text: str, kind: str, refs: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    return {
        "id": identifier,
        "text": text,
        "claimType": kind,
        "references": [dict(ref) for ref in refs],
    }


def _source_ref(job: Mapping[str, Any], *, location: str | None = None) -> dict[str, Any]:
    source_id = job.get("jobSourceId", job.get("job_source_id", job.get("sourceId")))
    version = job.get("jobVersion", job.get("job_version", job.get("version")))
    return {
        "source": "job_source",
        "id": _str(source_id, "unknown-job-source"),
        "version": _str(version, "unknown-job-version"),
        "location": location,
    }


def _evidence_ref(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": "answer",
        "id": _str(item.get("answerId", item.get("id")), "unknown-answer"),
        "version": _str(item.get("answerVersion", "runtime"), "runtime"),
        "location": item.get("questionId"),
    }


def _evidence_items(core: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = core.get("evidenceLedger", core.get("evidence", []))
    if isinstance(source, Mapping):
        source = source.get("items", [])
    result = []
    for item in _as_list(source):
        if isinstance(item, Mapping):
            result.append(dict(item))
    return sorted(result, key=lambda item: _str(item.get("id")))


def _task_ids(item: Mapping[str, Any]) -> set[str]:
    raw = item.get("taskIds", item.get("task_ids", item.get("tasks", [])))
    result: set[str] = set()
    for value in _as_list(raw):
        if isinstance(value, Mapping):
            value = value.get("id", value.get("taskId"))
        if value not in (None, ""):
            result.add(str(value))
    return result


def _job_tasks(job: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = job.get("tasks", job.get("coreTasks", job.get("taskIds", [])))
    result: list[dict[str, str]] = []
    for value in _as_list(raw):
        if isinstance(value, Mapping):
            identifier = value.get("id", value.get("taskId"))
            name = value.get("name", value.get("title", identifier))
            # Keep the core marker internally.  It is stripped before the
            # result crosses the JobMatch contract boundary.
            core = value.get("core", value.get("isCore", True)) is not False
        else:
            identifier, name = value, value
            core = True
        if identifier not in (None, ""):
            result.append({"id": str(identifier), "name": _str(name, str(identifier)), "_core": core})
    seen: set[str] = set()
    return [item for item in result if not (item["id"] in seen or seen.add(item["id"]))]


def _job_source_status(job: Mapping[str, Any]) -> str:
    explicit = _str(job.get("sourceStatus", job.get("source_status"))).lower()
    if explicit in {"verified", "template_provisional", "unknown"}:
        return explicit
    source_id = job.get("jobSourceId", job.get("job_source_id", job.get("sourceId")))
    version = job.get("jobVersion", job.get("job_version", job.get("version")))
    if source_id and version:
        return "verified"
    if job.get("template") or job.get("isTemplate") or job.get("roleTemplateId"):
        return "template_provisional"
    return "unknown"


def _requirements(job: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw: list[Any] = []
    raw.extend(_as_list(job.get("requirements", job.get("capabilityRequirements", []))))
    # Hard requirements are part of the same comparison, but retain their
    # hard_gate type even when the input omitted `type`.
    for value in _as_list(job.get("hardRequirements", job.get("hard_requirements", []))):
        if isinstance(value, Mapping):
            value = {**value, "type": value.get("type", value.get("requirementType", "hard_gate"))}
        else:
            value = {"id": value, "name": value, "type": "hard_gate"}
        raw.append(value)
    result: list[dict[str, Any]] = []
    for index, value in enumerate(raw):
        if not isinstance(value, Mapping):
            continue
        identifier = _str(value.get("id", value.get("requirementId")), f"requirement-{index + 1}")
        task_id = _str(value.get("taskId", value.get("task_id")))
        capability = _str(value.get("capabilityId", value.get("capability_id", value.get("capability"))), "unknown-capability")
        kind = _str(value.get("type", value.get("requirementType")), "core")
        if kind in {"hard", "gate", "hardRequirement"}:
            kind = "hard_gate"
        if kind not in {"hard_gate", "core", "bonus"}:
            kind = "core"
        level = _str(value.get("requiredLevel", value.get("required_level")), "unknown")
        if level not in _LEVELS:
            level = "unknown"
        result.append(
            {
                "id": identifier,
                "taskId": task_id,
                "capabilityId": capability,
                "type": kind,
                "requiredLevel": level,
                "sourceLocation": value.get("sourceLocation", value.get("location")),
                "name": _str(value.get("name", value.get("title")), identifier),
            }
        )
    result.sort(key=lambda item: item["id"])
    return result


def _observed_for(requirement: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    task_id = _str(requirement.get("taskId"))
    matched = [item for item in evidence if task_id and task_id in _task_ids(item)]
    ids = sorted({_str(item.get("id")) for item in matched if item.get("id")})
    if any(item.get("sourceStatus") == "conflict" for item in matched):
        return "unknown", "conflict", ids, matched
    explicit_levels = [item.get("observedLevel") for item in matched if item.get("observedLevel") in _LEVELS]
    observed = max(explicit_levels, key=lambda level: _LEVELS[level]) if explicit_levels else "unknown"
    required = requirement.get("requiredLevel", "unknown")
    if not matched:
        return observed, "unknown", ids, matched
    if required == "unknown" or observed == "unknown":
        if any(item.get("sourceStatus") == "behavior" for item in matched):
            return observed, "transfer_pending", ids, matched
        if any(item.get("sourceStatus") == "confirmed_self_report" for item in matched):
            return observed, "self_report_pending", ids, matched
        return observed, "unknown", ids, matched
    if any(item.get("sourceStatus") in _VERIFIED for item in matched) and _LEVELS[observed] >= _LEVELS[required]:
        return observed, "supported", ids, matched
    if _LEVELS[observed] < _LEVELS[required]:
        return observed, "gap", ids, matched
    return observed, "transfer_pending", ids, matched


def _hard_gate_status(
    requirement: Mapping[str, Any],
    observed: str,
    judgment: str,
    evidence: Sequence[Mapping[str, Any]],
    *,
    source_known: bool = True,
) -> str:
    # Without a task mapping the requirement cannot be compared to a user
    # fact.  It is unknown, even when the requirement text and level are
    # present; treating it as missing would incorrectly claim a known gap.
    if not _str(requirement.get("taskId")):
        return "unknown"
    # A requirement with no published level/source cannot be evaluated.
    if not source_known or requirement.get("requiredLevel") == "unknown":
        return "unknown"
    if judgment == "conflict":
        return "conflict"
    if judgment == "supported":
        return "met"
    if judgment == "gap":
        return "missing"
    matched = any(_str(requirement.get("taskId")) in _task_ids(item) for item in evidence)
    # A known gate with no evidence is an unmet gate, rather than an unknown
    # gate.  Unknown is reserved for an unpublishable requirement/source or a
    # supplied record that cannot be interpreted.
    if not matched:
        return "missing"
    return "unknown"


def _coverage(evidence: Sequence[Mapping[str, Any]], task_ids: Sequence[str]) -> dict[str, float | None]:
    target = set(task_ids)
    if not target:
        return {"behavior": None, "verified": None}
    behavior: set[str] = set()
    verified: set[str] = set()
    behavior_seen = verified_seen = False
    for item in evidence:
        overlap = _task_ids(item) & target
        status = item.get("sourceStatus")
        if not overlap or status in {"conflict", "missing", "preference"}:
            continue
        if status in _BEHAVIOR:
            behavior_seen = True
            behavior.update(overlap)
        if status in _VERIFIED:
            verified_seen = True
            verified.update(overlap)
    return {
        "behavior": len(behavior) / len(target) if behavior_seen else None,
        "verified": len(verified) / len(target) if verified_seen else None,
    }


def _transfer(evidence: Sequence[Mapping[str, Any]], requirements: Sequence[Mapping[str, Any]], tasks: Sequence[Mapping[str, Any]], *, provisional: bool, source_ref: Mapping[str, Any]) -> dict[str, Any]:
    task_ids = [task["id"] for task in tasks]
    core_task_set = set(task_ids)
    # Core-task evidence drives the reusable/validate-in-context dimension.
    # Requirement evidence is intentionally kept separate: a qualification or
    # hard-skill task can sit outside the core task list and still satisfy its
    # published requirement.
    task_evidence = [item for item in evidence if _task_ids(item) & core_task_set]
    requirement_evidence = list(evidence)
    conflict = any(item.get("sourceStatus") == "conflict" for item in task_evidence)
    verified = {task for item in task_evidence if item.get("sourceStatus") == "verified_result" for task in _task_ids(item)}
    behavioral = {task for item in task_evidence if item.get("sourceStatus") in _BEHAVIOR for task in _task_ids(item)}
    if conflict:
        core_status = "conflict"
    elif not task_ids:
        core_status = "unknown"
    elif verified >= set(task_ids):
        core_status = "reusable"
    elif behavioral:
        core_status = "validate_in_context"
    else:
        core_status = "unknown"
    gate_requirements = [req for req in requirements if req.get("type") == "hard_gate"]

    def requirement_state(requirement: Mapping[str, Any]) -> str:
        matched = [item for item in requirement_evidence if requirement.get("taskId") and requirement["taskId"] in _task_ids(item)]
        if any(item.get("sourceStatus") == "conflict" for item in matched):
            return "conflict"
        required = requirement.get("requiredLevel", "unknown")
        if required == "unknown":
            return "unknown"
        # A published hard gate with a concrete task mapping but no matching
        # evidence is a known qualification gap.  Keep it distinct from an
        # uninterpretable requirement: when the core task evidence is known,
        # this gap drives the transfer level to ``high``.  If the core task
        # itself is unknown, the outer precedence still returns ``unknown``.
        if not matched and requirement.get("type") == "hard_gate" and requirement.get("taskId"):
            return "training_needed"
        observed_values = [item.get("observedLevel") for item in matched if item.get("observedLevel") in _LEVELS]
        if not observed_values:
            return "unknown"
        observed = max(observed_values, key=lambda level: _LEVELS[level])
        if any(item.get("sourceStatus") == "verified_result" for item in matched) and _LEVELS[observed] >= _LEVELS[required]:
            return "supported"
        if _LEVELS[observed] < _LEVELS[required]:
            return "training_needed"
        return "validate_in_context"

    states = {str(req["id"]): requirement_state(req) for req in requirements}
    non_gate_requirements = [req for req in requirements if req.get("type") != "hard_gate"]

    def dimension_status(items: Sequence[Mapping[str, Any]]) -> str:
        values = [states[str(item["id"])] for item in items]
        if not values:
            return "reusable"
        if "conflict" in values:
            return "conflict"
        if "unknown" in values:
            return "unknown"
        if "training_needed" in values:
            return "training_needed"
        if any(value != "supported" for value in values):
            return "validate_in_context"
        return "reusable"

    if provisional or not requirements:
        industry_status = hard_status = "unknown"
    else:
        industry_status = dimension_status(gate_requirements)
        hard_status = dimension_status(non_gate_requirements)

    all_tasks_verified = bool(task_ids) and verified >= set(task_ids)
    service_status = "reusable" if all_tasks_verified else ("validate_in_context" if behavioral else "unknown")
    environment_status = "reusable" if all_tasks_verified else ("validate_in_context" if tasks and behavioral else "unknown")
    statuses = {
        "core_task": core_status,
        "industry_qualification": industry_status,
        "hard_skill": hard_status,
        "service_chain": service_status,
        "responsibility_environment": environment_status,
    }
    dimensions = []
    for key in _TRANSFER_KEYS:
        if key == "core_task":
            dimension_evidence = task_evidence
        elif key == "industry_qualification":
            dimension_requirements = [req for req in requirements if req.get("type") == "hard_gate"]
            dimension_evidence = [
                item
                for req in dimension_requirements
                for item in requirement_evidence
                if req.get("taskId") and req["taskId"] in _task_ids(item)
            ]
        elif key == "hard_skill":
            dimension_requirements = [req for req in requirements if req.get("type") != "hard_gate"]
            dimension_evidence = [
                item
                for req in dimension_requirements
                for item in requirement_evidence
                if req.get("taskId") and req["taskId"] in _task_ids(item)
            ]
        else:
            # These two dimensions are currently represented by the same
            # concrete task evidence; later method versions may add explicit
            # service/environment mappings without changing this contract.
            dimension_evidence = task_evidence
        dims_evidence = sorted({_str(item.get("id")) for item in dimension_evidence if item.get("id")})
        req_ids = [str(req["id"]) for req in requirements if (key == "hard_skill" and req.get("type") != "hard_gate") or (key == "industry_qualification" and req.get("type") == "hard_gate")]
        dimensions.append({"key": key, "status": statuses[key], "evidenceIds": dims_evidence, "requirementIds": sorted(req_ids), "references": [dict(source_ref)] if requirements else []})
    if provisional:
        level = "unknown"
    elif any(value in {"unknown", "conflict"} for value in statuses.values()):
        level = "unknown"
    elif any(value == "training_needed" for value in statuses.values()):
        level = "high"
    elif any(value == "validate_in_context" for value in statuses.values()):
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "provisional": provisional,
        "dimensions": dimensions,
        "reason": _claim("transfer-reason", "迁移难度按五维证据和岗位要求计算；未知项不会被当作已满足。", "inference", [source_ref]),
    }


def _one_match(core: Mapping[str, Any], job: Mapping[str, Any], *, explicit: bool = False) -> dict[str, Any]:
    job = dict(job)
    source_status = _job_source_status(job)
    source_id = job.get("jobSourceId", job.get("job_source_id", job.get("sourceId")))
    source_version = job.get("jobVersion", job.get("job_version", job.get("version")))
    # A verified source must carry both immutable external identifiers.  A
    # template comparison may instead use its stable internal template id and
    # declared template version, preserving provenance while remaining
    # explicitly provisional.
    if source_status == "template_provisional" and not (source_id and source_version):
        template_id = _str(job.get("id", job.get("targetId")), "template")
        source_id = f"template:{template_id}"
        source_version = _str(job.get("templateVersion", job.get("version")), "template-v1")
    elif source_status == "unknown" or (source_status == "verified" and not (source_id and source_version)):
        source_status = "unknown"
        source_id = source_version = None
    source_ref = _source_ref({**job, "jobSourceId": source_id, "jobVersion": source_version})
    tasks = _job_tasks(job)
    # Coverage and transfer use only the template's core tasks.  Supplemental
    # tasks remain visible in the JobMatch task list and can still be tied to
    # individual requirements, but they must not enlarge the core-task
    # denominator.
    core_tasks = [task for task in tasks if task.get("_core", True)]
    contract_tasks = [{"id": task["id"], "name": task["name"]} for task in tasks]
    requirements = _requirements(job)
    evidence = _evidence_items(core)
    comparisons = []
    hard_gates = []
    for req in requirements:
        observed, judgment, evidence_ids, matched = _observed_for(req, evidence)
        source = {**source_ref, "location": req.get("sourceLocation") or f"requirement:{req['id']}"}
        comparisons.append({
            "requirementId": req["id"],
            "taskId": req.get("taskId", ""),
            "capabilityId": req["capabilityId"],
            "requirementType": req["type"],
            "requiredLevel": req["requiredLevel"],
            "observedLevel": observed,
            "judgmentStatus": judgment,
            "evidenceIds": evidence_ids,
            "requirementSource": source,
        })
        if req["type"] == "hard_gate":
            hard_gates.append({
                "requirementId": req["id"],
                "status": _hard_gate_status(
                    req,
                    observed,
                    judgment,
                    evidence,
                    source_known=source_status == "verified",
                ),
                "evidenceIds": evidence_ids,
                "source": source,
            })
    task_ids = [task["id"] for task in core_tasks]
    coverage = _coverage(evidence, task_ids)
    conflict = any(item.get("sourceStatus") == "conflict" and (_task_ids(item) & set(task_ids)) for item in evidence)
    requirement_conflict = any(item.get("judgmentStatus") == "conflict" for item in comparisons)
    core_task_evidence = [item for item in evidence if _task_ids(item) & set(task_ids) and item.get("sourceStatus") in _BEHAVIOR]
    current_core_task_evidence = [item for item in core_task_evidence if item.get("sourceStatus") in _CURRENT_EVIDENCE]
    preference_match = any(item.get("sourceStatus") == "preference" for item in evidence)
    all_gates_met = bool(hard_gates) and all(gate["status"] == "met" for gate in hard_gates)
    gates_unknown = any(gate["status"] in {"unknown", "conflict"} for gate in hard_gates)
    gates_missing = any(gate["status"] == "missing" for gate in hard_gates)
    if conflict or requirement_conflict or any(gate["status"] == "conflict" for gate in hard_gates):
        eligibility = "clarify"
    elif gates_missing:
        eligibility = "exclude"
    elif gates_unknown:
        eligibility = "clarify"
    elif current_core_task_evidence and (not hard_gates or all_gates_met):
        eligibility = "current"
    elif core_task_evidence or preference_match or explicit:
        eligibility = "explore"
    else:
        eligibility = "exclude"
    if conflict or requirement_conflict:
        evidence_status = "conflict"
    elif gates_missing:
        evidence_status = "gap"
    elif any(item.get("sourceStatus") == "verified_result" for item in core_task_evidence):
        evidence_status = "supported"
    elif any(item.get("sourceStatus") == "behavior" for item in core_task_evidence):
        evidence_status = "transfer_pending"
    elif any(item.get("sourceStatus") == "confirmed_self_report" for item in core_task_evidence):
        evidence_status = "self_report_pending"
    else:
        evidence_status = "unknown"
    provisional = source_status in {"template_provisional", "unknown"} or not (source_id and source_version)
    transfer = _transfer(evidence, requirements, core_tasks, provisional=provisional, source_ref=source_ref)
    evidence_ids = sorted({_str(item.get("id")) for item in core_task_evidence if item.get("id")})
    reason_type = "to_validate" if eligibility in {"clarify", "explore"} else "inference"
    reason_text = {
        "current": "至少有可比较的核心任务证据，硬门槛状态已列出。",
        "explore": "目前只有部分任务线索或目标关联，建议先做验证任务。",
        "clarify": "存在冲突或未明确的要求，需要澄清后再判断。",
        "exclude": "当前证据或硬门槛不足以支持该岗位的直接尝试。",
    }[eligibility]
    refs = [source_ref] + [_evidence_ref(item) for item in core_task_evidence]
    action = {
        "id": f"validate-{_str(job.get('id'), 'job')}",
        "title": "完成一项目标岗位任务验证",
        "reason": _claim(f"action-reason-{_str(job.get('id'), 'job')}", reason_text, "recommendation", refs),
        "firstStep": _str(job.get("validationTask"), "选取一个真实任务，记录本人动作、结果和核验材料。"),
        "methodReferences": [],
        "status": "pending",
    }
    trend = job.get("trend") if isinstance(job.get("trend"), Mapping) else {}
    industry_text = _str(job.get("industry"), "行业信息待核实")
    context = {
        "point": _claim(f"point-{_str(job.get('id'), 'job')}", "个人任务证据需与岗位任务逐项核对。", "inference", [_evidence_ref(item) for item in core_task_evidence]),
        "line": _claim(f"line-{_str(job.get('id'), 'job')}", f"岗位任务链：{', '.join(task['name'] for task in tasks) or '待核实'}。", "fact", [source_ref]),
        "plane": _claim(f"plane-{_str(job.get('id'), 'job')}", f"行业：{industry_text}。", "fact", [source_ref]),
        "system": _claim(f"system-{_str(job.get('id'), 'job')}", _str(trend.get("text"), "更大环境趋势待核实。"), "to_validate", [source_ref]),
        "asOf": trend.get("asOf"),
        "references": [source_ref],
    }
    return {
        "id": _str(job.get("id", job.get("targetId")), "job-match"),
        "name": _str(job.get("name", job.get("title")), "待核实岗位"),
        "jobSourceId": source_id,
        "jobVersion": source_version,
        "sourceStatus": source_status,
        "tasks": contract_tasks,
        "eligibility": eligibility,
        "strategyLabel": None,
        "strategyStatus": "pending_method",
        "taskCoverage": coverage,
        "evidenceStatus": evidence_status,
        "requirementComparisons": comparisons,
        "hardGates": hard_gates,
        "transfer": transfer,
        "reason": _claim(f"reason-{_str(job.get('id'), 'job')}", reason_text, reason_type, refs),
        "evidenceIds": evidence_ids,
        "gaps": sorted({req["id"] for req in requirements if req["type"] in {"hard_gate", "core"} and any(item["requirementId"] == req["id"] and item["judgmentStatus"] in {"gap", "unknown", "self_report_pending", "transfer_pending"} for item in comparisons)}),
        "risks": [_claim(f"risk-{_str(job.get('id'), 'job')}", "岗位来源或关键任务仍需核验。", "to_validate", [source_ref])] if source_status != "verified" else [],
        "validationTask": action,
        "industryContext": context,
    }


def _explicit_inputs(explicit_target_ids: Any, kwargs: Mapping[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    """Normalize id-only and full target declarations from profile input."""

    values = explicit_target_ids
    if values is None:
        values = kwargs.get("explicitTargets", kwargs.get("explicit_targets"))
    ids: set[str] = set()
    specs: list[dict[str, Any]] = []
    for value in _as_list(values):
        if isinstance(value, Mapping):
            spec = dict(value)
            identifier = _str(spec.get("id", spec.get("targetId")))
            if identifier:
                ids.add(identifier)
                specs.append(spec)
        elif value not in (None, ""):
            ids.add(str(value))
    return ids, specs


def _unknown_target_spec(identifier: str) -> dict[str, Any]:
    """Keep a declared target visible when no published template was found."""

    return {
        "id": identifier,
        "name": identifier,
        "jobSourceId": None,
        "jobVersion": None,
        "sourceStatus": "unknown",
        "tasks": [],
        "requirements": [],
        "hardRequirements": [],
    }


def match_jobs(core: Mapping[str, Any] | None, templates: Sequence[Mapping[str, Any]] | None, explicit_target_ids: Sequence[str] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    """Return at most three deterministic job comparisons.

    ``explicit_target_ids`` is accepted separately so a UI can retain a
    user's declared target even when its evidence is insufficient.  Callers
    may also pass ``explicitTargets`` for compatibility with early drafts.
    """
    core = dict(core or {})
    templates = [dict(item) for item in (templates or []) if isinstance(item, Mapping)]
    explicit, explicit_specs = _explicit_inputs(explicit_target_ids, kwargs)
    existing_ids = {_str(item.get("id", item.get("targetId"))) for item in templates}
    templates.extend(spec for spec in explicit_specs if _str(spec.get("id", spec.get("targetId"))) not in existing_ids)
    existing_ids.update(_str(item.get("id", item.get("targetId"))) for item in explicit_specs)
    templates.extend(_unknown_target_spec(identifier) for identifier in sorted(explicit - existing_ids))
    # Keep declared targets first, then use a stable id/name order.  No score
    # is used to manufacture a Top 1 recommendation.
    templates.sort(key=lambda item: (0 if _str(item.get("id", item.get("targetId"))) in explicit else 1, _str(item.get("id", item.get("targetId"))), _str(item.get("name", item.get("title")))))
    matches: list[dict[str, Any]] = []
    for item in templates:
        item_id = _str(item.get("id", item.get("targetId")))
        is_explicit = item_id in explicit
        match = _one_match(core, item, explicit=is_explicit)
        # Excluded jobs are retained only when the user explicitly named them;
        # otherwise they are not recommendations and must not consume the
        # three-item recommendation budget.
        if is_explicit or match["eligibility"] != "exclude":
            matches.append(match)
    return matches[:3]


def build_decisions(core: Mapping[str, Any] | None, templates: Sequence[Mapping[str, Any]] | None, explicit_target_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Build the decisions-shaped envelope with explicit targets separate."""
    explicit, explicit_specs = _explicit_inputs(explicit_target_ids, {})
    all_templates = [dict(item) for item in (templates or []) if isinstance(item, Mapping)]
    existing_ids = {_str(item.get("id", item.get("targetId"))) for item in all_templates}
    all_templates.extend(spec for spec in explicit_specs if _str(spec.get("id", spec.get("targetId"))) not in existing_ids)
    existing_ids.update(_str(item.get("id", item.get("targetId"))) for item in explicit_specs)
    all_templates.extend(_unknown_target_spec(identifier) for identifier in sorted(explicit - existing_ids))
    all_templates.sort(key=lambda item: (_str(item.get("id", item.get("targetId"))), _str(item.get("name", item.get("title")))))
    all_matches = [
        _one_match(core or {}, item, explicit=_str(item.get("id", item.get("targetId"))) in explicit)
        for item in all_templates
    ]
    explicit_matches = [item for item in all_matches if item["id"] in explicit][:3]
    current = [item for item in all_matches if item["id"] not in explicit and item["eligibility"] != "exclude"][:3]
    return {
        "jobMatches": current,
        "explicitTargets": explicit_matches,
        "preferredDirection": None,
        "alternativeDirection": None,
        "actions": [item["validationTask"] for item in current[:3]],
        "actionPlan": [],
        "preparationSuggestions": [],
        "counterEvidenceConditions": [],
    }
