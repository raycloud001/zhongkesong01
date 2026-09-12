from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


ID = str
Score = Annotated[float | None, Field(ge=0, le=100)]
Kind = Literal["fact", "inference", "recommendation", "to_validate"]
Phase = Literal["pending", "running", "ready", "failed"]


class Reference(ContractModel):
    source: Literal["answer", "knowledge", "report", "profile", "job_source", "method"]
    id: ID
    version: ID
    location: str | None = None


class Claim(ContractModel):
    id: ID
    text: str
    claimType: Kind
    references: list[Reference]


class Evidence(ContractModel):
    id: ID
    questionId: ID | None
    answerId: ID | None
    quote: str
    taskIds: list[ID]
    sourceStatus: Literal["verified_result", "confirmed_self_report", "behavior", "preference", "missing", "conflict"]
    verificationSource: str | None
    gaps: list[str]
    conflictGroupId: ID | None


class Dimension(ContractModel):
    id: ID
    name: str
    score: Score
    description: str
    evidenceIds: list[ID]


class SourceVersions(ContractModel):
    questionVersion: ID
    ruleVersion: ID
    jobTemplateVersion: ID
    knowledgeIndexVersion: ID
    promptVersion: ID
    modelName: str
    embeddingModelVersion: str
    profileSnapshotId: ID | None


class Action(ContractModel):
    id: ID
    title: str
    reason: Claim
    firstStep: str
    methodReferences: list[Reference]
    status: Literal["pending", "completed"]


class IndustryContext(ContractModel):
    point: Claim
    line: Claim
    plane: Claim
    system: Claim
    asOf: str | None
    references: list[Reference]


class JobTask(ContractModel):
    id: ID
    name: str


class RequirementComparison(ContractModel):
    requirementId: ID
    taskId: ID
    capabilityId: ID
    requirementType: Literal["hard_gate", "core", "bonus"]
    requiredLevel: Literal["L0", "L1", "L2", "L3", "unknown"]
    observedLevel: Literal["L0", "L1", "L2", "L3", "unknown"]
    judgmentStatus: Literal["supported", "self_report_pending", "transfer_pending", "gap", "unknown", "conflict"]
    evidenceIds: list[ID]
    requirementSource: Reference


class HardGate(ContractModel):
    requirementId: ID
    status: Literal["met", "missing", "unknown", "conflict"]
    evidenceIds: list[ID]
    source: Reference


TransferKey = Literal["core_task", "industry_qualification", "hard_skill", "service_chain", "responsibility_environment"]


class TransferDimension(ContractModel):
    key: TransferKey
    status: Literal["reusable", "validate_in_context", "training_needed", "unknown", "conflict"]
    evidenceIds: list[ID]
    requirementIds: list[ID]
    references: list[Reference]


class Transfer(ContractModel):
    level: Literal["low", "medium", "high", "unknown"]
    provisional: bool
    dimensions: list[TransferDimension]
    reason: Claim

    @model_validator(mode="after")
    def validate_transfer(self):
        expected = {"core_task", "industry_qualification", "hard_skill", "service_chain", "responsibility_environment"}
        if {dimension.key for dimension in self.dimensions} != expected or len(self.dimensions) != 5:
            raise ValueError("transfer must contain each of the five dimensions exactly once")
        if self.provisional and self.level != "unknown":
            raise ValueError("provisional transfer difficulty must remain unknown")
        return self


class JobMatch(ContractModel):
    id: ID
    name: str
    jobSourceId: ID | None
    jobVersion: ID | None
    sourceStatus: Literal["verified", "template_provisional", "unknown"]
    tasks: list[JobTask]
    eligibility: Literal["current", "explore", "clarify", "exclude"]
    strategyLabel: Literal["steady", "stretch", "safe"] | None
    strategyStatus: Literal["ready", "pending_method"]
    taskCoverage: dict[Literal["behavior", "verified"], Score]
    evidenceStatus: Literal["supported", "self_report_pending", "transfer_pending", "gap", "unknown", "conflict"]
    requirementComparisons: list[RequirementComparison]
    hardGates: list[HardGate]
    transfer: Transfer
    reason: Claim
    evidenceIds: list[ID]
    gaps: list[str]
    risks: list[Claim]
    validationTask: Action
    industryContext: IndustryContext

    @model_validator(mode="after")
    def validate_source_and_strategy(self):
        if self.strategyStatus == "pending_method" and self.strategyLabel is not None:
            raise ValueError("pending strategy cannot have a label")
        if self.sourceStatus in ("verified", "template_provisional") and (self.jobSourceId is None or self.jobVersion is None):
            raise ValueError("verified and template jobs require source id and version")
        if self.sourceStatus == "unknown" and (self.jobSourceId is not None or self.jobVersion is not None):
            raise ValueError("unknown source cannot claim an id or version")
        if self.sourceStatus == "template_provisional" and not self.transfer.provisional:
            raise ValueError("template source requires provisional transfer")
        return self


