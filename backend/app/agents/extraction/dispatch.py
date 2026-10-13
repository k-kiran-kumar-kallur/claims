"""extraction_agent dispatcher: chooses targets and the parallel extractors (spec §6.2 extraction fan-out)."""
from __future__ import annotations

from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.repositories.docs import load_doc_views

BASE_EXTRACTORS = ["mmi_extractor", "rtw_extractor", "treatment_plan_extractor", "clinical_fact_extractor"]


@agent_node("extraction_agent", "extraction")
def extraction_agent(state: dict, ctx: AgentContext) -> dict:
    views = load_doc_views(ctx.db, ctx.claim_id)
    extractors = list(BASE_EXTRACTORS)
    if any(v.doc_type == "IME Report" for v in views):  # supervisor decision: run_ime_analysis
        extractors.append("ime_extractor")
    ctx.claim.current_stage = "extraction"
    ctx.emit("tool_called", {"tool": "extraction_dispatch", "extractors": extractors,
                             "documents": len(state.get("rerun_extraction_document_ids") or views)})
    return {"extractors": extractors}


def extraction_fanout(state: dict) -> list[str]:
    return state.get("extractors") or BASE_EXTRACTORS
