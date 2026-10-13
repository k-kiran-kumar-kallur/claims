"""HITL-5 Supervisor Sign-off and record_keeping / cms_sync nodes - Stage 7 Step 3 (PW-7.3)."""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select

from app.agents.common import fmt_date
from app.core.ids import now_iso, uuid7
from app.core.security import sha256_hex
from app.models import (
    Citation,
    Decision,
    Flag,
    FollowUp,
    Report,
    ReviewContext,
    URDetermination,
)
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import await_human
from app.repositories.docs import citation_dict
from app.services.report_service import render


@agent_node("hitl_signoff", "action")
def hitl_signoff(state: dict, ctx: AgentContext) -> dict:
    """HITL-5: required for high risk, exceptional complexity, any overridden AI flag, or manual escalation."""
    counts = state.get("retry_counts") or {}
    iteration = counts.get("decision_loop", 0)

    def payload():
        decisions = ctx.db.execute(select(Decision).where(Decision.claim_id == ctx.claim_id, Decision.status == "final")).scalars().all()
        overrides = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id, Flag.is_override.is_(True))).scalars().all()
        claim = ctx.claim
        return {"decisions": [{"id": d.id, "decision_type": d.decision_type, "outcome": d.outcome, "rationale": d.rationale,
                               "evidence_refs": d.evidence_refs, "outstanding_questions": d.outstanding_questions,
                               "next_steps": d.next_steps, "decided_by": d.decided_by} for d in decisions],
                "overridden_flags": [{"id": f.id, "title": f.title, "ai_recommendation": f.ai_recommendation,
                                      "human_action": f.human_action, "reason": f.reason} for f in overrides],
                "risk_score": claim.risk_score, "complexity": claim.complexity,
                "routing": (claim.baseline or {}).get("routing")}

    review, response = await_human(ctx, "HITL-5", iteration, "Supervisor sign-off of the decision record", payload, priority=1)
    action = response.get("action", "signoff")
    if action == "return":
        for d in ctx.db.execute(select(Decision).where(Decision.claim_id == ctx.claim_id, Decision.status == "final")).scalars():
            d.status = "returned"
        route = "return" if iteration + 1 <= ctx.settings.LOOP_MAX else "record"
    else:
        route = "record"
    return {"human_feedback": [{"checkpoint": "HITL-5", "review_id": review.id, "response": response}], "last_route": route,
            "retry_counts": {"decision_loop": iteration + (1 if action == "return" else 0)}}


def _record(ctx: AgentContext, d: Decision) -> dict:
    flags = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id, Flag.human_action.is_not(None))).scalars().all()
    urs = ctx.db.execute(select(URDetermination).where(URDetermination.claim_id == ctx.claim_id)).scalars().all()
    rc = ctx.db.execute(select(ReviewContext).where(ReviewContext.claim_id == ctx.claim_id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
    cites = []
    for ref in d.evidence_refs or []:
        if isinstance(ref, dict) and ref.get("citation_id"):
            c = ctx.db.get(Citation, ref["citation_id"])
            if c:
                cites.append(citation_dict(c))
        elif isinstance(ref, dict):
            cites.append(ref)
    return {"claim_number": ctx.claim.claim_number, "decision_id": d.id, "decision_type": d.decision_type, "outcome": d.outcome,
            "rationale": d.rationale, "review_question": rc.clinical_question if rc else None, "evidence": cites,
            "flags": [{"title": f.title, "ai_recommendation": f.ai_recommendation, "human_action": f.human_action,
                       "override": f.is_override, "reason": f.reason, "acted_by": f.acted_by, "acted_at": f.acted_at} for f in flags],
            "ur_determinations": [{"determination": u.determination, "rationale": u.clinical_rationale, "criteria_refs": u.criteria_refs,
                                   "reviewer_id": u.reviewer_id, "determined_at": u.determined_at} for u in urs],
            "outstanding_questions": d.outstanding_questions, "next_steps": d.next_steps,
            "decided_by": d.decided_by, "decided_at": d.decided_at, "signed_off_by": d.signed_off_by,
            "signed_off_at": d.signed_off_at, "signoff_comments": d.signoff_comments, "ai_draft": d.ai_draft,
            "communications": [f"Decision record logged to CMS on {fmt_date(date.today().isoformat())}"]}


@agent_node("record_keeping", "action")
def record_keeping(state: dict, ctx: AgentContext) -> dict:
    decisions = ctx.db.execute(select(Decision).where(Decision.claim_id == ctx.claim_id, Decision.status.in_(["final", "returned"]))).scalars().all()
    sealed = []
    for d in decisions:
        if d.status == "returned":
            d.status = "final"  # returned beyond the loop limit: recorded with the escalation trail
        existing_fu = {f.action for f in ctx.db.execute(select(FollowUp).where(FollowUp.decision_id == d.id)).scalars()}
        for i, step in enumerate(d.next_steps or []):
            text = step if isinstance(step, str) else step.get("action", "")
            due = (step.get("due_date") if isinstance(step, dict) else None) or (date.today() + timedelta(days=14 * (i + 1))).isoformat()
            if text and text not in existing_fu:
                ctx.db.add(FollowUp(id=uuid7(), claim_id=ctx.claim_id, decision_id=d.id, action=text, due_date=due,
                                    owner_id=ctx.claim.assigned_adjuster_id, created_by="record_keeping"))
        record = _record(ctx, d)
        d.record = record
        d.record_hash = sha256_hex(json.dumps(record, sort_keys=True, default=str))
        d.status = "sealed"
        sealed.append(d.id)
        ctx.audit("decision.seal", "decision", d.id, after={"record_hash": d.record_hash})
    # approved, exportable reports for the file / defence counsel (attorney role sees approved content only)
    report_ids = []
    for rtype in ("one_page_summary", "mmi_status", "medical_chronology", "case_progress", "decision_provenance"):
        rep = Report(id=uuid7(), claim_id=ctx.claim_id, report_type=rtype, format="pdf", is_approved_content=True,
                     requested_by="record_keeping", status="queued")
        ctx.db.add(rep)
        ctx.db.flush()
        render(ctx.db, rep)
        report_ids.append(rep.id)
    ctx.claim.status = "decided"
    return {"report_ids": report_ids, "decision_id": sealed[0] if sealed else state.get("decision_id")}


@agent_node("cms_sync", "action")
def cms_sync(state: dict, ctx: AgentContext) -> dict:
    """Outbox pattern: post each sealed decision record to the CMS (mock connector in v1)."""
    results = []
    for d in ctx.db.execute(select(Decision).where(Decision.claim_id == ctx.claim_id, Decision.status == "sealed")).scalars():
        payload = {"entity_type": "decision_record", "entity_id": d.id, "claim_number": ctx.claim.claim_number,
                   "decision_type": d.decision_type, "outcome": d.outcome, "record_hash": d.record_hash,
                   "diary": [s if isinstance(s, str) else s.get("action") for s in (d.next_steps or [])], "posted_at": now_iso()}
        res = ctx.tools.call("cms_connector_tool", db=ctx.db, operation="post_record", claim_id=ctx.claim_id, payload=payload)
        results.append(res)
        ctx.audit("cms.sync", "decision", d.id, after={"status": res["status"], "external_ref": res.get("external_ref"),
                                                       "payload_hash": sha256_hex(json.dumps(payload, sort_keys=True))})
    return {"stage_status": {"action": "completed"}, "current_stage": "done"}