class TypeSummary(ContractModel):
    id: ID
    name: str
    summary: Claim


class KeySummaries(ContractModel):
    state: Claim
    advantage: Claim
    risk: Claim


class Radar(ContractModel):
    dimensions: Annotated[list[Dimension], Field(min_length=6, max_length=8)]
    scale: tuple[Literal[0], Literal[100]]


class Strength(ContractModel):
    dimensionId: ID
    score: Score
    evidenceIds: list[ID]
    application: str


class Core(ContractModel):
    type: TypeSummary | None
    keySummaries: KeySummaries
    radar: Radar | None
    evidence: list[Evidence]
    strengths: list[Strength]
    weaknesses: list[Claim]
    risk: Claim | None
    judgments: list[Claim]


class ActionPlanItem(ContractModel):
    day: Literal[30, 60, 90]
    actionIds: list[ID]
    deliverable: str


class Decisions(ContractModel):
    jobMatches: Annotated[list[JobMatch], Field(max_length=3)]
    explicitTargets: Annotated[list[JobMatch], Field(max_length=3)]
    preferredDirection: Claim | None
    alternativeDirection: Claim | None
    actions: Annotated[list[Action], Field(max_length=3)]
    actionPlan: list[ActionPlanItem]
    preparationSuggestions: list[Claim]
    counterEvidenceConditions: list[Claim]


SectionKey = Literal["core_judgment", "job_impact", "uncertainty", "validation"]


class InterpretationSection(ContractModel):
    key: SectionKey
    claims: list[Claim]


class Interpretation(ContractModel):
    sections: list[InterpretationSection]
    aiUsageNotice: str
    reviewItems: list[str]

    @model_validator(mode="after")
    def exact_sections(self):
        expected = ["core_judgment", "job_impact", "uncertainty", "validation"]
        if [section.key for section in self.sections] != expected:
            raise ValueError("sections must contain the four contract keys in order")
        return self


T = TypeVar("T")


class Part(ContractModel, Generic[T]):
    status: Phase
    data: T | None
    errorCode: str | None

    @model_validator(mode="after")
    def data_matches_status(self):
        if self.status == "ready" and self.data is None:
            raise ValueError("ready part requires data")
        if self.status in ("pending", "running") and self.data is not None:
            raise ValueError("unfinished part cannot contain data")
        return self


class TrackingNode(ContractModel):
    day: Literal[7, 30, 90]
    label: str


class Tracking(ContractModel):
    status: Literal["preview"]
    nodes: list[TrackingNode]


class Report(ContractModel):
    id: ID
    assessmentId: ID
    version: int = Field(ge=1)
    demo: bool
    status: Literal["generating", "partial", "ready", "failed"]
    reviewStatus: Literal["pending", "confirmed", "disputed"]
    sourceVersions: SourceVersions
    inputHash: str
    createdAt: datetime
    core: Part[Core]
    decisions: Part[Decisions]
    interpretation: Part[Interpretation]
    tracking: Tracking


class Job(ContractModel):
    id: ID
    status: Literal["queued", "running", "ready", "failed"]
    stage: Literal["validate", "score", "retrieve", "generate", "complete"]
    reportId: ID | None
    completedParts: list[Literal["core", "decisions", "interpretation"]]
    failedParts: list[str]
    retryable: bool
    attemptCount: int = Field(ge=0, le=3)
    errorCode: str | None


class Fact(ContractModel):
    factId: ID
    content: str
    sourceMessageId: ID
    status: Literal["candidate", "confirmed", "rejected", "retracted"]
    createdAt: datetime
    targetProfileField: Literal["goal", "preference", "experience", "feedback"]


class ChatReply(ContractModel):
    messageId: ID
    conclusion: Claim
    facts: list[Claim]
    inferences: list[Claim]
    recommendations: list[Claim]
    toValidate: list[Claim]
    factCandidates: list[Fact]
    createdAt: datetime


class Snapshot(ContractModel):
    id: ID
    previousId: ID | None
    createdAt: datetime
    reportIds: list[ID]
    confirmedFacts: list[Fact]
    changeReason: str


REPORT_SCHEMA_MODELS = [Report, Job, Fact, ChatReply, Snapshot]
