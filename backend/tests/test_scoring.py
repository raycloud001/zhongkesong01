from app.scoring.service import (
    build_core,
    compute_task_coverage,
    normalize_evidence,
    score_answers,
)


def fact(
    evidence_id,
    *,
    fact_key="u:p:t:2025",
    claim_hash="claim-a",
    task_ids=None,
    source_status="behavior",
    quote="完成任务并复盘",
    question_id="Q37",
    claim=None,
    source_id=None,
    verification_source=None,
):
    return {
        "id": evidence_id,
        "fact_key": fact_key,
        "claim_hash": claim_hash,
        "taskIds": task_ids or ["task-1"],
        "sourceStatus": source_status,
        "quote": quote,
        "questionId": question_id,
        "answerId": source_id or evidence_id,
        "claim": claim or {"responsibility": "执行", "result": "按期交付"},
        "sourceId": source_id or evidence_id,
        "verificationSource": verification_source,
    }


def rule_with_tasks(*task_ids):
    return {"coreTasks": [{"id": task_id, "name": task_id} for task_id in task_ids]}


def test_empty_facts_are_unknown_not_zero():
    result = score_answers([], rule_with_tasks("task-1"))

    assert result["radar"] is None
    assert result["type"] is None
    assert result["taskCoverage"] == {"behavior": None, "verified": None}
    assert result["evidence"] == []


def test_duplicate_fact_key_and_claim_hash_keeps_sources_but_counts_one_task():
    answers = [
        fact("e1", source_id="answer-1"),
        fact("e2", source_id="answer-2"),
    ]

    normalized = normalize_evidence(answers)
    result = score_answers(answers, rule_with_tasks("task-1"))

    assert len(normalized) == 1
    assert result["taskCoverage"] == {"behavior": 1.0, "verified": None}
    assert set(normalized[0]["sourceIds"]) == {"answer-1", "answer-2"}


def test_same_fact_key_with_mutually_exclusive_claims_is_conflict_and_not_averaged():
    answers = [
        fact("e1", claim_hash="lead", claim={"responsibility": "负责"}),
        fact("e2", claim_hash="assist", claim={"responsibility": "仅参与"}),
    ]

    normalized = normalize_evidence(answers)
    result = score_answers(answers, rule_with_tasks("task-1"))

    assert len(normalized) == 2
    assert {item["sourceStatus"] for item in normalized} == {"conflict"}
    assert len({item["conflictGroupId"] for item in normalized}) == 1
    assert result["taskCoverage"] == {"behavior": None, "verified": None}


def test_behavior_and_verified_coverage_are_separate_and_capped():
    answers = [
        fact("e1", fact_key="u:p:t1", claim_hash="claim-t1", task_ids=["task-1"], source_status="behavior"),
        fact("e2", fact_key="u:p:t2", claim_hash="claim-t2", task_ids=["task-2"], source_status="verified_result", verification_source="review-1"),
        fact("e3", fact_key="u:p:t2", claim_hash="claim-t2", task_ids=["task-2"], source_status="verified_result", verification_source="review-1"),
    ]

    result = score_answers(answers, rule_with_tasks("task-1", "task-2"))

    assert result["taskCoverage"] == {"behavior": 1.0, "verified": 0.5}
    assert result["taskCoverage"]["behavior"] <= 1
    assert result["taskCoverage"]["verified"] <= 1


def test_zero_denominator_returns_null():
    assert compute_task_coverage([], []) == {"behavior": None, "verified": None}


def test_preference_and_self_report_do_not_become_verified_result():
    answers = [
        fact("p", fact_key="pref", claim_hash="pref-claim", source_status="preference", task_ids=["task-1"]),
        fact("s", fact_key="self", claim_hash="self-claim", source_status="confirmed_self_report", task_ids=["task-2"]),
    ]

    result = score_answers(answers, rule_with_tasks("task-1", "task-2"))

    assert result["taskCoverage"] == {"behavior": 0.5, "verified": None}
    assert all(item["sourceStatus"] != "verified_result" for item in result["evidence"])


def test_q30_is_self_report_without_level_mapping_and_q39_does_not_penalize():
    answers = [
        {
            "id": "q30-a",
            "questionId": "Q30",
            "answerId": "q30-a",
            "value": {"name": "Excel", "independence": 4},
            "quote": "Excel，独立程度4级",
            "sourceStatus": "confirmed_self_report",
        },
        {
            "id": "q39-a",
            "questionId": "Q39",
            "answerId": "q39-a",
            "value": "报告可能误判我的行业经验",
            "quote": "报告可能误判我的行业经验",
            "sourceStatus": "preference",
        },
    ]

    result = score_answers(answers, rule_with_tasks("task-1"))

    q30 = next(item for item in result["evidence"] if item["questionId"] == "Q30")
    assert q30["sourceStatus"] == "confirmed_self_report"
    assert q30["taskIds"] == []
    assert q30.get("observedLevel") is None
    assert result["quality"]["q39ReviewRequired"] is True
    assert result["taskCoverage"] == {"behavior": None, "verified": None}


def test_q07_and_q40_different_situations_do_not_create_conflict():
    answers = [
        {"id": "q07", "questionId": "Q07", "answerId": "q07", "value": "A", "quote": "先问目标", "sourceStatus": "behavior"},
        {"id": "q40", "questionId": "Q40", "answerId": "q40", "value": "B", "quote": "先做小版本", "sourceStatus": "behavior"},
    ]

    result = score_answers(answers, rule_with_tasks("task-1"))

    assert all(item["conflictGroupId"] is None for item in result["evidence"])
    assert result["quality"]["conflictGroups"] == []


