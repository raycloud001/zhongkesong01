#!/usr/bin/env python3
"""Generate the evidence-only questionnaire from the locally frozen 2.2 source table."""
import argparse
import hashlib
import json
import re
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
SOURCE = BACKEND / "seed/sources/题目与AI报告生成规则.md"
OUTPUT = BACKEND / "seed/official-questionnaire.json"
ROW = re.compile(r"^\| (Q\d{2}) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$")
OPTION = re.compile(r"(?:^|；)([A-F])\s*([^；]+)")


def options_from(text: str) -> list[dict[str, str]]:
    if "单选：" in text:
        option_text = text.split("单选：", 1)[1]
    elif "多选：" in text:
        option_text = text.split("多选：", 1)[1]
    else:
        option_text = text
    return [{"id": key, "label": label.strip()} for key, label in OPTION.findall(option_text)]


def base_shape(identifier: str, source_text: str) -> tuple[str, bool, list[dict], list[dict]]:
    required = identifier != "Q39"
    options = options_from(source_text)
    if "多选：" in source_text:
        prompt = source_text.split("多选：", 1)[0]
        maximum = 2 if identifier in {"Q04", "Q34"} else len(options)
        fields = [{"id": "choice", "type": "multiple", "required": required, "minSelections": 1, "maxSelections": maximum, "options": options}]
        return prompt, required, options, fields
    if "单选：" in source_text:
        prompt = source_text.split("单选：", 1)[0]
        fields = [{"id": "choice", "type": "single", "required": required, "options": options}]
        return prompt, required, options, fields
    return source_text, required, options, []


def compound(identifier: str, source_text: str, prompt: str, options: list[dict], fields: list[dict]) -> tuple[str, list[dict], list[dict]]:
    if identifier == "Q25":
        prompt = source_text.split("（", 1)[0]
        options = [{"id": key, "label": label} for key, label in zip("ABCD", ["定义问题", "收集信息", "提出方案", "验证结果"])]
        fields = [
            {"id": "choice", "type": "single", "required": True, "options": options},
            {"id": "reason", "type": "text", "required": True, "maxLength": 20},
        ]
    elif identifier == "Q30":
        prompt = source_text.split("：", 1)[0]
        fields = [
            {"id": "name", "type": "text", "required": True},
            {"id": "frequency", "type": "text", "required": True},
            {"id": "typicalTask", "type": "text", "required": True},
            {"id": "independence", "type": "integer", "required": True, "min": 1, "max": 4},
        ]
    elif identifier == "Q31":
        prompt = source_text.split("：", 1)[0]
        fields = [{"id": key, "type": "text", "required": key in {"work", "action", "time"}} for key in ("work", "action", "result", "time")]
    elif identifier == "Q36":
        option_segment = source_text.split("：", 1)[1]
        options = [{"id": key, "label": label.strip()} for key, label in OPTION.findall(option_segment)]
        fields = [
            {"id": "choice", "type": "single", "required": True, "options": options},
            {"id": "reason", "type": "text", "required": False, "requiredWhenCondition": True, "condition": {"field": "choice", "equals": "C"}},
        ]
    elif identifier == "Q37":
        prompt = source_text.split("（", 1)[0]
        length = {"fields": ["goal", "action", "result"], "min": 100, "max": 200}
        fields = [
            {"id": "status", "type": "single", "required": True, "options": [{"id": "has_experience", "label": "有相关经历"}, {"id": "no_experience", "label": "暂无相关经历"}]},
            {"id": "goal", "type": "text", "required": True, "condition": {"field": "status", "equals": "has_experience"}, "combinedLength": length},
            {"id": "action", "type": "text", "required": True, "condition": {"field": "status", "equals": "has_experience"}},
            {"id": "result", "type": "text", "required": False, "condition": {"field": "status", "equals": "has_experience"}, "missingMeaning": "pending_verification"},
        ]
    elif identifier == "Q38":
        prompt = source_text.split("：", 1)[0]
        answer_text = source_text.split("：", 1)[1]
        labels_text = answer_text.split("单选+补充原因：", 1)[1]
        labels = labels_text.split("/")
        options = [{"id": f"T{i}", "label": label} for i, label in enumerate(labels, 1)]
        fields = [{"id": "target", "type": "single", "required": True, "options": options}, {"id": "reason", "type": "text", "required": True}]
    elif identifier == "Q39":
        prompt = source_text.split("：", 1)[0]
        fields = [
            {"id": "text", "type": "text", "required": False},
            {"id": "audio", "type": "audio", "required": False, "status": "pending_implementation"},
        ]
    return prompt, options, fields


def build(source_path: Path = SOURCE) -> dict:
    raw = source_path.read_bytes()
    questions = []
    in_table = False
    for line_number, line in enumerate(raw.decode().splitlines(), 1):
        if line.startswith("### 2.2 "):
            in_table = True
            continue
        if in_table and line.startswith("### 2.3 "):
            break
        if not in_table:
            continue
        match = ROW.match(line)
        if not match:
            continue
        identifier, source_text, dimension, evidence, report_use = match.groups()
        prompt, required, options, fields = base_shape(identifier, source_text)
        prompt, options, fields = compound(identifier, source_text, prompt, options, fields)
        question_type = "compound" if len(fields) > 1 or identifier in {"Q30", "Q31", "Q37", "Q39"} else fields[0]["type"]
        questions.append({
            "id": identifier, "text": source_text, "type": question_type, "required": required,
            "options": options, "fields": fields, "sourceText": source_text, "sourceLine": line_number,
            "dimension": dimension, "evidenceRule": evidence, "reportUse": report_use,
        })
    if len(questions) != 40:
        raise ValueError(f"expected 40 source rows, found {len(questions)}")
    return {"metadata": {"mode": "evidence_only", "synthetic": False, "scoringStatus": "pending_method", "sourceSha256": hashlib.sha256(raw).hexdigest(), "sourceSection": "2.2"}, "questions": questions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            print(f"stale generated asset: {OUTPUT.relative_to(BACKEND.parent)}")
            return 1
        return 0
    OUTPUT.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
