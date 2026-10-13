"""Stage 7: Decision Support Agent (POC-7, PW-7.1), HITL-4 Claims Decision and HITL-4 UR Determination (PW-7.2)."""
from __future__ import annotations

from sqlalchemy import select

from app.agents.common import fmt_date, run_llm, upsert_flag
from app.agents.extraction.turning_points import validated_facts
from app.agents.report import _context, next_actions
from app.core.ids import uuid7
from app.models import (
    Citation,
    ClinicalIssue,
    Decision,
    Discrepancy,
    Flag,
    GuidelineFinding,
    Review,
    ReviewContext,
    Summary,
    URDetermination,
    UtilizationAssessment,
)
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import await_human, ensure_review
from app.repositories.docs import citation_dict
from app.schemas.llm import DecisionDraftOut


def _fact_cites(ctx: AgentContext, fid: str) -> list[dict]:
    return [citation_dict(c) for c in ctx.db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id == fid)).scalars()][:3]


def build_flags(ctx: AgentContext) -> int:
    facts = validated_facts(ctx)
    mmi = [f for f in facts if f.fact_type == "mmi"]
    if mmi:
        m = mmi[-1]
        rec = (f"Accept: MMI not reached; diary re-evaluation {fmt_date(m.value.get('anticipated_date'))} and request an impairment rating at MMI"
               if m.value.get("status") != "reached" else "Accept MMI; obtain impairment rating and evaluate indemnity transition")
        upsert_flag(ctx, "mmi:latest", flag_type="mmi_status", severity="medium", title=m.label, ref_type="fact", ref_id=m.id,
                    detail=f"Declared by {m.value.get('declaring_provider') or 'treating provider'} on {fmt_date(m.effective_date)}",
                    evidence=_fact_cites(ctx, m.id), ai_recommendation=rec)
    ws = [f for f in facts if f.fact_type == "work_status"]
    fce = [f for f in facts if f.fact_type == "rtw" and f.value.get("capacity")]
    if ws or fce:
        latest = ws[-1] if ws else None
        restr = "; ".join(r.get("type", "") + (f" {r['limit_lb']} lb {r.get('frequency', '')}" if r.get("limit_lb") else f" {r.get('limit') or r.get('max_hours_per_day') or r.get('alternate_every_minutes') or ''}")
                          for r in (latest.value.get("restrictions") or [])) if latest else ""
        title = f"RTW limits: {latest.value.get('work_status', '').replace('_', ' ')}" + (f" - {restr}" if restr else "") if latest else "RTW limits"
        if fce:
            title += f" (FCE: {fce[-1].value['capacity']})"
        upsert_flag(ctx, "rtw:latest", flag_type="rtw_limit", severity="medium", title=title[:255], ref_type="fact",
                    ref_id=(latest or fce[-1]).id, evidence=_fact_cites(ctx, (latest or fce[-1]).id) + (_fact_cites(ctx, fce[-1].id) if fce else []),
                    ai_recommendation="Approve these restrictions as the current RTW limits; confirm employer accommodation or vocational options")
    for issue in ctx.db.execute(select(ClinicalIssue).where(ClinicalIssue.claim_id == ctx.claim_id, ClinicalIssue.status == "open",
                                                            ClinicalIssue.severity == "high",
                                                            ClinicalIssue.issue_type != "missing_evidence")).scalars():
        upsert_flag(ctx, f"issue:{issue.id}", flag_type="clinical_issue", severity="high", title=issue.description[:255],
                    ref_type="clinical_issue", ref_id=issue.id, ai_recommendation=issue.suggested_action)
    return len(ctx.db.execute(select(Flag.id).where(Flag.claim_id == ctx.claim_id)).all())


