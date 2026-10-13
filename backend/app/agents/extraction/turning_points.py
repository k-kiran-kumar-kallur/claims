"""turning_point_detector - Stage 4 Step 3 (PW-4.3): events that shifted diagnosis, plan, outlook, function or
work capacity, each with before/after state.  Also maintains the RTW status history (work-capacity trajectory)."""
from __future__ import annotations

import itertools

from sqlalchemy import select

from app.agents import heuristics as H
from app.agents.common import fmt_date, run_llm
from app.agents.taxonomy import MILESTONE_FACT_TYPES
from app.core.ids import uuid7
from app.models import ExtractedFact, Milestone, RtwStatus
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.schemas.llm import TurningPointsOut

USABLE = ("auto_verified", "validated", "edited")


def as_restriction_list(value) -> list[dict]:
    """Model output may give restrictions as text, a dict or a list of strings; store a list of objects."""
    if not value:
        return []
    if isinstance(value, str):
        return H.restrictions_of(value) or [{"type": "note", "limit": value}]
    if isinstance(value, dict):
        return [value]
    return [r if isinstance(r, dict) else {"type": "note", "limit": str(r)} for r in value]


def validated_facts(ctx: AgentContext, types: set[str] | None = None) -> list[ExtractedFact]:
    q = select(ExtractedFact).where(ExtractedFact.claim_id == ctx.claim_id, ExtractedFact.is_current.is_(True),
                                    ExtractedFact.validation_status.in_(USABLE))
    facts = ctx.db.execute(q).scalars().all()
    facts = [f for f in facts if types is None or f.fact_type in types]
    return sorted(facts, key=lambda f: (f.effective_date or "9999", f.created_at))


def rules_turning_points(facts: list[ExtractedFact]) -> list[dict]:
    out: list[dict] = []
    dx = [f for f in facts if f.fact_type == "diagnosis"]
    seen = []
    for f in dx:
        code = f.value.get("icd10")
        if seen and code not in [s.value.get("icd10") for s in seen] and (f.effective_date or "") > (seen[-1].effective_date or ""):
            prev = seen[-1]
            out.append({"milestone_type": "diagnosis_change", "date": f.effective_date,
                        "description": f"Diagnosis changed to {f.value.get('description')} ({code})",
                        "before_state": {"diagnosis": prev.value.get("description"), "icd10": prev.value.get("icd10")},
                        "after_state": {"diagnosis": f.value.get("description"), "icd10": code},
                        "impact": ["diagnosis", "treatment"], "fact_ids": [prev.id, f.id]})
        seen.append(f)
    for f in facts:
        if f.fact_type == "imaging" and H.positive_finding(str(f.value.get("findings", ""))):
            out.append({"milestone_type": "diagnosis_change", "date": f.effective_date,
                        "description": f"{f.value.get('modality')} {fmt_date(f.effective_date)}: {f.value.get('findings', '')[:160]}",
                        "before_state": {"imaging": "no structural diagnosis"}, "after_state": {"imaging": f.value.get("findings", "")[:200]},
                        "impact": ["diagnosis", "treatment", "prognosis"], "fact_ids": [f.id]})
        if f.fact_type == "procedure":
            out.append({"milestone_type": "surgery", "date": f.value.get("date") or f.effective_date,
                        "description": f"Surgery: {f.value.get('description', '')[:160]}",
                        "before_state": {"treatment": "conservative care"}, "after_state": {"treatment": "post-surgical recovery"},
                        "impact": ["treatment", "prognosis", "function", "work_status"], "fact_ids": [f.id]})
        if f.fact_type == "rtw" and f.value.get("capacity"):
            out.append({"milestone_type": "fce", "date": f.effective_date,
                        "description": f"FCE: {f.value['capacity']} physical demand level"
                                       + ("; does not meet job demands" if f.value.get("meets_job_demands") is False else ""),
                        "before_state": {"work_capacity": "undetermined"},
                        "after_state": {"work_capacity": f.value["capacity"], "meets_job_demands": f.value.get("meets_job_demands")},
                        "impact": ["function", "work_status"], "fact_ids": [f.id]})
        if f.fact_type == "mmi":
            out.append({"milestone_type": "mmi", "date": f.value.get("date") or f.effective_date,
                        "description": f.label, "before_state": {}, "after_state": {"mmi": f.value.get("status"),
                                                                                   "anticipated": f.value.get("anticipated_date")},
                        "impact": ["prognosis", "work_status"], "fact_ids": [f.id]})
    ws = [f for f in facts if f.fact_type == "work_status"]
    for prev, cur in itertools.pairwise(ws):
        a, b = prev.value.get("work_status"), cur.value.get("work_status")
        if a != b:
            out.append({"milestone_type": "work_capacity_change" if b != "full_duty" else "rtw", "date": cur.effective_date,
                        "description": f"Work status changed from {a} to {b}",
                        "before_state": {"work_status": a}, "after_state": {"work_status": b, "restrictions": cur.value.get("restrictions")},
                        "impact": ["work_status", "function"], "fact_ids": [prev.id, cur.id]})
    return out


@agent_node("turning_point_detector", "extraction")
def turning_point_detector(state: dict, ctx: AgentContext) -> dict:
    facts = validated_facts(ctx)
    milestone_facts = [f for f in facts if f.fact_type in MILESTONE_FACT_TYPES | {"imaging", "response"}]
    points, source = None, "rules"
    if ctx.llm.enabled and milestone_facts:
        listing = "\n".join(f"- key: {f.id} | {f.effective_date} | {f.fact_type} | {f.label}" for f in milestone_facts)
        res, source = run_llm(ctx, "turning_points", TurningPointsOut, facts=listing)
        if res is not None:
            valid = {f.id for f in milestone_facts}
            points = [{**tp.model_dump(exclude={"fact_keys"}), "fact_ids": [k for k in tp.fact_keys if k in valid]}
                      for tp in res.turning_points if any(k in valid for k in tp.fact_keys)]  # must be grounded in facts
    if points is None:
        points = rules_turning_points(facts)
    for old in ctx.db.execute(select(Milestone).where(Milestone.claim_id == ctx.claim_id, Milestone.status == "draft")).scalars():
        old.status = "superseded"
    for p in points:
        ctx.db.add(Milestone(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, milestone_type=p["milestone_type"],
                             milestone_date=p.get("date"), description=p["description"], before_state=p.get("before_state"),
                             after_state=p.get("after_state"), impact=p.get("impact", []), is_turning_point=True,
                             fact_ids=p.get("fact_ids", []), status="draft"))
    # work-capacity trajectory for the RTW tracker (PR-2)
    for old in ctx.db.execute(select(RtwStatus).where(RtwStatus.claim_id == ctx.claim_id)).scalars():
        ctx.db.delete(old)
    ws = [f for f in facts if f.fact_type == "work_status"]
    for i, f in enumerate(ws):
        nxt = ws[i + 1].effective_date if i + 1 < len(ws) else None
        ctx.db.add(RtwStatus(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, effective_date=f.effective_date,
                             work_status=f.value.get("work_status") or "off_work", restrictions=as_restriction_list(f.value.get("restrictions")),
                             source_fact_id=f.id, expected_next_change=nxt, employer_accommodation=f.value.get("employer_accommodation")))
    ctx.audit("milestones.detect", "claim", ctx.claim_id, after={"turning_points": len(points), "source": source})
    return {"stage_status": {"extraction": "completed"}}
