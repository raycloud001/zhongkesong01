import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/seed/sources/题目与AI报告生成规则.md"
OUTPUT = ROOT / "backend/seed/official-questionnaire.json"


def load():
    return json.loads(OUTPUT.read_text())


def test_generator_is_current_and_idempotent():
    command = [str(ROOT / ".venv/bin/python"), "scripts/import_official_questionnaire.py", "--check"]
    first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert first.returncode == second.returncode == 0, first.stdout + first.stderr


def test_all_40_source_rows_are_mapped_verbatim_with_provenance():
    payload = load()
    assert payload["metadata"]["mode"] == "evidence_only"
    assert payload["metadata"]["synthetic"] is False
    assert payload["metadata"]["scoringStatus"] == "pending_method"
    assert len(payload["questions"]) == 40
    assert [q["id"] for q in payload["questions"]] == [f"Q{i:02d}" for i in range(1, 41)]
    source_lines = SOURCE.read_text().splitlines()
    for question in payload["questions"]:
        assert question["sourceText"] == source_lines[question["sourceLine"] - 1].split("|")[2].strip()
        assert question["text"] in question["sourceText"]
    import hashlib
    assert payload["metadata"]["sourceSha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()


def test_compound_and_optional_input_shapes_are_explicit():
    questions = {q["id"]: q for q in load()["questions"]}
    assert questions["Q04"]["fields"][0]["maxSelections"] == 2
    assert questions["Q34"]["fields"][0]["maxSelections"] == 2
    assert [f["id"] for f in questions["Q25"]["fields"]] == ["choice", "reason"]
    assert questions["Q25"]["fields"][1]["maxLength"] == 20
    assert {f["id"] for f in questions["Q30"]["fields"]} == {"name", "frequency", "typicalTask", "independence"}
    assert questions["Q30"]["fields"][-1]["min"] == 1 and questions["Q30"]["fields"][-1]["max"] == 4
    assert {f["id"] for f in questions["Q31"]["fields"]} == {"work", "action", "result", "time"}
    assert questions["Q36"]["fields"][1]["condition"] == {"field": "choice", "equals": "C"}
    assert questions["Q36"]["fields"][1]["requiredWhenCondition"] is True
    assert {f["id"] for f in questions["Q37"]["fields"]} == {"status", "goal", "action", "result"}
    assert questions["Q37"]["fields"][0]["options"][1]["id"] == "no_experience"
    assert questions["Q37"]["fields"][1]["combinedLength"] == {"fields": ["goal", "action", "result"], "min": 100, "max": 200}
    assert {f["id"] for f in questions["Q38"]["fields"]} == {"target", "reason"}
    assert questions["Q39"]["required"] is False
    assert questions["Q39"]["fields"][1]["status"] == "pending_implementation"


def test_option_extraction_does_not_treat_ai_or_prose_as_options():
    questions = {q["id"]: q for q in load()["questions"]}
    assert [item["id"] for item in questions["Q10"]["options"]] == ["A", "B", "C", "D"]
    assert [item["label"] for item in questions["Q10"]["options"][:2]] == ["A", "B"]
    assert [item["id"] for item in questions["Q32"]["options"]] == ["A", "B", "C", "D"]
    assert questions["Q38"]["options"][-1]["label"] == "其他"
    assert [item["label"] for item in questions["Q36"]["options"]] == [
        "先快速产出再迭代", "先充分研究再产出", "视任务而定并说明条件"
    ]


def test_q37_allows_unknown_result_and_prompts_keep_actual_questions():
    questions = {q["id"]: q for q in load()["questions"]}
    result = next(field for field in questions["Q37"]["fields"] if field["id"] == "result")
    assert result["required"] is False
    assert result["missingMeaning"] == "pending_verification"
    assert "你当前最想验证哪个岗位任务？" in questions["Q38"]["text"]
    assert "报告最容易误判你的地方是什么？" in questions["Q39"]["text"]


def test_frozen_source_is_byte_identical_to_supplied_file():
    # CI only has the checked-in canonical source.  An external copy can be
    # supplied when validating a handoff from the source author.
    supplied_value = os.environ.get("OFFICIAL_RULES_SOURCE")
    if supplied_value:
        supplied = Path(supplied_value)
        assert supplied.exists()
        assert SOURCE.read_bytes() == supplied.read_bytes()
    else:
        assert SOURCE.exists()


def test_asset_does_not_invent_scoring_or_sample_results():
    payload = load()
    forbidden = {"weight", "score", "scoringAnchors", "talentTypes", "jobThresholds", "sampleAnswers"}
    assert forbidden.isdisjoint(payload)
    for question in payload["questions"]:
        assert forbidden.isdisjoint(question)
