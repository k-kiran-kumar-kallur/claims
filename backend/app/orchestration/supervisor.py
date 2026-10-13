"""Supervisor router (spec §6.6): rule-based routing at the defined branch points, with loop guards.

Decisions: reclassify | request_documents | rerun_extraction | run_ime_analysis | escalate | continue.
Each loop has a max count (settings.LOOP_MAX); beyond it the router escalates to a supervisor and continues.
"""
from __future__ import annotations

from app.config import settings
from app.core.ids import uuid7
from app.models import Assignment
from app.orchestration.context import AgentContext


def escalate(ctx: AgentContext, reason: str) -> None:
    from app.agents.common import upsert_flag
    from app.orchestration.hitl import users_with_role
    from app.services.events import notify

    ctx.db.add(Assignment(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, role_key="claims_supervisor",
                          user_id=ctx.claim.assigned_supervisor_id, task=f"Escalation: {reason}"))
    upsert_flag(ctx, f"escalation:{ctx.node}:{reason[:60]}", flag_type="urgent", severity="high",
                title=f"Escalated to supervisor: {reason}", ai_recommendation="Supervisor review required")
    for uid in users_with_role(ctx, "claims_supervisor"):
        notify(ctx.db, uid, "escalation", f"Escalation on {ctx.claim.claim_number}", reason, claim_id=ctx.claim_id,
               link=f"/claims/{ctx.claim_id}")
    ctx.audit("workflow.escalate", "claim", ctx.claim_id, after={"reason": reason, "node": ctx.node})


def route_after_timeline(ctx: AgentContext, response: dict, iteration: int) -> tuple[str, dict]:
    decision = response.get("decision", "approve")
    if decision == "await_documents":
        return "request_documents", {}
    if decision == "corrections":
        if iteration + 1 > settings.LOOP_MAX:
            escalate(ctx, "timeline corrections loop exceeded the maximum; continuing with the current timeline")
            return "continue", {}
        return "reclassify", {"reclassify_document_ids": response.get("reclassify_document_ids", [])}
    return "continue", {}


def route_after_validation(ctx: AgentContext, per_doc: dict[str, tuple[int, int]], loops: int) -> tuple[str, list[str]]:
    """rerun_extraction when validation rejected more than 20% of a document's facts."""
    bad = [doc for doc, (rejected, total) in per_doc.items() if total >= 3 and rejected / total > 0.2]
    if not bad:
        return "continue", []
    if loops >= settings.LOOP_MAX:
        escalate(ctx, f"repeated low-quality extraction for {len(bad)} document(s)")
        return "continue", []
    return "rerun_extraction", bad


def route_after_summary(ctx: AgentContext, response: dict, iteration: int) -> str:
    if response.get("action") == "revise":
        if iteration + 1 > settings.LOOP_MAX:
            escalate(ctx, "summary revision loop exceeded the maximum")
            return "continue"
        return "revise"
    return "continue"


# ---- pure edge functions used by graph.add_conditional_edges ------------------------------------

def baseline_gate(state: dict) -> str:
    return "confirm" if state.get("baseline_needs_confirmation") else "ok"


def by_last_route(state: dict) -> str:
    return state.get("last_route") or "continue"


def risk_gate(state: dict) -> str:
    return "signoff" if state.get("requires_signoff") else "record"
