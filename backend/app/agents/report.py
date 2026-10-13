"""Report Agent - Stage 6 Step 2 (POC-6, PW-6.2, POC-OUT) and HITL-3 NCM Summary Review (PW-6.3)."""
from __future__ import annotations

from sqlalchemy import select

from app.agents.clinical import persist_cited_document
from app.agents.common import fmt_date, run_llm
from app.agents.extraction.turning_points import validated_facts
from app.core.ids import uuid7
from app.models import (
    Citation,
    ClinicalIssue,
    DocumentRequest,
    GuidelineFinding,
    Milestone,
    ReviewContext,
    Summary,
    TimelineGap,
    UtilizationAssessment,
)
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import await_human
from app.orchestration.supervisor import route_after_summary
from app.repositories.docs import alias_map, citation_dict, classifications_for, resolve_cites
from app.schemas.llm import ReportNarrativeOut
from app.services.report_builder import build_report
from app.tools.output import render_pdf

REPORT_TYPES = ["narrative", "one_page", "mmi_status", "case_progress"]
PHYSICIAN_TYPES = {"ED Visit Record", "Orthopedic/Specialist Consultation", "Operative Report", "Post-Op Follow-Up Note",
                   "IME Report", "Primary Care Note", "Pain Management Note"}


def _cites(ctx: AgentContext, fact_ids: list[str]) -> list[dict]:
    return [citation_dict(c) for c in ctx.db.execute(select(Citation).where(Citation.owner_type == "fact",
                                                                            Citation.owner_id.in_(fact_ids))).scalars()]


def _S(ctx, text: str, fact_ids: list[str] | None = None, cites: list[dict] | None = None) -> dict:
    return {"text": text, "citations": (cites or []) + (_cites(ctx, fact_ids) if fact_ids else [])}


def _latest(facts, t):
    items = [f for f in facts if f.fact_type == t]
    return items[-1] if items else None


def _context(ctx: AgentContext) -> dict:
    facts = validated_facts(ctx)
    rc = ctx.db.execute(select(ReviewContext).where(ReviewContext.claim_id == ctx.claim_id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
    findings = ctx.db.execute(select(GuidelineFinding).where(GuidelineFinding.claim_id == ctx.claim_id,
                                                             GuidelineFinding.finding_type.notin_(["compliant", "no_applicable_guideline"]),
                                                             GuidelineFinding.status != "dismissed")).scalars().all()
    milestones = ctx.db.execute(select(Milestone).where(Milestone.claim_id == ctx.claim_id, Milestone.status != "superseded")
                                .order_by(Milestone.milestone_date)).scalars().all()
    gaps = ctx.db.execute(select(TimelineGap).where(TimelineGap.claim_id == ctx.claim_id, TimelineGap.status.in_(["open", "requested"]))).scalars().all()
    issues = ctx.db.execute(select(ClinicalIssue).where(ClinicalIssue.claim_id == ctx.claim_id, ClinicalIssue.status.in_(["open", "in_progress"]),
                                                        ClinicalIssue.severity.in_(["high", "medium"]))).scalars().all()
    reqs = ctx.db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == ctx.claim_id, DocumentRequest.status.in_(["open", "sent"]))).scalars().all()
    uas = ctx.db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == ctx.claim_id)
                         .order_by(UtilizationAssessment.created_at.desc())).scalars().all()
    cls = classifications_for(ctx.db, list({f.document_id for f in facts if f.document_id}))
    return {"doc_types": {k: v.doc_type for k, v in cls.items()}, "facts": facts, "rc": rc, "findings": findings, "milestones": milestones, "gaps": gaps, "issues": issues, "reqs": reqs, "uas": uas}


def next_actions(c: dict) -> list[str]:
    acts = []
    mmi = _latest(c["facts"], "mmi")
    if mmi and mmi.value.get("status") != "reached":
        acts.append(f"Diary MMI re-evaluation for {fmt_date(mmi.value.get('anticipated_date'))}; request impairment rating at MMI"
                    if mmi.value.get("anticipated_date") else "Request MMI opinion from the treating provider")
    for ua in c["uas"][:2]:
        acts.append(f"Route utilization request to UR reviewer for determination: {ua.request_description[:90]}")
    for f in c["findings"][:3]:
        if f.recommendation:
            acts.append(f.recommendation)
    for r in c["reqs"][:3]:
        acts.append(f"Obtain missing record: {r.description}")
    rtw = _latest(c["facts"], "rtw")
    if rtw and rtw.value.get("meets_job_demands") is False:
        acts.append(f"Pursue light-duty accommodation / vocational options consistent with FCE ({rtw.value.get('capacity')})")
    seen, out = set(), []
    for a in acts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:7]


