"""LangGraph state schema (spec §6.3).  Large artifacts live in SQLite; the state carries ids and small flags."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

STAGES = ["intake", "classification", "clinical_review", "extraction", "guideline_review", "output", "action"]


def merge_dict(left: dict | None, right: dict | None) -> dict:
    out = dict(left or {})
    out.update(right or {})
    return out


def last_value(left: Any, right: Any) -> Any:
    return right


class ClaimWorkflowState(TypedDict, total=False):
    # identity
    run_id: str
    claim_id: str
    initiated_by: str
    mode: str                                   # full | incremental
    # stage tracking
    current_stage: Annotated[str, last_value]
    stage_status: Annotated[dict[str, str], merge_dict]
    # references to persisted artifacts (ids only)
    document_ids: Annotated[list[str], last_value]
    review_context_id: Annotated[str | None, last_value]
    timeline_version: Annotated[int, last_value]
    summary_id: Annotated[str | None, last_value]
    report_ids: Annotated[list[str], last_value]
    decision_id: Annotated[str | None, last_value]
    reclassify_document_ids: Annotated[list[str], last_value]
    rerun_extraction_document_ids: Annotated[list[str], last_value]
    extractors: Annotated[list[str], last_value]
    # findings for routing (small)
    baseline_needs_confirmation: Annotated[bool, last_value]
    missing_documents: Annotated[list[dict], operator.add]
    urgent_flags: Annotated[list[dict], operator.add]
    clinical_issues: Annotated[list[dict], operator.add]
    guideline_flags: Annotated[list[dict], operator.add]
    low_confidence_items: Annotated[list[str], operator.add]
    risk_score: Annotated[float | None, last_value]
    complexity: Annotated[str | None, last_value]
    requires_signoff: Annotated[bool, last_value]
    # HITL
    pending_review: Annotated[dict | None, last_value]
    human_feedback: Annotated[list[dict], operator.add]
    last_route: Annotated[str | None, last_value]
    # errors and control
    errors: Annotated[list[dict], operator.add]
    retry_counts: Annotated[dict[str, int], merge_dict]
    cancel_requested: Annotated[bool, last_value]


def initial_state(run_id: str, claim_id: str, user_id: str, mode: str = "full") -> ClaimWorkflowState:
    return ClaimWorkflowState(
        run_id=run_id, claim_id=claim_id, initiated_by=user_id, mode=mode, current_stage="intake",
        stage_status={s: "pending" for s in STAGES}, document_ids=[], review_context_id=None, timeline_version=0,
        summary_id=None, report_ids=[], decision_id=None, reclassify_document_ids=[], rerun_extraction_document_ids=[], extractors=[],
        baseline_needs_confirmation=False, missing_documents=[], urgent_flags=[], clinical_issues=[],
        guideline_flags=[], low_confidence_items=[], risk_score=None, complexity=None, requires_signoff=False,
        pending_review=None, human_feedback=[], last_route=None, errors=[], retry_counts={}, cancel_requested=False)
