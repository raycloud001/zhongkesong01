from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest
from pydantic import TypeAdapter, ValidationError

from app.contracts.report import (
    ChatReply,
    Claim,
    Core,
    Dimension,
    Interpretation,
    InterpretationSection,
    Part,
    Report,
    Score,
    Fact,
    Snapshot,
    SourceVersions,
)


def claim(identifier: str = "claim-1") -> Claim:
    return Claim(id=identifier, text="A supported statement", claimType="fact", references=[])


def test_unknown_and_bounds():
    adapter = TypeAdapter(Score)
    assert adapter.validate_python(None) is None
    assert adapter.validate_python(0) == 0
    assert adapter.validate_python(100) == 100
    with pytest.raises(ValidationError):
        adapter.validate_python(101)
    with pytest.raises(ValidationError):
        adapter.validate_python(-1)


def test_radar_requires_six_to_eight_dimensions():
    summary = claim()
    with pytest.raises(ValidationError):
        Core.model_validate(
            {
                "type": None,
                "keySummaries": {"state": summary, "advantage": summary, "risk": summary},
                "radar": {
                    "dimensions": [
                        Dimension(id=str(i), name=str(i), score=None, description="unknown", evidenceIds=[])
                        for i in range(5)
                    ],
                    "scale": [0, 100],
                },
                "evidence": [],
                "strengths": [],
                "weaknesses": [],
                "risk": None,
                "judgments": [],
            }
        )


def test_interpretation_has_exact_ordered_sections():
    with pytest.raises(ValidationError):
        Interpretation(
            sections=[InterpretationSection(key="core_judgment", claims=[])],
            aiUsageNotice="AI explains deterministic results.",
            reviewItems=[],
        )


def test_report_rejects_extra_fields_and_contains_complete_source_versions():
    versions = SourceVersions(
        questionVersion="questions-v1",
        ruleVersion="rules-v1",
        jobTemplateVersion="jobs-v1",
        knowledgeIndexVersion="knowledge-v1",
        promptVersion="prompt-v1",
        modelName="demo-model",
        embeddingModelVersion="embedding-v1",
        profileSnapshotId=None,
    )
    pending = Part[Core](status="pending", data=None, errorCode=None)
    payload = {
        "id": "report-1",
        "assessmentId": "assessment-1",
        "version": 1,
        "demo": True,
        "status": "generating",
        "reviewStatus": "pending",
        "sourceVersions": versions,
        "inputHash": "abc",
        "createdAt": datetime.now(timezone.utc),
        "core": pending,
        "decisions": {"status": "pending", "data": None, "errorCode": None},
        "interpretation": {"status": "pending", "data": None, "errorCode": None},
        "tracking": {"status": "preview", "nodes": []},
        "unexpected": True,
    }
    with pytest.raises(ValidationError):
        Report.model_validate(payload)


def test_generated_typescript_is_current():
    repository = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [str(repository / ".venv" / "bin" / "python"), "scripts/generate_contracts.py", "--check"],
        cwd=repository,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_schema_references_resolve_and_radar_scale_is_tuple():
    repository = Path(__file__).resolve().parents[2]
    schema = __import__("json").loads((repository / "frontend/src/api/schema.json").read_text())
    definitions = schema["$defs"]

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].removeprefix("#/$defs/") in definitions
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
    typescript = (repository / "frontend/src/api/schema.ts").read_text()
    assert "readonly scale: readonly [0, 100];" in typescript
    for name in ("Fact", "ChatReply", "Snapshot", "ErrorEnvelope"):
        assert f"export type {name} =" in typescript


def test_profile_chat_contracts_forbid_extra_fields():
    fact = Fact(
        factId="f-1", content="Prefers analysis", sourceMessageId="m-1", status="candidate",
        createdAt=datetime.now(timezone.utc), targetProfileField="preference",
    )
    snapshot = Snapshot(id="s-1", previousId=None, createdAt=datetime.now(timezone.utc), reportIds=[], confirmedFacts=[], changeReason="initial")
    with pytest.raises(ValidationError):
        Snapshot.model_validate({**snapshot.model_dump(), "extra": True})