def rules_draft(ctx: AgentContext) -> DecisionDraftOut:
    c = _context(ctx)
    findings = c["findings"]
    pt = next((g for g in findings if g.finding_type == "off_guideline_request"), None)
    op = next((g for g in findings if "opioid" in g.title.lower()), None)
    rtw = next((f for f in reversed(c["facts"]) if f.fact_type == "rtw" and f.value.get("capacity")), None)
    mmi = next((f for f in reversed(c["facts"]) if f.fact_type == "mmi"), None)
    treat = []
    if pt:
        treat.append(f"Do not authorize as requested: {pt.title.replace('Off-guideline request: ', '')} ({pt.explanation[:160]})")
    if rtw and rtw.value.get("meets_job_demands") is False:
        treat.append("Consider authorizing a time-limited work hardening program recommended by the FCE")
    if op:
        treat.append("Require an opioid taper plan and functional goals")
    return DecisionDraftOut(
        treatment_recommendation="; ".join(treat) or "Continue current treatment plan consistent with guidelines",
        disability_recommendation=(f"Work capacity {rtw.value['capacity']} per FCE; claimant cannot return to the regular job. "
                                   "Offer light duty within restrictions; if unavailable, temporary disability continues." if rtw else
                                   "Maintain current work status pending updated provider work-status slip"),
        claim_trajectory=(f"MMI anticipated {fmt_date(mmi.value.get('anticipated_date'))}; impairment rating expected at MMI. Monitor "
                          "for vocational rehabilitation needs." if mmi and mmi.value.get("anticipated_date") else "Obtain MMI opinion"),
        rationale="Draft derived from validated facts, guideline findings and the FCE; see evidence links. Requires examiner decision.",
        outstanding_questions=[r.description for r in c["reqs"]][:4] + [d.description for d in ctx.db.execute(
            select(Discrepancy).where(Discrepancy.claim_id == ctx.claim_id, Discrepancy.status == "open")).scalars()][:2],
        next_steps=next_actions(c))


@agent_node("decision_support_agent", "action")
def decision_support_agent(state: dict, ctx: AgentContext) -> dict:
    ctx.claim.current_stage = "action"
    n_flags = build_flags(ctx)
    draft, src = None, "rules"
    if ctx.llm.enabled:
        c = _context(ctx)
        one = ctx.db.execute(select(Summary).where(Summary.claim_id == ctx.claim_id, Summary.summary_type == "one_page",
                                                   Summary.status.in_(["approved", "in_review"])).order_by(Summary.created_at.desc()).limit(1)).scalar_one_or_none()
        flags = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id)).scalars().all()
        draft, src = run_llm(ctx, "decision_draft", DecisionDraftOut, claim=f"{ctx.claim.claim_number} DOI {ctx.claim.date_of_injury}",
                             question=c["rc"].clinical_question if c["rc"] else "",
                             flags="\n".join(f"- [{f.flag_type}] {f.title}: {f.ai_recommendation}" for f in flags),
                             summary=one.content_md[:8000] if one else "")
    draft = draft or rules_draft(ctx)
    for old in ctx.db.execute(select(Decision).where(Decision.claim_id == ctx.claim_id, Decision.status == "draft")).scalars():
        ctx.db.delete(old)
    row = Decision(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, decision_type="claim_trajectory", outcome="pending examiner decision",
                   rationale=draft.rationale, outstanding_questions=draft.outstanding_questions, next_steps=draft.next_steps,
                   ai_draft={**draft.model_dump(), "label": "AI draft - not a determination", "source": src}, status="draft")
    ctx.db.add(row)
    ctx.audit("decision.draft", "decision", row.id, after={"flags": n_flags, "source": src})
    return {"decision_id": row.id}


