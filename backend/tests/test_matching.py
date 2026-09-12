from app.matching.service import match_jobs
from app.matching.service import build_decisions
from app.contracts.report import Decisions, JobMatch


def claim(identifier="c", text="待验证", claim_type="to_validate"):
    return {"id": identifier, "text": text, "claimType": claim_type, "references": []}


def core_with_evidence(*evidence, coverage=None):
    items = list(evidence)
    return {
        "evidence": items,
        "evidenceLedger": items,
        "taskCoverage": coverage or {"behavior": None, "verified": None},
        "judgments": [],
        "quality": {"conflictGroups": []},
    }


def evidence(identifier, task_id, status="behavior"):
    return {
        "id": identifier,
        "questionId": "Q37",
        "answerId": identifier,
        "quote": "完成并复盘",
        "taskIds": [task_id],
        "sourceStatus": status,
        "verificationSource": "review-1" if status == "verified_result" else None,
        "gaps": [],
        "conflictGroupId": None,
    }


def job_template(**overrides):
    value = {
        "id": "job-content",
        "name": "内容运营",
        "jobSourceId": "jd-1",
        "jobVersion": "jd-v1",
        "sourceStatus": "verified",
        "tasks": [{"id": "content", "name": "内容生产"}],
        "requirements": [
            {
                "id": "req-content",
                "taskId": "content",
                "capabilityId": "P02",
                "type": "core",
                "requiredLevel": "L1",
            }
        ],
        "hardRequirements": [],
        "industry": "互联网",
    }
    value.update(overrides)
    return value


def test_empty_evidence_with_no_target_is_not_a_recommendation():
    assert match_jobs(core_with_evidence(), []) == []


def test_missing_hard_gate_cannot_be_current():
    core = core_with_evidence(evidence("e1", "content"), coverage={"behavior": 1.0, "verified": None})
    job = job_template(
        hardRequirements=[
            {
                "id": "gate-cert",
                "taskId": "content",
                "capabilityId": "CERT",
                "type": "hard_gate",
                "requiredLevel": "L1",
            }
        ]
    )
    result = match_jobs(core, [job])[0]
    assert result["eligibility"] in {"clarify", "exclude", "explore"}
    assert result["hardGates"][0]["status"] in {"missing", "unknown"}
    assert result["strategyLabel"] is None
    assert result["strategyStatus"] == "pending_method"


def test_explicit_target_is_retained_even_when_unknown():
    result = match_jobs(
        core_with_evidence(),
        [job_template(jobSourceId=None, jobVersion=None, sourceStatus="unknown")],
        explicit_target_ids=["job-content"],
    )[0]
    assert result["id"] == "job-content"
    assert result["eligibility"] in {"explore", "clarify", "exclude"}


def test_template_without_jd_is_provisional_and_transfer_unknown():
    template = job_template(
        jobSourceId="template-content",
        jobVersion="templates-v1",
        sourceStatus="template_provisional",
        requirements=[],
        hardRequirements=[],
    )
    result = match_jobs(core_with_evidence(evidence("e1", "content")), [template])[0]
    assert result["sourceStatus"] == "template_provisional"
    assert result["transfer"]["provisional"] is True
    assert result["transfer"]["level"] == "unknown"
    assert result["strategyLabel"] is None


def test_conflict_has_priority_over_high_or_low_transfer():
    conflicted = evidence("e1", "content", "conflict")
    core = core_with_evidence(conflicted, coverage={"behavior": None, "verified": None})
    result = match_jobs(core, [job_template()])[0]
    assert result["eligibility"] == "clarify"
    assert result["transfer"]["level"] == "unknown"
    assert any(d["status"] == "conflict" for d in result["transfer"]["dimensions"])


def test_matching_is_stable_when_input_order_changes_and_caps_three():
    core = core_with_evidence(evidence("e1", "content"))
    jobs = [job_template(id=f"job-{i}", name=f"岗位{i}") for i in range(5)]
    first = match_jobs(core, jobs)
    second = match_jobs(core, list(reversed(jobs)))
    assert len(first) <= 3
    assert first == second


def test_non_explicit_excluded_jobs_are_not_recommendations():
    result = match_jobs(core_with_evidence(), [job_template()])

    assert result == []


def test_explicit_targets_are_kept_separate_from_three_recommendations():
    core = core_with_evidence(evidence("e1", "content"))
    jobs = [job_template(id=f"job-{i}", name=f"岗位{i}") for i in range(5)]

    result = build_decisions(core, jobs, explicit_target_ids=["job-0"])

    assert len(result["explicitTargets"]) == 1
    assert result["explicitTargets"][0]["id"] == "job-0"
    assert len(result["jobMatches"]) <= 3
    assert all(item["id"] != "job-0" for item in result["jobMatches"])