def one_page_sections(ctx: AgentContext, c: dict, actions: list[str]) -> list[tuple[str, list[dict]]]:
    f = c["facts"]
    mech = _latest(f, "mechanism")
    dx = [x for x in f if x.fact_type == "diagnosis"]
    physician = [x for x in dx if c["doc_types"].get(x.document_id) in PHYSICIAN_TYPES]
    latest_dx = (physician or dx)[-1] if dx else None
    sym = _latest(f, "symptom")
    resp = _latest(f, "response")
    ws = _latest(f, "work_status")
    rtw = next((x for x in reversed(f) if x.fact_type == "rtw" and x.value.get("capacity")), None)
    mmi = _latest(f, "mmi")
    rc = c["rc"]
    sections = [("Review question", [_S(ctx, rc.clinical_question)] if rc else [])]
    inj = []
    if mech:
        inj.append(_S(ctx, f"{fmt_date(ctx.claim.date_of_injury)}: {mech.value.get('description', mech.label)[:220]}", [mech.id]))
    if latest_dx:
        inj.append(_S(ctx, f"Current diagnosis: {latest_dx.value.get('description')} ({latest_dx.value.get('icd10')})", [latest_dx.id]))
    sections.append(("Injury and diagnosis", inj))
    sections.append(("Treatment to date (key milestones)", [
        _S(ctx, f"{fmt_date(m.milestone_date)} - {m.description[:160]}", m.fact_ids[:2]) for m in c["milestones"][:6]]))
    status = []
    if sym:
        status.append(_S(ctx, f"{fmt_date(sym.effective_date)}: {sym.value.get('description', sym.label)[:200]}", [sym.id]))
    if resp:
        status.append(_S(ctx, f"{fmt_date(resp.effective_date)}: {resp.value.get('description', resp.label)[:200]}", [resp.id]))
    sections.append(("Current clinical status", status))
    work = []
    if ws:
        work.append(_S(ctx, f"{fmt_date(ws.effective_date)}: {ws.value.get('description', ws.label)[:220]}", [ws.id]))
    if rtw:
        work.append(_S(ctx, f"FCE {fmt_date(rtw.effective_date)}: {rtw.value.get('capacity')} capacity"
                            + ("; does not meet job demands" if rtw.value.get("meets_job_demands") is False else ""), [rtw.id]))
    sections.append(("Work status and restrictions (RTW)", work))
    sections.append(("MMI status", [_S(ctx, mmi.label + (f" (by {mmi.value.get('declaring_provider')})" if mmi.value.get("declaring_provider") else ""), [mmi.id])]
                     if mmi else [_S(ctx, "No MMI opinion documented.")]))
    flag_rows = []
    for g in c["findings"][:5]:
        cites = [citation_dict(x) for x in ctx.db.execute(select(Citation).where(Citation.owner_type == "finding", Citation.owner_id == g.id)).scalars()][:2]
        flag_rows.append(_S(ctx, f"[{g.severity.upper()}] {g.title}", cites=cites))
    sections.append(("Guideline flags", flag_rows or [_S(ctx, "No guideline deviations identified.")]))
    open_items = [_S(ctx, f"Missing record: {r.description}") for r in c["reqs"][:4]]
    open_items += [_S(ctx, f"[{i.severity}] {i.description[:160]}") for i in c["issues"][:3] if i.issue_type != "missing_evidence"]
    sections.append(("Open issues / missing records", open_items or [_S(ctx, "None.")]))
    sections.append(("Recommended next actions", [_S(ctx, a) for a in actions]))
    return sections


def _word_count(sections) -> int:
    return sum(len(s["text"].split()) for _, ss in sections for s in ss)


def _fit_one_page(ctx: AgentContext, sections: list) -> list:
    """Enforce the one-page limit (<= ONE_PAGE_WORD_LIMIT words and 1 rendered page)."""
    limit = ctx.settings.ONE_PAGE_WORD_LIMIT
    for _ in range(12):
        doc = {"title": "One-Page Actionable Summary", "header": [("Claim", "x")] * 8,
               "sections": [{"heading": h, "bullets": [s["text"] + " [1]" for s in ss]} for h, ss in sections]}
        _, pages = render_pdf(doc)
        if _word_count(sections) <= limit and pages <= 1:
            return sections
        longest = max(range(len(sections)), key=lambda i: len(sections[i][1]) if sections[i][0] != "Review question" else 0)
        if len(sections[longest][1]) <= 1:
            break
        sections[longest] = (sections[longest][0], sections[longest][1][:-1])
    return sections


