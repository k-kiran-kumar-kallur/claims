"""Pydantic schemas for structured LLM output (spec §5.6 'Structured output').

Citations use the document alias + page + line markers shown in prompts (<<D3|P2|L14>>); agents map aliases back
to document ids and the Validation Agent checks every quote against the stored page lines.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Cite(BaseModel):
    doc: str = Field(description="document alias exactly as in the marker, e.g. 'D3'")
    page: int
    line_start: int
    line_end: int
    quote: str = Field(description="verbatim text copied from the cited lines")


class BaselineField(BaseModel):
    value: str | None = None
    confidence: float = Field(ge=0, le=1)
    citation: Cite | None = None


class UrgentFlagOut(BaseModel):
    title: str
    detail: str
    severity: Literal["low", "medium", "high"]
    citation: Cite | None = None


class BaselineOut(BaseModel):
    claim_number: BaselineField
    claimant_name: BaselineField
    employer_name: BaselineField
    insurer: BaselineField
    tpa: BaselineField
    date_of_injury: BaselineField = Field(description="ISO date YYYY-MM-DD")
    body_parts: BaselineField = Field(description="comma separated body parts")
    mechanism_of_injury: BaselineField
    assigned_adjuster: BaselineField
    jurisdiction_state: BaselineField = Field(description="two-letter state code")
    urgent_flags: list[UrgentFlagOut] = Field(default_factory=list)


class ReviewContextOut(BaseModel):
    review_goals: list[str]
    clinical_question: str
    required_evidence: list[str]
    applicable_guidelines: list[str]
    state_rules: list[str] = Field(default_factory=list)


class Boundary(BaseModel):
    start_page: int
    title: str


class BoundariesOut(BaseModel):
    documents: list[Boundary]


class ClassificationTags(BaseModel):
    treatment: list[str] = Field(default_factory=list)
    imaging: list[str] = Field(default_factory=list)
    surgery: list[str] = Field(default_factory=list)
    therapy: list[str] = Field(default_factory=list)
    work_status: str | None = None


class ClassificationOut(BaseModel):
    doc_type: str
    confidence: float = Field(ge=0, le=1)
    provider_name: str | None = None
    provider_specialty: str | None = None
    facility: str | None = None
    npi: str | None = None
    service_date_start: str | None = Field(default=None, description="YYYY-MM-DD")
    service_date_end: str | None = None
    encounter_type: str | None = None
    body_parts: list[str] = Field(default_factory=list)
    tags: ClassificationTags = Field(default_factory=ClassificationTags)
    icd10_codes: list[str] = Field(default_factory=list)
    cpt_codes: list[str] = Field(default_factory=list)
    rationale: str


class CitedSentence(BaseModel):
    text: str
    citations: list[Cite] = Field(default_factory=list)
    evidence_type: Literal["objective", "subjective", "mixed", "administrative"] = "mixed"


class EpisodeSummaryOut(BaseModel):
    summary: list[CitedSentence]


class NarrativeChange(BaseModel):
    date: str | None = None
    direction: Literal["improved", "worsened", "plateaued", "new_finding"]
    description: str
    citations: list[Cite] = Field(default_factory=list)


class ClinicalSummaryOut(BaseModel):
    executive_summary: list[CitedSentence] = Field(description="<= 250 words in total")
    injury_and_mechanism: list[CitedSentence]
    diagnoses: list[CitedSentence]
    key_tests: list[CitedSentence]
    treatments_and_response: list[CitedSentence]
    recovery_trajectory: list[CitedSentence]
    daily_functioning: list[CitedSentence]
    work_status_and_restrictions: list[CitedSentence]
    key_narrative_changes: list[NarrativeChange]


class NecessityIndicator(BaseModel):
    indicator: str
    supports_necessity: bool
    citations: list[Cite] = Field(default_factory=list)
    guideline_rule_code: str | None = None


class UtilizationRequestOut(BaseModel):
    request_description: str
    request_type: Literal["mri", "esi", "pt_extension", "surgery", "medication", "other"]
    requesting_provider: str | None = None
    request_date: str | None = None
    necessity_indicators: list[NecessityIndicator]
    appropriateness: str
    progression: str
    barriers: list[str]
    unresolved_questions: list[str]
    ai_recommendation: str


class IssueOut(BaseModel):
    issue_type: Literal["inconsistency", "conflicting_diagnosis", "unexplained_change", "missing_evidence", "barrier"]
    description: str
    severity: Literal["low", "medium", "high"]
    suggested_action: str
    citations: list[Cite] = Field(default_factory=list)


class UtilizationOut(BaseModel):
    requests: list[UtilizationRequestOut]
    issues: list[IssueOut]


class FactOut(BaseModel):
    fact_type: str
    label: str = Field(description="short human readable label, e.g. 'Diagnosis: L4-L5 disc herniation'")
    value: dict = Field(description="structured value for the fact type")
    effective_date: str | None = Field(default=None, description="YYYY-MM-DD")
    confidence: float = Field(ge=0, le=1)
    citations: list[Cite]


class FactsOut(BaseModel):
    facts: list[FactOut]


class JudgeVerdict(BaseModel):
    key: str
    verdict: Literal["yes", "no", "partial"]
    reason: str


class JudgeOut(BaseModel):
    verdicts: list[JudgeVerdict]


class TurningPointOut(BaseModel):
    milestone_type: Literal["mmi", "rtw", "surgery", "diagnosis_change", "fce", "ime", "treatment_change",
                            "work_capacity_change"]
    date: str | None = None
    description: str
    before_state: dict
    after_state: dict
    impact: list[Literal["diagnosis", "treatment", "prognosis", "function", "work_status"]]
    fact_keys: list[str] = Field(default_factory=list)


class TurningPointsOut(BaseModel):
    turning_points: list[TurningPointOut]


class MilestoneImpactOut(BaseModel):
    milestone_key: str
    cause_effect: str
    work_capacity_link: str


class MilestoneImpactsOut(BaseModel):
    impacts: list[MilestoneImpactOut]


class GuidelineAssessmentOut(BaseModel):
    meets_criteria: Literal["yes", "no", "unclear"]
    missing_prerequisites: list[str]
    explanation: str


class ChronoDescription(BaseModel):
    key: str
    description: str
    key_findings: str


class ChronoDescriptionsOut(BaseModel):
    events: list[ChronoDescription]


class ReportSection(BaseModel):
    heading: str
    sentences: list[CitedSentence]


class ReportNarrativeOut(BaseModel):
    narrative: list[ReportSection] = Field(description="injury -> diagnosis -> treatment -> response -> function -> status")
    recommended_next_actions: list[str]


class DecisionDraftOut(BaseModel):
    treatment_recommendation: str
    disability_recommendation: str
    claim_trajectory: str
    rationale: str
    outstanding_questions: list[str]
    next_steps: list[str]


class RoutingRationaleOut(BaseModel):
    rationale: str