def test_unknown_job_source_is_provisional_and_difficulty_unknown():
    job = job_template(jobSourceId=None, jobVersion=None, sourceStatus="unknown", requirements=[])

    result = match_jobs(core_with_evidence(evidence("e1", "content")), [job])[0]

    assert result["transfer"]["provisional"] is True
    assert result["transfer"]["level"] == "unknown"


def test_unknown_requirement_keeps_transfer_difficulty_unknown():
    job = job_template(requirements=[{
        "id": "req-unknown",
        "taskId": "content",
        "capabilityId": "P02",
        "type": "core",
        "requiredLevel": "unknown",
    }])

    result = match_jobs(core_with_evidence(evidence("e1", "content")), [job])[0]

    assert result["transfer"]["level"] == "unknown"


def test_verified_evidence_takes_priority_over_behavior_status():
    core = core_with_evidence(
        evidence("e1", "content", "behavior"),
        evidence("e2", "content", "verified_result"),
    )
    job = job_template(requirements=[{
        "id": "req-content",
        "taskId": "content",
        "capabilityId": "P02",
        "type": "core",
        "requiredLevel": "unknown",
    }])

    result = match_jobs(core, [job])[0]

    assert result["evidenceStatus"] == "supported"


def test_confirmed_self_report_core_evidence_is_explore_not_current():
    core = core_with_evidence(evidence("self-1", "content", "confirmed_self_report"))

    result = match_jobs(core, [job_template()])[0]

    assert result["eligibility"] == "explore"
    assert result["evidenceStatus"] == "self_report_pending"


def test_behavior_evidence_takes_priority_over_self_report_status():
    core = core_with_evidence(
        evidence("self-1", "content", "confirmed_self_report"),
        evidence("behavior-1", "content", "behavior"),
    )

    result = match_jobs(core, [job_template()])[0]

    assert result["evidenceStatus"] == "transfer_pending"


def test_conflict_on_non_core_requirement_clarifies_the_job_match():
    core_task = evidence("core-1", "content", "verified_result")
    core_task["observedLevel"] = "L1"
    conflicted = evidence("conflict-1", "analytics", "conflict")
    conflicted["conflictGroupId"] = "conflict-group-1"
    job = job_template(requirements=[{
        "id": "req-analytics",
        "taskId": "analytics",
        "capabilityId": "ANALYTICS",
        "type": "core",
        "requiredLevel": "L1",
    }])

    result = match_jobs(core_with_evidence(core_task, conflicted), [job])[0]

    assert result["eligibility"] == "clarify"
    assert result["evidenceStatus"] == "conflict"
    assert result["transfer"]["dimensions"][2]["status"] == "conflict"
    assert result["transfer"]["level"] == "unknown"


def test_contract_validation_preserves_requirement_and_source_references():
    result = match_jobs(core_with_evidence(evidence("e1", "content")), [job_template()])[0]

    validated = JobMatch.model_validate(result)

    assert validated.requirementComparisons[0].requirementSource.source == "job_source"
    assert validated.requirementComparisons[0].taskId == "content"


def test_reusable_core_task_and_satisfied_requirement_can_be_low_transfer():
    verified = evidence("e1", "content", "verified_result")
    verified["observedLevel"] = "L1"
    job = job_template(requirements=[{
        "id": "req-content",
        "taskId": "content",
        "capabilityId": "P02",
        "type": "core",
        "requiredLevel": "L1",
    }])

    result = match_jobs(core_with_evidence(verified), [job])[0]

    assert result["transfer"]["level"] == "low"


def test_known_hard_gate_gap_has_high_transfer_priority():
    observed = evidence("e1", "content", "verified_result")
    observed["observedLevel"] = "L0"
    job = job_template(hardRequirements=[{
        "id": "gate-cert",
        "taskId": "content",
        "capabilityId": "CERT",
        "type": "hard_gate",
        "requiredLevel": "L1",
    }])

    result = match_jobs(core_with_evidence(observed), [job], explicit_target_ids=["job-content"])[0]

    assert result["hardGates"][0]["status"] == "missing"
    assert result["transfer"]["level"] == "high"


def test_explicit_target_mapping_is_retained_even_when_not_in_template_list():
    target = job_template(id="target-only", name="用户目标", sourceStatus="unknown", jobSourceId=None, jobVersion=None)

    result = build_decisions(core_with_evidence(), [], explicit_target_ids=[target])

    assert len(result["explicitTargets"]) == 1
    assert result["explicitTargets"][0]["id"] == "target-only"
    assert result["explicitTargets"][0]["eligibility"] in {"explore", "clarify", "exclude"}