def narrative_sections(ctx: AgentContext, c: dict, instructions: str | None) -> tuple[list, list[str] | None, str]:
    facts = c["facts"]
    if ctx.llm.enabled and facts:
        amap = alias_map(ctx.db, ctx.claim_id)
        rev = {a: i for i, a in amap.items()}
        cites = {}
        for ci in ctx.db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id.in_([f.id for f in facts]))).scalars():
            cites.setdefault(ci.owner_id, ci)
        lines = [f"<<{amap.get(cites[f.id].document_id)}|P{cites[f.id].page_number}|L{cites[f.id].line_start}>> {f.effective_date} {f.fact_type}: {f.label}"
                 for f in facts if f.id in cites]
        res, src = run_llm(ctx, "report_narrative", ReportNarrativeOut, question=c["rc"].clinical_question if c["rc"] else "",
                           instructions=instructions, facts="\n".join(lines)[:60000],
                           findings="\n".join(f"- {g.title}: {g.explanation}" for g in c["findings"]))
        if res is not None:
            secs = [(s.heading, [{"text": x.text, "citations": resolve_cites(x.citations, rev)} for x in s.sentences]) for s in res.narrative]
            return secs, res.recommended_next_actions, src
    order = [("Injury", {"mechanism"}), ("Diagnosis", {"diagnosis", "imaging"}), ("Treatment", {"procedure", "treatment_plan"}),
             ("Response", {"response", "symptom"}), ("Function", {"rtw", "restriction"}), ("Current status", {"work_status", "mmi"})]
    secs = []
    for heading, types in order:
        items = [f for f in facts if f.fact_type in types]
        if heading in ("Response", "Treatment"):
            items = items[:2] + items[-3:] if len(items) > 5 else items
        if heading == "Current status":
            items = items[-3:]
        secs.append((heading, [_S(ctx, f"{fmt_date(f.effective_date)}: {f.label}.", [f.id]) for f in items]))
    note = f"Reviewer instructions recorded: {instructions}" if instructions else None
    if note:
        secs.append(("Revision note", [_S(ctx, note + " (rule-based mode: please apply edits inline)")]))
    return secs, None, "rules"


def mmi_sections(ctx: AgentContext, c: dict) -> list:
    f = c["facts"]
    mmis = [x for x in f if x.fact_type == "mmi"]
    ir = [x for x in f if x.fact_type == "impairment_rating"]
    rtw = [x for x in f if x.fact_type == "rtw"]
    plans = [x for x in f if x.fact_type == "treatment_plan" and x.value.get("status") in ("requested", "approved")][-4:]
    secs = [("MMI determination", [_S(ctx, f"{fmt_date(m.effective_date)}: {m.label}" + (f" - {m.value.get('declaring_provider')}" if m.value.get("declaring_provider") else ""), [m.id]) for m in mmis]
             or [_S(ctx, "No MMI opinion documented in the records reviewed.")]),
            ("Impairment rating", [_S(ctx, x.label, [x.id]) for x in ir] or [_S(ctx, "Not yet rated (deferred until MMI).")]),
            ("Functional status / work capacity", [_S(ctx, f"{fmt_date(x.effective_date)}: {x.label}", [x.id]) for x in rtw]),
            ("Remaining treatment before MMI", [_S(ctx, f"{fmt_date(x.effective_date)}: {x.label}", [x.id]) for x in plans]),
            ("Open questions", [_S(ctx, i.description[:200]) for i in c["issues"] if i.issue_type in ("conflicting_diagnosis", "missing_evidence")][:4]
             or [_S(ctx, "None.")])]
    return secs


