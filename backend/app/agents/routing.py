"""Routing Agent (POC-OUT 'direct complex or exceptional cases', PR-4): risk/complexity scoring and assignments."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.agents.common import run_llm
from app.agents.extraction.turning_points import validated_facts
from app.core.ids import to_iso, utcnow, uuid7
from app.models import Assignment, ClinicalIssue, Discrepancy, GuidelineFinding, RtwStatus, UtilizationAssessment
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import users_with_role
from app.schemas.llm import RoutingRationaleOut

WEIGHTS = {"surgery": 0.15, "conflicting_mmi": 0.15, "litigated": 0.15, "ttd_over_90_days": 0.1, "guideline_deviations": 0.05,
           "opioid_use": 0.1, "open_high_issues": 0.05, "reserve_impact": 0.1, "pending_ur": 0.05, "fce_below_job_demands": 0.1}


def score(ctx: AgentContext) -> tuple[float, list[dict]]:
    facts = validated_facts(ctx)
    claim = ctx.claim
    factors = []

    def add(name, present, detail, mult=1.0):
        if present:
            factors.append({"factor": name, "weight": round(WEIGHTS[name] * mult, 3), "detail": detail})

    procs = [f for f in facts if f.fact_type == "procedure"]
    add("surgery", bool(procs), f"{len(procs)} surgical procedure(s)")
    conflicting = ctx.db.execute(select(Discrepancy).where(Discrepancy.claim_id == ctx.claim_id, Discrepancy.discrepancy_type == "conflicting_mmi")).first()
    add("conflicting_mmi", bool(conflicting), "Conflicting MMI opinions")
    add("litigated", claim.litigated, "Claim is litigated")
    rtw = ctx.db.execute(select(RtwStatus).where(RtwStatus.claim_id == ctx.claim_id).order_by(RtwStatus.effective_date)).scalars().all()
    if claim.date_of_injury:
        first_rtw = next((r.effective_date for r in rtw if r.work_status in ("modified_duty", "full_duty") and r.effective_date), None)
        ttd_days = (date.fromisoformat(first_rtw or date.today().isoformat()) - date.fromisoformat(claim.date_of_injury)).days
        add("ttd_over_90_days", ttd_days > 90, f"{ttd_days} days of temporary total disability")
    devs = ctx.db.execute(select(GuidelineFinding).where(GuidelineFinding.claim_id == ctx.claim_id,
                                                         GuidelineFinding.finding_type.notin_(["compliant", "no_applicable_guideline"]))).scalars().all()
    add("guideline_deviations", bool(devs), f"{len(devs)} guideline deviation(s)", min(len(devs), 4))
    opioids = [f for f in facts if f.fact_type == "medication" and f.value.get("is_opioid")]
    add("opioid_use", len(opioids) >= 3, f"{len(opioids)} opioid fills")
    issues = ctx.db.execute(select(ClinicalIssue).where(ClinicalIssue.claim_id == ctx.claim_id, ClinicalIssue.severity == "high",
                                                       ClinicalIssue.status == "open")).scalars().all()
    add("open_high_issues", bool(issues), f"{len(issues)} open high-severity clinical issue(s)", min(len(issues), 2))
    add("reserve_impact", bool(procs), "Surgical costs drive reserve impact")
    ura = ctx.db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == ctx.claim_id, UtilizationAssessment.status == "ai_draft")).scalars().all()
    add("pending_ur", bool(ura), f"{len(ura)} pending utilization request(s)")
    fce = [f for f in facts if f.fact_type == "rtw" and f.value.get("meets_job_demands") is False]
    add("fce_below_job_demands", bool(fce), "FCE capacity below job demands")
    return round(min(sum(f["weight"] for f in factors), 1.0), 2), factors


@agent_node("routing_agent", "action")
def routing_agent(state: dict, ctx: AgentContext) -> dict:
    risk, factors = score(ctx)
    complexity = "exceptional" if risk >= 0.85 else ("complex" if risk >= 0.4 else "routine")
    rationale = None
    if ctx.llm.enabled:
        res, _ = run_llm(ctx, "routing_rationale", RoutingRationaleOut, score=risk, complexity=complexity,
                         factors="\n".join(f"- {f['factor']} (+{f['weight']}): {f['detail']}" for f in factors))
        rationale = res.rationale if res else None
    rationale = rationale or (f"Risk {risk:.2f} ({complexity}) driven by: " + ", ".join(f["detail"] for f in factors[:6]) if factors
                              else f"Risk {risk:.2f}: routine claim")
    claim = ctx.claim
    claim.risk_score, claim.complexity = risk, complexity
    claim.baseline = {**(claim.baseline or {}), "routing": {"risk_score": risk, "complexity": complexity, "factors": factors, "rationale": rationale}}
    plan = [("claims_examiner", claim.assigned_adjuster_id, "HITL-4 claims decision", 48)]
    if ctx.db.execute(select(UtilizationAssessment.id).where(UtilizationAssessment.claim_id == ctx.claim_id)).first():
        plan.append(("clinical_reviewer", claim.assigned_reviewer_id, "HITL-4 UR determination", 72))
    plan.append(("nurse_case_manager", claim.assigned_ncm_id, "Monitor RTW progress and care gaps", 120))
    if complexity == "exceptional" or risk >= ctx.settings.RISK_ESCALATION_THRESHOLD:
        plan.append(("claims_supervisor", claim.assigned_supervisor_id, "High-risk claim oversight / HITL-5 sign-off", 72))
    notified = 0
    for role, uid, task, hours in plan:
        ctx.db.add(Assignment(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, role_key=role, user_id=uid, task=task,
                              due_at=to_iso(utcnow() + timedelta(hours=hours))))
        targets = [uid] if uid else users_with_role(ctx, role)
        notified += ctx.tools.call("notification_tool", db=ctx.db, user_ids=targets, kind="assignment",
                                   title=f"{task} - {claim.claim_number}", body=f"Risk {risk:.2f} ({complexity})",
                                   claim_id=ctx.claim_id, link=f"/claims/{ctx.claim_id}")
    ctx.audit("claim.route", "claim", ctx.claim_id, after={"risk_score": risk, "complexity": complexity, "assignments": len(plan)})
    return {"risk_score": risk, "complexity": complexity}
