"""Claim workflow StateGraph (spec §6.2, §18.5).  Stage = node; HITL checkpoints are interrupt() nodes."""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.chronology import chronology_agent
from app.agents.classification import classification_agent, classify_document
from app.agents.clinical import clinical_summary_agent, utilization_agent
from app.agents.decision_support import decision_support_agent, hitl_decision, ur_gate
from app.agents.extraction.clinical import clinical_fact_extractor
from app.agents.extraction.dispatch import BASE_EXTRACTORS, extraction_agent, extraction_fanout
from app.agents.extraction.mmi import ime_extractor, mmi_extractor
from app.agents.extraction.rtw import rtw_extractor
from app.agents.extraction.treatment_plan import treatment_plan_extractor
from app.agents.extraction.turning_points import turning_point_detector
from app.agents.guideline import guideline_agent
from app.agents.intake import await_documents, hitl_baseline, intake_agent
from app.agents.organization import hitl_timeline_check, organization_agent
from app.agents.record_keeping import cms_sync, hitl_signoff, record_keeping
from app.agents.report import hitl_summary_review, report_agent
from app.agents.routing import routing_agent
from app.agents.validation import hitl_fact_validation, validation_agent
from app.orchestration.checkpointer import get_checkpointer
from app.orchestration.state import ClaimWorkflowState
from app.orchestration.supervisor import baseline_gate, by_last_route, risk_gate

GRAPH_VERSION = "1.0.0"

NODES = {fn.node_name: fn for fn in [
    intake_agent, hitl_baseline, await_documents, classification_agent, classify_document, organization_agent,
    hitl_timeline_check, clinical_summary_agent, utilization_agent, extraction_agent, mmi_extractor, rtw_extractor,
    treatment_plan_extractor, clinical_fact_extractor, ime_extractor, validation_agent, hitl_fact_validation,
    turning_point_detector, guideline_agent, chronology_agent, report_agent, hitl_summary_review,
    decision_support_agent, routing_agent, hitl_decision, ur_gate, hitl_signoff, record_keeping, cms_sync,
]}

NODE_STAGE = {name: fn.stage for name, fn in NODES.items()}


def classify_fanout(state: dict):
    """Per-document classification fan-out with the Send API."""
    targets = state.get("document_ids") or []
    if not targets:
        return "organization_agent"
    return [Send("classify_document", {"run_id": state["run_id"], "claim_id": state["claim_id"], "document_id": d})
            for d in targets]


def build_graph(checkpointer=None):
    g = StateGraph(ClaimWorkflowState)
    for name, fn in NODES.items():
        g.add_node(name, fn)
    # Stage 1 - intake (+ HITL-0)
    g.add_edge(START, "intake_agent")
    g.add_conditional_edges("intake_agent", baseline_gate, {"confirm": "hitl_baseline", "ok": "classification_agent"})
    g.add_edge("hitl_baseline", "classification_agent")
    # Stage 2 - classification fan-out, organization, HITL-1, supervisor loop
    g.add_conditional_edges("classification_agent", classify_fanout, ["classify_document", "organization_agent"])
    g.add_edge("classify_document", "organization_agent")
    g.add_edge("organization_agent", "hitl_timeline_check")
    g.add_conditional_edges("hitl_timeline_check", by_last_route,
                            {"reclassify": "classification_agent", "request_documents": "await_documents",
                             "continue": "clinical_summary_agent"})
    g.add_edge("await_documents", "intake_agent")
    # Stage 3 - clinical understanding
    g.add_edge("clinical_summary_agent", "utilization_agent")
    g.add_edge("utilization_agent", "extraction_agent")
    # Stage 4 - parallel extractors -> validation -> HITL-2 -> turning points
    g.add_conditional_edges("extraction_agent", extraction_fanout, BASE_EXTRACTORS + ["ime_extractor"])
    for ex in BASE_EXTRACTORS + ["ime_extractor"]:
        g.add_edge(ex, "validation_agent")
    g.add_conditional_edges("validation_agent", by_last_route,
                            {"rerun_extraction": "extraction_agent", "continue": "hitl_fact_validation"})
    g.add_edge("hitl_fact_validation", "turning_point_detector")
    # Stage 5 - guidelines
    g.add_edge("turning_point_detector", "guideline_agent")
    # Stage 6 - chronology, reports, HITL-3
    g.add_edge("guideline_agent", "chronology_agent")
    g.add_edge("chronology_agent", "report_agent")
    g.add_edge("report_agent", "hitl_summary_review")
    g.add_conditional_edges("hitl_summary_review", by_last_route, {"revise": "report_agent", "continue": "decision_support_agent"})
    # Stage 7 - decision support, routing, HITL-4 (+UR), risk gate, HITL-5, record keeping, CMS
    g.add_edge("decision_support_agent", "routing_agent")
    g.add_edge("routing_agent", "hitl_decision")
    g.add_edge("hitl_decision", "ur_gate")
    g.add_conditional_edges("ur_gate", risk_gate, {"signoff": "hitl_signoff", "record": "record_keeping"})
    g.add_conditional_edges("hitl_signoff", by_last_route, {"return": "hitl_decision", "record": "record_keeping"})
    g.add_edge("record_keeping", "cms_sync")
    g.add_edge("cms_sync", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else get_checkpointer())


@lru_cache
def get_graph():
    return build_graph()


def mermaid() -> str:
    return build_graph(checkpointer=False).get_graph().draw_mermaid()