def progress_sections(ctx: AgentContext, c: dict, actions: list[str]) -> list:
    f = c["facts"]
    ws = [x for x in f if x.fact_type == "work_status"]
    return [("Milestones", [_S(ctx, f"{fmt_date(m.milestone_date)} - {m.description[:150]}" + (f" -> {m.impact_narrative[:150]}" if m.impact_narrative else ""), m.fact_ids[:2]) for m in c["milestones"]]),
            ("Work-status trajectory", [_S(ctx, f"{fmt_date(x.effective_date)}: {x.label}", [x.id]) for x in ws]),
            ("Utilization requests (AI drafts)", [_S(ctx, f"{u.request_description[:120]} - {u.ai_recommendation[:160]}") for u in c["uas"][:3]] or [_S(ctx, "None.")]),
            ("Guideline findings", [_S(ctx, f"[{g.severity}] {g.title}") for g in c["findings"]] or [_S(ctx, "None.")]),
            ("Open items", [_S(ctx, g.description[:160]) for g in c["gaps"]] or [_S(ctx, "None.")]),
            ("Next steps", [_S(ctx, a) for a in actions])]


def _save(ctx: AgentContext, stype: str, sections: list, extra: dict | None = None) -> str:
    sid = uuid7()
    md, js = persist_cited_document(ctx, "summary", sid, sections)
    js.update(extra or {})
    prev = ctx.db.execute(select(Summary).where(Summary.claim_id == ctx.claim_id, Summary.summary_type == stype,
                                                Summary.status.in_(["draft", "in_review"]))).scalars().all()
    for p in prev:
        p.status = "superseded"
    n = ctx.db.execute(select(Summary).where(Summary.claim_id == ctx.claim_id, Summary.summary_type == stype)).scalars().all()
    ctx.db.add(Summary(id=sid, claim_id=ctx.claim_id, summary_type=stype, content_md=md, content_json=js, status="in_review",
                       generated_by_run_id=ctx.run_id, version=len(n) + 1, word_count=_word_count(sections),
                       supersedes_id=prev[-1].id if prev else None))
    return sid


@agent_node("report_agent", "output")
def report_agent(state: dict, ctx: AgentContext) -> dict:
    instructions = None
    for fb in reversed(state.get("human_feedback") or []):
        if fb.get("checkpoint") == "HITL-3":
            instructions = (fb.get("response") or {}).get("regenerate_instructions")
            break
    c = _context(ctx)
    narrative, llm_actions, src = narrative_sections(ctx, c, instructions)
    actions = llm_actions or next_actions(c)
    ids = {"narrative": _save(ctx, "narrative", narrative, {"source": src, "instructions": instructions})}
    one_page = _fit_one_page(ctx, one_page_sections(ctx, c, actions))
    ids["one_page"] = _save(ctx, "one_page", one_page, {"source": src})
    ids["mmi_status"] = _save(ctx, "mmi_status", mmi_sections(ctx, c))
    ids["case_progress"] = _save(ctx, "case_progress", progress_sections(ctx, c, actions))
    ctx.db.flush()
    _, pages = render_pdf(build_report(ctx.db, ctx.claim, "one_page_summary"))
    ctx.audit("report.generate", "claim", ctx.claim_id, after={**ids, "one_page_pages": pages, "source": src,
                                                              "words": _word_count(one_page)})
    return {"summary_id": ids["one_page"], "report_ids": list(ids.values())}


@agent_node("hitl_summary_review", "output")
def hitl_summary_review(state: dict, ctx: AgentContext) -> dict:
    """HITL-3: NCM reviews and contextualizes the summary against the review question."""
    iteration = (state.get("retry_counts") or {}).get("summary_loop", 0)

    def payload():
        rows = {}
        for t in REPORT_TYPES + ["clinical", "case_facts"]:
            s = ctx.db.execute(select(Summary).where(Summary.claim_id == ctx.claim_id, Summary.summary_type == t,
                                                     Summary.status.in_(["draft", "in_review"])).order_by(Summary.created_at.desc()).limit(1)).scalar_one_or_none()
            if s:
                rows[t] = {"id": s.id, "version": s.version, "word_count": s.word_count}
        rc = ctx.db.execute(select(ReviewContext).where(ReviewContext.claim_id == ctx.claim_id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
        return {"summaries": rows, "review_question": rc.clinical_question if rc else None,
                "instructions": "Approve, edit inline (creates a new version) or request regeneration with instructions."}

    review, response = await_human(ctx, "HITL-3", iteration, "Review one-page summary, narrative and MMI status report", payload)
    route = route_after_summary(ctx, response, iteration)
    return {"human_feedback": [{"checkpoint": "HITL-3", "review_id": review.id, "response": response}], "last_route": route,
            "retry_counts": {"summary_loop": iteration + 1},
            "stage_status": {"output": "completed"} if route == "continue" else {}}