def test_candidate_semantic_mapping_is_not_formal_evidence():
    answers = [
        {"id": "candidate-1", "status": "candidate", "taskIds": ["task-1"], "quote": "AI猜测"},
    ]

    result = score_answers(answers, rule_with_tasks("task-1"))

    assert result["evidence"] == []
    assert result["candidateEvidence"][0]["id"] == "candidate-1"
    assert result["taskCoverage"] == {"behavior": None, "verified": None}


def test_core_output_has_no_numeric_or_type_invention_and_claims_cite_evidence():
    answers = [fact("e1", source_status="verified_result", verification_source="review-1")]

    core = build_core(score_answers(answers, rule_with_tasks("task-1")))

    assert core["type"] is None
    assert core["radar"] is None
    assert core["evidence"][0]["id"] == "e1"
    for claim in [core["keySummaries"]["state"], core["keySummaries"]["advantage"], core["keySummaries"]["risk"]]:
        assert claim["references"]
        assert any(ref["source"] == "answer" for ref in claim["references"])


def test_q39_review_is_stable_when_input_order_changes():
    answers = [
        {"id": "q40", "questionId": "Q40", "answerId": "q40", "value": "A", "quote": "澄清", "sourceStatus": "behavior"},
        {"id": "q39", "questionId": "Q39", "answerId": "q39", "value": "质疑", "quote": "质疑", "sourceStatus": "preference"},
    ]

    first = score_answers(answers, rule_with_tasks("task-1"))
    second = score_answers(list(reversed(answers)), rule_with_tasks("task-1"))

    assert first == second


def test_official_behavior_questions_keep_behavior_provenance_without_task_mapping():
    answers = [
        {"id": "q15", "questionId": "Q15", "answerId": "q15", "value": ["A"], "quote": "跨团队项目"},
        {"id": "q20", "questionId": "Q20", "answerId": "q20", "value": "A", "quote": "有且有结果"},
    ]

    result = score_answers(answers, rule_with_tasks("task-1"))

    assert [item["sourceStatus"] for item in result["evidence"]] == ["behavior", "behavior"]
    assert result["taskCoverage"] == {"behavior": None, "verified": None}


def test_q27_is_confirmed_self_report_until_project_evidence_is_linked():
    result = score_answers(
        [{"id": "q27", "questionId": "Q27", "answerId": "q27", "value": "A", "quote": "多次且有结果"}],
        rule_with_tasks("task-1"),
    )

    assert result["evidence"][0]["sourceStatus"] == "confirmed_self_report"
    assert result["evidence"][0]["taskIds"] == []


def test_raw_experience_and_target_answers_do_not_trust_task_ids_without_confirmed_mapping():
    answers = [
        {"id": "q27", "questionId": "Q27", "answerId": "q27", "value": "A", "taskIds": ["task-1"]},
        {"id": "q31", "questionId": "Q31", "answerId": "q31", "value": {"result": "增长"}, "taskIds": ["task-1"]},
        {"id": "q37", "questionId": "Q37", "answerId": "q37", "value": {"result": "交付"}, "taskIds": ["task-1"]},
        {"id": "q38", "questionId": "Q38", "answerId": "q38", "value": "内容生产", "taskIds": ["task-1"]},
    ]

    result = score_answers(answers, rule_with_tasks("task-1"))

    assert all(item["taskIds"] == [] for item in result["evidence"])
    assert result["taskCoverage"] == {"behavior": None, "verified": None}


def test_confirmed_task_mapping_allows_q37_task_evidence():
    result = score_answers(
        [{
            "id": "q37-confirmed",
            "questionId": "Q37",
            "answerId": "q37-confirmed",
            "value": {"result": "交付"},
            "taskIds": ["task-1"],
            "mappingConfirmed": True,
            "sourceStatus": "behavior",
        }],
        rule_with_tasks("task-1"),
    )

    assert result["evidence"][0]["taskIds"] == ["task-1"]
    assert result["taskCoverage"] == {"behavior": 1.0, "verified": None}


def test_no_experience_markers_are_missing_evidence_not_negative_scores():
    answers = [
        {"id": "q15-none", "questionId": "Q15", "answerId": "q15-none", "value": ["E"], "quote": "暂无"},
        {"id": "q20-none", "questionId": "Q20", "answerId": "q20-none", "value": "D", "quote": "暂无"},
    ]

    result = score_answers(answers, rule_with_tasks("task-1"))

    assert all(item["sourceStatus"] == "missing" for item in result["evidence"])
    assert result["taskCoverage"] == {"behavior": None, "verified": None}


def test_explicit_conflict_status_is_not_overwritten_by_verified_duplicate():
    answers = [
        fact("conflict", fact_key="fact-c", claim_hash="claim-c", source_status="conflict", verification_source="review-1"),
        fact("verified", fact_key="fact-c", claim_hash="claim-c", source_status="verified_result", verification_source="review-2"),
    ]

    normalized = normalize_evidence(answers)

    assert normalized[0]["sourceStatus"] == "conflict"


def test_explicit_claim_hash_does_not_override_different_fact_identity():
    answers = [
        fact("e1", fact_key="fact-one", claim_hash="same-explicit-hash", claim={"responsibility": "负责"}, source_id="answer-1"),
        fact("e2", fact_key="fact-two", claim_hash="same-explicit-hash", claim={"responsibility": "负责并复盘"}, source_id="answer-2"),
    ]

    normalized = normalize_evidence(answers)

    assert len(normalized) == 2
    assert {item["factKey"] for item in normalized} == {"fact-one", "fact-two"}


def test_same_claim_hash_in_different_facts_does_not_merge():
    answers = [
        fact("e1", fact_key="project-one", claim_hash="same-hash", source_id="answer-1"),
        fact("e2", fact_key="project-two", claim_hash="same-hash", source_id="answer-2"),
    ]

    normalized = normalize_evidence(answers)

    assert len(normalized) == 2