def test_unversioned_verified_job_is_downgraded_to_unknown_source_for_contract_safety():
    job = job_template(sourceStatus="verified", jobSourceId=None, jobVersion=None)

    result = match_jobs(core_with_evidence(), [job], explicit_target_ids=["job-content"])[0]

    assert result["sourceStatus"] == "unknown"
    assert result["jobSourceId"] is None
    assert result["transfer"]["provisional"] is True


def test_explicit_target_alias_is_supported():
    target = job_template(id="alias-target", sourceStatus="unknown", jobSourceId=None, jobVersion=None)

    result = match_jobs(core_with_evidence(), [], explicit_targets=[target])

    assert result[0]["id"] == "alias-target"


def test_known_hard_gate_without_evidence_is_missing():
    job = job_template(hardRequirements=[{
        "id": "gate-cert",
        "taskId": "content",
        "capabilityId": "CERT",
        "type": "hard_gate",
        "requiredLevel": "L1",
    }])

    result = match_jobs(core_with_evidence(), [job], explicit_target_ids=["job-content"])[0]

    assert result["hardGates"][0]["status"] == "missing"
    assert result["eligibility"] == "exclude"


def test_explicit_id_without_template_gets_unknown_placeholder():
    result = match_jobs(core_with_evidence(), [], explicit_target_ids=["missing-job"])

    assert len(result) == 1
    assert result[0]["id"] == "missing-job"
    assert result[0]["sourceStatus"] == "unknown"
    assert result[0]["eligibility"] in {"explore", "clarify", "exclude"}
    assert result[0]["transfer"]["provisional"] is True


def test_template_provisional_without_external_jd_gets_stable_source_reference():
    template = job_template(
        jobSourceId=None,
        jobVersion=None,
        sourceStatus="template_provisional",
        template=True,
        requirements=[],
        hardRequirements=[],
    )

    result = match_jobs(core_with_evidence(), [template], explicit_target_ids=["job-content"])[0]

    assert result["sourceStatus"] == "template_provisional"
    assert result["jobSourceId"]
    assert result["jobVersion"]
    assert result["transfer"]["provisional"] is True
    JobMatch.model_validate(result)


def test_non_core_job_tasks_do_not_expand_task_coverage_denominator():
    template = job_template(
        tasks=[
            {"id": "content", "name": "内容生产", "core": True},
            {"id": "bonus", "name": "额外任务", "core": False},
        ],
        requirements=[],
        hardRequirements=[],
    )
    core = core_with_evidence(evidence("e1", "content"))

    result = match_jobs(core, [template])[0]

    assert result["taskCoverage"]["behavior"] == 1.0


def test_hard_gate_without_task_mapping_remains_unknown():
    template = job_template(hardRequirements=[{
        "id": "gate-unknown",
        "capabilityId": "CERT",
        "type": "hard_gate",
        "requiredLevel": "L1",
    }])

    result = match_jobs(core_with_evidence(), [template], explicit_target_ids=["job-content"])[0]

    assert result["hardGates"][0]["status"] == "unknown"


def test_known_missing_hard_gate_is_high_when_core_evidence_is_known():
    template = job_template(
        tasks=[{"id": "content", "name": "内容生产", "core": True}],
        requirements=[],
        hardRequirements=[{
            "id": "gate-cert",
            "taskId": "certification",
            "capabilityId": "CERT",
            "type": "hard_gate",
            "requiredLevel": "L1",
        }],
    )
    observed = evidence("e1", "content", "verified_result")
    observed["observedLevel"] = "L1"
    # Deliberately omit a certificate evidence record: the gate is a known
    # requirement, while the core task evidence remains usable.
    # The core task is evidenced, while the separate qualification task has
    # no evidence.  This isolates a known hard-gate gap from an unknown core
    # task.

    result = match_jobs(core_with_evidence(observed), [template], explicit_target_ids=["job-content"])[0]

    assert result["hardGates"][0]["status"] == "missing"
    assert result["transfer"]["level"] == "high"


def test_verified_hard_gate_evidence_is_used_in_transfer_dimensions():
    template = job_template(
        tasks=[{"id": "content", "name": "内容生产", "core": True}],
        requirements=[],
        hardRequirements=[{
            "id": "gate-cert",
            "taskId": "certification",
            "capabilityId": "CERT",
            "type": "hard_gate",
            "requiredLevel": "L1",
        }],
    )
    core_task = evidence("content-e1", "content", "verified_result")
    core_task["observedLevel"] = "L1"
    certificate = evidence("cert-e1", "certification", "verified_result")
    certificate["observedLevel"] = "L1"

    result = match_jobs(core_with_evidence(core_task, certificate), [template], explicit_target_ids=["job-content"])[0]

    assert result["hardGates"][0]["status"] == "met"
    assert result["transfer"]["dimensions"][1]["status"] == "reusable"