def decision_payload(ctx: AgentContext, decision_id: str | None) -> dict:
    claim = ctx.claim
    flags = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id).order_by(Flag.severity.desc())).scalars().all()
    draft = ctx.db.get(Decision, decision_id) if decision_id else None
    findings = ctx.db.execute(select(GuidelineFinding).where(GuidelineFinding.claim_id == ctx.claim_id)).scalars().all()
    uas = ctx.db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == ctx.claim_id)).scalars().all()
    rc = ctx.db.execute(select(ReviewContext).where(ReviewContext.claim_id == ctx.claim_id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
    order = {"high": 0, "medium": 1, "low": 2}
    return {"risk_score": claim.risk_score, "complexity": claim.complexity,
            "review_question": rc.clinical_question if rc else None,
            "flags": sorted([{"id": f.id, "flag_type": f.flag_type, "severity": f.severity, "title": f.title, "detail": f.detail,
                              "ai_recommendation": f.ai_recommendation, "evidence": f.evidence, "human_action": f.human_action}
                             for f in flags], key=lambda x: (x["human_action"] is not None, order.get(x["severity"], 3))),
            "decision_draft": draft.ai_draft if draft else None, "decision_id": decision_id,
            "guideline_findings": [{"id": g.id, "title": g.title, "finding_type": g.finding_type, "severity": g.severity, "status": g.status} for g in findings],
            "utilization_assessments": [{"id": u.id, "request": u.request_description, "ai_recommendation": u.ai_recommendation,
                                         "status": u.status} for u in uas]}


@agent_node("hitl_decision", "action")
def hitl_decision(state: dict, ctx: AgentContext) -> dict:
    """HITL-4: Claims Examiner decides with one-click flag approvals; the UR reviewer works in parallel (HITL-4-UR)."""
    counts = state.get("retry_counts") or {}
    iteration = counts.get("decision_loop", 0)
    pending_ur = ctx.db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == ctx.claim_id,
                                                                    UtilizationAssessment.status == "ai_draft")).scalars().all()
    if pending_ur:
        ensure_review(ctx, "HITL-4-UR", iteration, f"UR determination: {len(pending_ur)} request(s)",
                      lambda: {"utilization_assessments": [{"id": u.id, "request": u.request_description, "type": u.request_type,
                                                            "requesting_provider": u.requesting_provider, "request_date": u.request_date,
                                                            "necessity_indicators": u.necessity_indicators, "appropriateness": u.appropriateness,
                                                            "progression": u.progression, "barriers": u.barriers,
                                                            "unresolved_questions": u.unresolved_questions,
                                                            "ai_recommendation": u.ai_recommendation} for u in pending_ur],
                               "label": "AI draft - not a determination"}, priority=2, blocks_run=False)
    review, response = await_human(ctx, "HITL-4", iteration, "Claims decision: review AI flags and record the decision",
                                   lambda: decision_payload(ctx, state.get("decision_id")), priority=2)
    overrides = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id, Flag.is_override.is_(True))).scalars().all()
    claim = ctx.claim
    requires = bool(response.get("escalate")) or bool(overrides) or (claim.risk_score or 0) >= ctx.settings.RISK_ESCALATION_THRESHOLD \
        or claim.complexity == "exceptional"
    final = ctx.db.execute(select(Decision).where(Decision.claim_id == ctx.claim_id, Decision.status == "final")).scalars().all()
    for d in final:
        d.requires_signoff = requires
    return {"human_feedback": [{"checkpoint": "HITL-4", "review_id": review.id, "response": response}],
            "requires_signoff": requires, "decision_id": final[0].id if final else state.get("decision_id")}


@agent_node("ur_gate", "action")
def ur_gate(state: dict, ctx: AgentContext) -> dict:
    """Waits for the UR determination branch (PW-7.2) when treatment requests exist."""
    iteration = (state.get("retry_counts") or {}).get("decision_loop", 0)
    key = f"{ctx.run_id}:HITL-4-UR:{iteration}"
    review = ctx.db.execute(select(Review).where(Review.review_key == key)).scalar_one_or_none()
    pending = ctx.db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == ctx.claim_id,
                                                                 UtilizationAssessment.status == "ai_draft")).scalars().all()
    if review is None or review.status == "submitted" or not pending:
        return {}
    review.blocks_run = True
    review, response = await_human(ctx, "HITL-4-UR", iteration, review.title, lambda: review.payload)
    n = ctx.db.execute(select(URDetermination).where(URDetermination.claim_id == ctx.claim_id)).all()
    return {"human_feedback": [{"checkpoint": "HITL-4-UR", "review_id": review.id, "determinations": len(n)}]}
