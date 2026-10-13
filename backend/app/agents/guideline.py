"""Guideline Agent - Stage 5 (POC-5, PW-5.1, PW-5.2).

Never relies on model memory for guideline criteria: every finding cites a rule loaded into `guideline_rules`
(or is recorded as 'no_applicable_guideline').  Metrics (visit counts, durations) are computed deterministically.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select

from app.agents import heuristics as H
from app.agents.common import fmt_date, run_llm, upsert_flag
from app.agents.extraction.turning_points import validated_facts
from app.core.ids import uuid7
from app.models import Citation, GuidelineFinding, Milestone, RtwStatus, Summary, UtilizationAssessment
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.repositories.docs import citation_dict, save_citations
from app.schemas.llm import GuidelineAssessmentOut, MilestoneImpactsOut


def _fact_cites(ctx: AgentContext, fact_ids: list[str]) -> list[dict]:
    rows = ctx.db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id.in_(fact_ids))).scalars().all()
    return [citation_dict(c) for c in rows]


# ---- Step 1: case-fact narrative arc (PW-5.1) -----------------------------------------------------

ARC = [("Injury details", {"mechanism", "causation"}), ("Symptom progression", {"symptom"}),
       ("Objective findings", {"exam_finding", "imaging", "diagnosis"}), ("Treatment plans", {"procedure", "treatment_plan"}),
       ("Clinical responses", {"response"}), ("Current work status", {"work_status", "rtw", "restriction", "mmi"})]


def build_case_fact_sheet(ctx: AgentContext) -> str:
    from app.agents.clinical import persist_cited_document

    facts = validated_facts(ctx)
    sections = []
    for heading, types in ARC:
        items = [f for f in facts if f.fact_type in types]
        if heading == "Current work status":
            items = items[-4:]
        elif heading == "Symptom progression":
            items = items[:2] + items[-3:] if len(items) > 5 else items
        sentences = [{"text": f"{fmt_date(f.effective_date)}: {f.label}", "citations": _fact_cites(ctx, [f.id]),
                      "evidence_type": "subjective" if f.fact_type == "symptom" else "objective"} for f in items]
        sections.append((heading, sentences))
    sid = uuid7()
    md, js = persist_cited_document(ctx, "summary", sid, sections)
    for old in ctx.db.execute(select(Summary).where(Summary.claim_id == ctx.claim_id, Summary.summary_type == "case_facts",
                                                    Summary.status != "superseded")).scalars():
        old.status = "superseded"
    ctx.db.add(Summary(id=sid, claim_id=ctx.claim_id, summary_type="case_facts", content_md=md, content_json=js,
                       status="draft", generated_by_run_id=ctx.run_id))
    return sid


# ---- Step 2: milestone impacts (PW-5.2) -------------------------------------------------------------

def _rules_impact(m: Milestone, rtw: list[RtwStatus]) -> tuple[str, str]:
    after = m.after_state or {}
    status_after = next((r for r in rtw if (r.effective_date or "") >= (m.milestone_date or "")), None)
    wc = f"Work status after this event: {status_after.work_status.replace('_', ' ')}" if status_after else "No subsequent work-status change documented"
    if m.milestone_type == "surgery":
        return ("Moved care from conservative management to post-surgical recovery and rehabilitation; extends the "
                "disability period and drives medical cost exposure.", wc)
    if m.milestone_type == "diagnosis_change":
        return (f"Established a structural diagnosis ({after.get('icd10') or after.get('imaging', '')[:60]}), changing the "
                "treatment plan and prognosis.", wc)
    if m.milestone_type == "fce":
        return (f"Objectively defined work capacity at the {after.get('work_capacity')} level"
                + (", below the job's demands - a return to the regular job is not yet possible" if after.get("meets_job_demands") is False else ""),
                f"Defines restrictions for RTW at {after.get('work_capacity')} duty")
    if m.milestone_type in ("work_capacity_change", "rtw"):
        return (f"Changed work status from {(m.before_state or {}).get('work_status')} to {after.get('work_status')}, "
                "affecting indemnity (TTD vs modified duty).", f"Work capacity: {after.get('work_status')}")
    if m.milestone_type == "mmi":
        return ("Determines when permanent impairment can be rated and indemnity may transition; drives diary dates.",
                f"MMI status: {after.get('mmi')}" + (f", anticipated {after.get('anticipated')}" if after.get("anticipated") else ""))
    return (m.description, wc)


def map_milestone_impacts(ctx: AgentContext) -> int:
    ms = ctx.db.execute(select(Milestone).where(Milestone.claim_id == ctx.claim_id, Milestone.status == "draft")
                        .order_by(Milestone.milestone_date)).scalars().all()
    rtw = ctx.db.execute(select(RtwStatus).where(RtwStatus.claim_id == ctx.claim_id).order_by(RtwStatus.effective_date)).scalars().all()
    llm = None
    if ctx.llm.enabled and ms:
        res, _ = run_llm(ctx, "milestone_impacts", MilestoneImpactsOut,
                         milestones="\n".join(f"- key: {m.id} | {m.milestone_date} | {m.milestone_type} | {m.description}" for m in ms),
                         rtw="\n".join(f"- {r.effective_date}: {r.work_status} {r.restrictions}" for r in rtw))
        llm = {i.milestone_key: i for i in res.impacts} if res else None
    for m in ms:
        if llm and m.id in llm:
            m.impact_narrative, m.work_capacity_link = llm[m.id].cause_effect, llm[m.id].work_capacity_link
        else:
            m.impact_narrative, m.work_capacity_link = _rules_impact(m, rtw)
    return len(ms)


# ---- deviation analysis (POC-5) -----------------------------------------------------------------------

def _rule(ctx: AgentContext, query: str, category: str, procedure_codes: list[str] | None = None,
          diagnosis_codes: list[str] | None = None) -> dict | None:
    claim = ctx.claim
    hits = ctx.tools.call("guideline_retrieval_tool", db=ctx.db, query=query, jurisdiction=claim.jurisdiction_state,
                          body_part=" ".join(claim.body_parts or []), category=category,
                          procedure_codes=procedure_codes or [], diagnosis_codes=diagnosis_codes or [], limit=3)
    return hits[0] if hits else None


def _assess(ctx: AgentContext, rule: dict, request: str, facts_text: str, rules_verdict: tuple[str, list[str], str]) -> tuple[str, list[str], str]:
    res, _ = run_llm(ctx, "guideline_assessment", GuidelineAssessmentOut, rule_code=rule["rule_code"],
                     rule_text=rule["criteria_text"], prerequisites=rule.get("prerequisites") or [], request=request, facts=facts_text)
    if res is None:
        return rules_verdict
    if rules_verdict[0] in ("yes", "no") and res.meets_criteria in ("yes", "no") and res.meets_criteria != rules_verdict[0]:
        # model and deterministic evidence disagree: never auto-resolve, route to the reviewer
        return "unclear", res.missing_prerequisites, f"{res.explanation} (Deterministic check: {rules_verdict[2]}) Reviewer to confirm."
    return res.meets_criteria, res.missing_prerequisites, res.explanation


def analyse_deviations(ctx: AgentContext) -> list[dict]:
    facts = validated_facts(ctx)
    claim = ctx.claim
    doi = claim.date_of_injury
    findings: list[dict] = []
    procs = [f for f in facts if f.fact_type == "procedure"]
    cpts = [f.value.get("cpt") for f in procs if f.value.get("cpt")]
    dx = sorted({f.value.get("icd10") for f in facts if f.fact_type == "diagnosis" and f.value.get("icd10")})
    surgery_date = min((d for d in (H.normalize_date(str(f.value.get("date") or f.effective_date or "")) for f in procs) if d), default=None)

    def add(kind, severity, title, rule, explanation, recommendation, evidence_ids, metrics=None, key=None):
        findings.append({"finding_type": kind, "severity": severity, "title": title, "rule": rule, "explanation": explanation,
                         "recommendation": recommendation, "evidence": _fact_cites(ctx, evidence_ids), "metrics": metrics or {},
                         "treatment_ref": evidence_ids[0] if evidence_ids else None, "key": key or title})

    # (a) therapy visit counts / duration
    pt_visit_facts = [f for f in facts if f.fact_type in ("treatment_plan", "symptom", "response")]
    visits = _documented_visits(ctx)
    if visits:
        rule = _rule(ctx, "physical therapy post-surgical discectomy visits" if procs else "physical therapy low back visits",
                     "therapy", cpts, dx)
        if rule is None:
            add("no_applicable_guideline", "low", "Physical therapy - no applicable guideline rule found", None,
                "No guideline rule in the store matches this therapy course.", "Load the applicable guideline", [], key="pt:none")
        else:
            calc = ctx.tools.call("duration_calculator_tool", actual_visits=visits["count"], max_visits=rule.get("max_visits"),
                                  start_date=visits["start"], end_date=visits["end"], max_duration_days=rule.get("max_duration_days"))
            ev = [f.id for f in pt_visit_facts if f.effective_date in (visits["start"], visits["end"])][:3]
            if calc["exceeds"]:
                add("excessive_duration", "high" if calc["visits_exceeded_by"] >= 6 else "medium",
                    f"Physical therapy exceeds guideline: {visits['count']} visits vs {rule['max_visits']} recommended", rule,
                    f"{visits['count']} visits from {fmt_date(visits['start'])} to {fmt_date(visits['end'])} ({calc['actual_days']} days) "
                    f"vs guideline {rule['max_visits']} visits / {rule.get('max_duration_days')} days.",
                    "Require documented objective functional improvement before further visits; consider work hardening/HEP.",
                    ev, calc, key="pt:visits")
            else:
                add("compliant", "low", "Physical therapy within guideline visit count", rule,
                    f"{visits['count']} visits vs {rule['max_visits']} recommended.", None, ev, calc, key="pt:visits")
    # (b) pending requests (utilization assessments)
    for ua in ctx.db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == ctx.claim_id,
                                                                 UtilizationAssessment.run_id == ctx.run_id)).scalars():
        category = {"pt_extension": "therapy", "mri": "imaging", "esi": "injection", "surgery": "surgery", "medication": "medication"}.get(ua.request_type)
        rule = _rule(ctx, ua.request_description, category) if category else None
        if rule is None:
            add("no_applicable_guideline", "low", f"No applicable guideline for request: {ua.request_description[:80]}", None,
                "No rule in the guideline store applies; the reviewer must apply clinical judgement.", None, [], key=f"req:{ua.id}")
            continue
        stalled = any(not i.get("supports_necessity") for i in ua.necessity_indicators or [])
        exceeded = bool(visits and rule.get("max_visits") and visits["count"] >= rule["max_visits"])
        not_recommended = rule.get("recommendation") == "not_recommended"
        rules_verdict = ("no" if (exceeded and stalled) or not_recommended else "unclear",
                         ["documented objective functional improvement"] if stalled else [],
                         "Visits already exceed the guideline maximum and progress has plateaued." if exceeded and stalled
                         else f"Guideline rule {rule['rule_code']} does not recommend this treatment for the documented condition." if not_recommended
                         else "Criteria could not be fully established from the record.")
        verdict, missing, expl = _assess(ctx, rule, ua.request_description,
                                         "\n".join(f"- {f.effective_date} {f.label}" for f in facts[-40:]), rules_verdict)
        if verdict == "no":
            add("off_guideline_request", "high", f"Off-guideline request: {ua.request_description[:90]}", rule, expl,
                "Non-certification may be supported; consider alternatives consistent with the guideline (e.g. work hardening).",
                [], {"missing_prerequisites": missing}, key=f"req:{ua.id}")
        elif verdict == "yes":
            add("compliant", "low", f"Request consistent with guideline: {ua.request_description[:90]}", rule, expl, None, [], key=f"req:{ua.id}")
        else:
            add("off_guideline_request", "medium", f"Request needs clinical review: {ua.request_description[:90]}", rule, expl,
                "Obtain the missing documentation before determination.", [], {"missing_prerequisites": missing}, key=f"req:{ua.id}")
    # (c) opioid duration
    opioids = sorted([f for f in facts if f.fact_type == "medication" and f.value.get("is_opioid")], key=lambda f: f.effective_date or "")
    if opioids:
        rule = _rule(ctx, "opioid oxycodone acute post-operative pain duration", "medication")
        start, last = opioids[0].effective_date, opioids[-1].effective_date
        if rule and start and last:
            end = (date.fromisoformat(last) + timedelta(days=10)).isoformat()  # approximate days supply of the last fill
            calc = ctx.tools.call("duration_calculator_tool", start_date=start, end_date=end, max_duration_days=rule.get("max_duration_days"))
            if calc["exceeds"]:
                add("excessive_duration", "high", f"Opioid therapy ~{calc['actual_days']} days vs {rule['max_duration_days']}-day guideline", rule,
                    f"{len(opioids)} opioid fills from {fmt_date(start)} to {fmt_date(last)}.",
                    "Request a taper plan, functional goals, pain agreement and urine drug screening per the guideline.",
                    [opioids[0].id, opioids[-1].id], calc, key="opioid:duration")
    # (d) stalled recovery: pain scores flat across therapy, and TTD duration
    pains = sorted([f for f in facts if f.fact_type == "symptom" and f.value.get("severity_0_10") is not None
                    and (not surgery_date or (f.effective_date or "") > surgery_date)], key=lambda f: f.effective_date or "")
    if len(pains) >= 3:
        tail = pains[-3:]
        if max(p.value["severity_0_10"] for p in tail) - min(p.value["severity_0_10"] for p in tail) <= 1:
            rule = _rule(ctx, "physical therapy functional improvement continuation", "therapy", cpts, dx)
            add("stalled_recovery", "medium", f"Stalled recovery: pain {_n(tail[-1].value['severity_0_10'])}/10 unchanged across {len(tail)} assessments",
                rule, f"Pain scores {', '.join(str(_n(p.value['severity_0_10'])) for p in tail)} from {fmt_date(tail[0].effective_date)} to "
                      f"{fmt_date(tail[-1].effective_date)} - no measurable improvement.",
                "Re-evaluate the treatment plan; consider work hardening, psychosocial screening or IME.", [p.id for p in tail],
                key="stalled:pain")
    ttd = [r for r in ctx.db.execute(select(RtwStatus).where(RtwStatus.claim_id == ctx.claim_id).order_by(RtwStatus.effective_date)).scalars()]
    if ttd and doi:
        first_rtw = next((r.effective_date for r in ttd if r.work_status in ("modified_duty", "full_duty") and r.effective_date), None)
        end = first_rtw or date.today().isoformat()
        rule = _rule(ctx, "disability duration lumbar discectomy" if procs else "disability duration low back strain", "disability_duration")
        if rule:
            calc = ctx.tools.call("duration_calculator_tool", start_date=doi, end_date=end, max_duration_days=rule.get("max_duration_days"))
            if calc["exceeds"]:
                add("excessive_duration", "medium", f"Temporary total disability {calc['actual_days']} days vs expected {rule['max_duration_days']}",
                    rule, f"Off work from {fmt_date(doi)} until {'release to ' + fmt_date(first_rtw) if first_rtw else 'present'}.",
                    "Pursue modified-duty accommodation or vocational options; diary for re-evaluation.",
                    [r.source_fact_id for r in ttd if r.source_fact_id][:2], calc, key="ttd:duration")
    # (e) unusual escalation: early imaging / surgery
    for f in facts:
        if f.fact_type == "imaging" and "mri" in str(f.value.get("modality", "")).lower() and doi and f.effective_date:
            days = (date.fromisoformat(f.effective_date) - date.fromisoformat(doi)).days
            rule = _rule(ctx, "MRI lumbar spine imaging", "imaging", ["72148"])
            if rule and days < 42:
                deficit = _has_deficit(facts, f.effective_date)
                verdict = ("yes" if deficit else "no", [] if deficit else ["red flags or progressive neurological deficit"],
                           f"MRI {days} days after injury; " + ("neurological deficit documented." if deficit else "no red flags documented."))
                verdict = _assess(ctx, rule, f"Lumbar MRI {days} days after injury", _deficit_text(facts), verdict)
                add("compliant" if verdict[0] == "yes" else "unusual_escalation", "low" if verdict[0] == "yes" else "medium",
                    f"Early MRI ({days} days post-injury): " + {"yes": "criteria met", "no": "criteria not documented"}.get(verdict[0], "needs clinical review"),
                    rule, verdict[2], None if verdict[0] == "yes" else "Confirm red-flag findings justifying early imaging.", [f.id], key="mri:early")
                break
    if surgery_date and doi:
        days = (date.fromisoformat(surgery_date) - date.fromisoformat(doi)).days
        rule = _rule(ctx, "lumbar discectomy microdiscectomy surgery", "surgery", cpts, dx)
        if rule:
            deficit = _has_deficit(facts, surgery_date)
            rv = ("yes" if (deficit or days >= 42) else "no", [] if (deficit or days >= 42) else ["6 weeks of conservative care"],
                  f"Surgery {days} days after injury; " + ("progressive motor deficit with concordant imaging documented."
                                                         if deficit else "conservative-care period shorter than recommended."))
            verdict = _assess(ctx, rule, f"Lumbar microdiscectomy {days} days after injury", _deficit_text(facts), rv)
            add("compliant" if verdict[0] == "yes" else "unusual_escalation", {"yes": "low", "no": "high"}.get(verdict[0], "medium"),
                f"Surgery {days} days post-injury: " + {"yes": "guideline exception criteria met", "no": "rapid escalation"}.get(verdict[0], "needs clinical review"),
                rule, verdict[2], None if verdict[0] == "yes" else "Obtain documentation of failed conservative care or neurological deficit.",
                [p.id for p in procs], key="surgery:timing")
    return findings


def _n(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _has_deficit(facts, before: str) -> bool:
    txt = " ".join(f"{f.label} {f.value}" for f in facts if (f.effective_date or "") <= before)
    return bool(re.search(r"progressive (motor )?deficit|weakness|\b4[-+]?/5|motor deficit|diminished sensation", txt, re.I))


def _deficit_text(facts) -> str:
    return "\n".join(f"- {f.effective_date} {f.label}" for f in facts if f.fact_type in ("symptom", "exam_finding", "imaging", "diagnosis", "procedure"))[:6000]


def _documented_visits(ctx: AgentContext) -> dict | None:
    from app.repositories.docs import load_doc_views

    pts = [v for v in load_doc_views(ctx.db, ctx.claim_id)
           if v.doc_type in ("Physical Therapy Progress Note", "Rehab Note") and "THERAPY" in v.title.upper()]
    nums = []
    for v in pts:
        for ln in v.lines[:8]:
            m = re.search(r"Visit:\s*(\d+)", ln.text)
            if m:
                nums.append((int(m.group(1)), v.service_date))
    if not pts:
        return None
    dates = sorted(d for v in pts for d in [v.service_date] if d)
    return {"count": max([n for n, _ in nums], default=len(pts)), "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None}


@agent_node("guideline_agent", "guideline_review")
def guideline_agent(state: dict, ctx: AgentContext) -> dict:
    ctx.claim.current_stage = "guideline_review"
    build_case_fact_sheet(ctx)
    impacts = map_milestone_impacts(ctx)
    findings = analyse_deviations(ctx)
    flags = []
    for f in findings:
        rule = f["rule"]
        existing = ctx.db.execute(select(GuidelineFinding).where(GuidelineFinding.claim_id == ctx.claim_id,
                                                                 GuidelineFinding.item_key == f["key"])).scalar_one_or_none()
        if existing and existing.status != "open":
            continue  # keep reviewer decisions
        row = existing or GuidelineFinding(id=uuid7(), claim_id=ctx.claim_id, item_key=f["key"])
        row.run_id, row.finding_type, row.severity, row.title = ctx.run_id, f["finding_type"], f["severity"], f["title"][:255]
        row.treatment_ref, row.guideline_rule_id = f["treatment_ref"], rule["rule_id"] if rule else None
        row.rule_excerpt = f"[{rule['rule_code']}] {rule['criteria_text']}" if rule else None
        row.explanation, row.recommendation, row.metrics = f["explanation"], f["recommendation"], f["metrics"]
        if existing is None:
            ctx.db.add(row)
            save_citations(ctx.db, "finding", row.id, f["evidence"], rescore=False)
        if f["finding_type"] not in ("compliant", "no_applicable_guideline"):
            upsert_flag(ctx, f"guideline:{f['key']}", flag_type="guideline_deviation", severity=f["severity"], title=f["title"][:255],
                        detail=f["explanation"], ref_type="guideline_finding", ref_id=row.id, evidence=f["evidence"][:3],
                        ai_recommendation=f["recommendation"])
            flags.append({"key": f["key"], "type": f["finding_type"], "severity": f["severity"]})
    ctx.audit("guideline.review", "claim", ctx.claim_id, after={"findings": len(findings), "deviations": len(flags), "milestones": impacts})
    return {"guideline_flags": flags, "stage_status": {"guideline_review": "completed"}, "summary_id": state.get("summary_id")}

