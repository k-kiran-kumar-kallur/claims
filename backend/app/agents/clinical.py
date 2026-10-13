"""Stage 3: Clinical Summary Agent (POC-3, PW-3.1) and Utilization / Clinical Assessment Agent (PW-3.2, PW-3.3)."""
from __future__ import annotations

import itertools
import re
from datetime import date

from sqlalchemy import func, select

from app.agents import heuristics as H
from app.agents.common import fmt_date, run_llm
from app.agents.intake import find_requests
from app.agents.taxonomy import NON_CLINICAL_TYPES
from app.core.ids import uuid7
from app.models import ClinicalIssue, DocumentIndex, Episode, ReviewContext, Summary, TimelineGap, UtilizationAssessment
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.repositories.docs import alias_map, load_doc_views, resolve_cites, save_citations
from app.schemas.llm import ClinicalSummaryOut, EpisodeSummaryOut, UtilizationOut

SECTIONS = [("executive_summary", "Executive health summary"), ("injury_and_mechanism", "Injury and mechanism"),
            ("diagnoses", "Diagnoses"), ("key_tests", "Key tests and results"),
            ("treatments_and_response", "Treatments and response"), ("recovery_trajectory", "Recovery trajectory"),
            ("daily_functioning", "Daily functioning"), ("work_status_and_restrictions", "Work status and restrictions")]


def S(text: str, cites: list[dict], evidence: str = "objective") -> dict:
    return {"text": text, "citations": [c for c in cites if c], "evidence_type": evidence}


def persist_cited_document(ctx: AgentContext, owner_type: str, owner_id: str, sections: list[tuple[str, list[dict]]]) -> tuple[str, dict]:
    """Persist citations for cited sentences; returns (markdown with [[cite:id]] tokens, json content)."""
    md, js = [], {"sections": []}
    for heading, sentences in sections:
        md.append(f"### {heading}")
        out_sentences = []
        for s in sentences:
            rows = save_citations(ctx.db, owner_type, owner_id, s.get("citations", []))
            tokens = "".join(f" [[cite:{r.id}]]" for r in rows)
            md.append(f"- {s['text']}{tokens}")
            out_sentences.append({"text": s["text"], "citation_ids": [r.id for r in rows],
                                  "evidence_type": s.get("evidence_type", "mixed")})
        js["sections"].append({"heading": heading, "sentences": out_sentences})
        md.append("")
    return "\n".join(md).strip(), js


def clinical_views(ctx: AgentContext) -> list[H.DocView]:
    return [v for v in load_doc_views(ctx.db, ctx.claim_id) if v.doc_type not in NON_CLINICAL_TYPES]


# =============================================================================================
# Clinical Summary Agent - rules implementation
# =============================================================================================

def rules_clinical_summary(ctx: AgentContext, views: list[H.DocView]) -> dict[str, list[dict]]:
    claim = ctx.claim
    out: dict[str, list[dict]] = {k: [] for k, _ in SECTIONS}
    out["key_narrative_changes"] = []
    clinical = [v for v in views if v.doc_type not in ("Pharmacy/Prescription Record",)]
    # injury and mechanism
    for v in clinical:
        lv = H.first_labeled(v, ["Mechanism of Injury", "Description of Accident", "History of Injury"])
        if lv:
            out["injury_and_mechanism"].append(S(f"Injury on {fmt_date(claim.date_of_injury)}: {lv.value}", [H.citation_for(v, lv)], "subjective"))
            break
    for v in clinical:
        lv = H.first_labeled(v, ["Chief Complaint"])
        if lv:
            out["injury_and_mechanism"].append(S(f"Presenting complaint: {lv.value}", [H.citation_for(v, lv)], "subjective"))
            break
    # diagnoses (distinct, chronological)
    seen_codes: set[str] = set()
    dx_events = []
    for v in clinical:
        for lv in H.labeled_values(v, ["Diagnosis", "Assessment", "Postoperative Diagnosis", "Preoperative Diagnosis"]):
            codes = tuple(H.icd_codes(lv.value))
            if codes and not set(codes) <= seen_codes:
                seen_codes |= set(codes)
                dx_events.append((v, lv, codes))
                out["diagnoses"].append(S(f"{fmt_date(v.service_date)} ({v.provider or v.facility or v.doc_type}): {lv.value}",
                                          [H.citation_for(v, lv)]))
    # key tests
    for v in clinical:
        for lv in H.labeled_values(v, ["Diagnostic Testing", "Imaging", "Imaging/Diagnostics", "Intraoperative Findings"]):
            if re.search(r"x-ray|mri|ct|emg|finding|fce|functional capacity", lv.value, re.I):
                out["key_tests"].append(S(f"{fmt_date(v.service_date)}: {lv.value}", [H.citation_for(v, lv)]))
        if v.doc_type == "FCE Report":
            lv = H.first_labeled(v, ["Work Capacity Classification"])
            if lv:
                out["key_tests"].append(S(f"FCE {fmt_date(v.service_date)}: work capacity {lv.value}", [H.citation_for(v, lv)]))
    # treatments and response
    for v in clinical:
        for lv in H.labeled_values(v, ["Procedure Performed", "Treatment Provided"]):
            out["treatments_and_response"].append(S(f"{fmt_date(v.service_date)}: {lv.value}", [H.citation_for(v, lv)]))
        if v.doc_type in ("Post-Op Follow-Up Note", "Orthopedic/Specialist Consultation"):
            lv = H.first_labeled(v, ["Assessment"])
            if lv and v.doc_type == "Post-Op Follow-Up Note":
                out["treatments_and_response"].append(S(f"{fmt_date(v.service_date)} response: {lv.value}", [H.citation_for(v, lv)]))
    pt = [v for v in clinical if v.doc_type == "Physical Therapy Progress Note"]
    if pt:
        visits = [m for v in pt for ln in v.lines[:6] for m in [re.search(r"Visit:\s*(\d+)", ln.text)] if m]
        last = pt[-1]
        resp = H.first_labeled(last, ["Response", "Assessment"])
        out["treatments_and_response"].append(S(
            f"Physical therapy {fmt_date(pt[0].service_date)} - {fmt_date(last.service_date)}"
            + (f", {max(int(m.group(1)) for m in visits)} visits documented" if visits else "")
            + (f"; latest response: {resp.value}" if resp else ""),
            [H.citation_for(pt[0], pt[0].lines[4] if len(pt[0].lines) > 4 else pt[0].lines[0])] + ([H.citation_for(last, resp)] if resp else [])))
    # recovery trajectory: pain scores over time
    series = []
    for v in clinical:
        for ln, score in H.pain_scores(v):
            series.append((v.service_date or "", score, v, ln))
    series.sort(key=lambda x: x[0])
    if len(series) >= 2:
        peak = max(series, key=lambda x: x[1])
        last = series[-1]
        tail = series[-4:]
        plateau = len(tail) >= 3 and max(s[1] for s in tail) - min(s[1] for s in tail) <= 1
        txt = (f"Reported pain peaked at {peak[1]}/10 ({fmt_date(peak[0])}) and was {last[1]}/10 at the latest visit "
               f"({fmt_date(last[0])})" + (f"; pain has plateaued at {last[1]}/10 since {fmt_date(tail[0][0])}." if plateau else "."))
        out["recovery_trajectory"].append(S(txt, [H.citation_for(peak[2], peak[3]), H.citation_for(last[2], last[3])], "subjective"))
        if plateau:
            out["key_narrative_changes"].append({"date": tail[0][0], "direction": "plateaued",
                                                 "description": f"Pain plateau at {last[1]}/10 across the last {len(tail)} assessments",
                                                 "citations": [H.citation_for(tail[0][2], tail[0][3]), H.citation_for(last[2], last[3])]})
    # daily functioning: ODI and tolerances
    odi = []
    for v in clinical:
        for ln in v.lines:
            m = re.search(r"Oswestry Disability Index (\d+) percent", ln.text)
            if m:
                odi.append((v.service_date or "", int(m.group(1)), v, ln))
    if len(odi) >= 2:
        odi.sort(key=lambda x: x[0])
        out["daily_functioning"].append(S(f"Oswestry Disability Index {odi[0][1]}% ({fmt_date(odi[0][0])}) to {odi[-1][1]}% "
                                          f"({fmt_date(odi[-1][0])}).", [H.citation_for(odi[0][2], odi[0][3]), H.citation_for(odi[-1][2], odi[-1][3])], "mixed"))
    for v in reversed(clinical):
        ln = H.find_line(v, r"difficulty (sitting|with prolonged sitting)|sitting tolerance")
        if ln:
            out["daily_functioning"].append(S(f"{fmt_date(v.service_date)}: {ln.text.strip()}", [H.citation_for(v, ln)],
                                              "objective" if "tolerance" in ln.text.lower() else "subjective"))
            break
    # work status and restrictions (latest)
    ws = [(v.service_date or "", v, lv) for v in clinical for lv in H.labeled_values(v, ["Work Status"])]
    ws.sort(key=lambda x: x[0])
    if ws:
        d, v, lv = ws[-1]
        out["work_status_and_restrictions"].append(S(f"Current work status ({fmt_date(d)}, {v.provider or v.doc_type}): {lv.value}", [H.citation_for(v, lv)]))
        first = ws[0]
        if H.work_status_of(first[2].value) != H.work_status_of(lv.value):
            out["key_narrative_changes"].append({"date": d, "direction": "improved",
                                                 "description": f"Work status changed from {H.work_status_of(first[2].value)} to {H.work_status_of(lv.value)}",
                                                 "citations": [H.citation_for(first[1], first[2]), H.citation_for(v, lv)]})
    for v in clinical:
        if v.doc_type == "FCE Report":
            lv = H.first_labeled(v, ["Functional Limitations/Restrictions", "Can the patient meet job demands"])
            if lv:
                out["work_status_and_restrictions"].append(S(f"FCE {fmt_date(v.service_date)}: {lv.value}", [H.citation_for(v, lv)]))
    for (_v1, _lv1, c1), (v2, lv2, c2) in itertools.pairwise(dx_events):
        out["key_narrative_changes"].append({"date": v2.service_date, "direction": "new_finding" if "updated" not in lv2.value.lower() else "worsened",
                                             "description": f"Diagnosis changed from {', '.join(c1)} to {', '.join(c2)}",
                                             "citations": [H.citation_for(v2, lv2)]})
    # executive summary (<= 250 words)
    exec_s: list[dict] = []
    for key in ("injury_and_mechanism", "diagnoses", "treatments_and_response", "recovery_trajectory", "work_status_and_restrictions"):
        items = out[key]
        if items:
            pick = items[0] if key == "injury_and_mechanism" else items[-1]
            exec_s.append(pick)
    mmi = next(((v, lv) for v in reversed(clinical) for lv in [H.first_labeled(v, ["MMI"])] if lv), None)
    if mmi:
        exec_s.append(S(f"MMI: {mmi[1].value}", [H.citation_for(mmi[0], mmi[1])]))
    words = 0
    out["executive_summary"] = []
    for s in exec_s:
        words += len(s["text"].split())
        if words > 250:
            break
        out["executive_summary"].append(s)
    return out


def _llm_clinical_summary(ctx: AgentContext, views: list[H.DocView]) -> dict | None:
    amap_rev = {v.alias: v.id for v in views}
    version = ctx.db.execute(select(func.max(Episode.timeline_version)).where(Episode.claim_id == ctx.claim_id)).scalar()
    episodes = ctx.db.execute(select(Episode).where(Episode.claim_id == ctx.claim_id, Episode.timeline_version == version)
                              .order_by(Episode.sort_order)).scalars().all()
    idx = ctx.db.execute(select(DocumentIndex).where(DocumentIndex.claim_id == ctx.claim_id,
                                                     DocumentIndex.timeline_version == version)).scalars().all()
    by_ep: dict[str, list[str]] = {}
    for i in idx:
        by_ep.setdefault(i.episode_id, []).append(i.document_id)
    vmap = {v.id: v for v in views}
    episode_summaries = []
    for ep in episodes:  # map
        ep_views = [vmap[d] for d in by_ep.get(ep.id, []) if d in vmap]
        if not ep_views:
            continue
        res, src = run_llm(ctx, "episode_summary", EpisodeSummaryOut, episode=ep.label,
                           documents="\n\n".join(v.marked(30000) for v in ep_views))
        if res is None:
            return None
        lines = []
        for s in res.summary:
            marks = " ".join(f"<<{c.doc}|P{c.page}|L{c.line_start}>>" for c in s.citations)
            lines.append(f"- {s.text} {marks} ({s.evidence_type})")
        episode_summaries.append(f"Episode: {ep.label}\n" + "\n".join(lines))
    rc = ctx.db.execute(select(ReviewContext).where(ReviewContext.claim_id == ctx.claim_id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
    res, src = run_llm(ctx, "clinical_summary", ClinicalSummaryOut,  # reduce
                       claim=f"DOI {ctx.claim.date_of_injury}, body parts {ctx.claim.body_parts}",
                       question=rc.clinical_question if rc else "", episodes="\n\n".join(episode_summaries))
    if res is None:
        return None
    out: dict[str, list[dict]] = {}
    for key, _ in SECTIONS:
        out[key] = [S(s.text, resolve_cites(s.citations, amap_rev), s.evidence_type) for s in getattr(res, key)]
    out["key_narrative_changes"] = [{"date": H.normalize_date(c.date) if c.date else None, "direction": c.direction,
                                     "description": c.description, "citations": resolve_cites(c.citations, amap_rev)}
                                    for c in res.key_narrative_changes]
    return out


@agent_node("clinical_summary_agent", "clinical_review")
def clinical_summary_agent(state: dict, ctx: AgentContext) -> dict:
    views = clinical_views(ctx)
    content = _llm_clinical_summary(ctx, views) if ctx.llm.enabled else None
    source = "llm" if content else "rules"
    if content is None:
        content = rules_clinical_summary(ctx, views)
    # quality gate: functional and work limitations must be explicit
    if not content.get("work_status_and_restrictions"):
        content["work_status_and_restrictions"] = [S("No work status or restrictions are documented in the records reviewed.", [], "administrative")]
    summary_id = uuid7()
    changes = [S(f"{fmt_date(c.get('date'))} - {c['direction'].replace('_', ' ')}: {c['description']}", c.get("citations", []))
               for c in content.get("key_narrative_changes", [])]
    sections = [(title, content.get(key, [])) for key, title in SECTIONS] + [("Key narrative changes", changes)]
    md, js = persist_cited_document(ctx, "summary", summary_id, sections)
    js["source"] = source
    js["subjective_only"] = [s["text"] for _, ss in sections for s in ss if s.get("evidence_type") == "subjective"]
    prev = ctx.db.execute(select(Summary).where(Summary.claim_id == ctx.claim_id, Summary.summary_type == "clinical",
                                                Summary.status != "superseded")).scalars().all()
    for p in prev:
        p.status = "superseded"
    row = Summary(id=summary_id, claim_id=ctx.claim_id, summary_type="clinical", content_md=md, content_json=js,
                  status="draft", generated_by_run_id=ctx.run_id, version=len(prev) + 1,
                  word_count=sum(len(s["text"].split()) for s in content.get("executive_summary", [])))
    ctx.db.add(row)
    ctx.audit("summary.generate", "summary", summary_id, after={"type": "clinical", "source": source})
    ctx.claim.current_stage = "clinical_review"
    return {"summary_id": summary_id}


# =============================================================================================
# Utilization / Clinical Assessment Agent
# =============================================================================================

def rules_utilization(ctx: AgentContext, views: list[H.DocView], requests: list[dict], rules_by_req: dict) -> tuple[list[dict], list[dict]]:
    pt = [v for v in views if v.doc_type in ("Physical Therapy Progress Note", "Rehab Note") and "THERAPY" in v.title.upper()]
    fce = next((v for v in views if v.doc_type == "FCE Report"), None)
    assessments = []
    barriers, barrier_cites = [], []
    for v in views:
        ln = H.find_line(v, r"\bsmoker\b|tobacco use")
        if ln:
            barriers.append("Tobacco use (comorbidity that can delay spinal recovery)")
            barrier_cites.append(H.citation_for(v, ln))
            break
    for v in views:
        ln = H.find_line(v, r"no modified duty available|unable to accommodate")
        if ln:
            barriers.append("Employer unable to accommodate modified duty")
            barrier_cites.append(H.citation_for(v, ln))
            break
    opioid_lines = [(v, row) for v in views if v.doc_type == "Pharmacy/Prescription Record" for row in H.table_rows(v)
                    if any(o in row.value.lower() for o in H.OPIOIDS) and "Filled" in row.value]
    if len(opioid_lines) >= 4:
        barriers.append(f"Prolonged opioid therapy ({len(opioid_lines)} fills)")
    gaps = ctx.db.execute(select(TimelineGap).where(TimelineGap.claim_id == ctx.claim_id, TimelineGap.status == "open",
                                                    TimelineGap.gap_type == "missing_referenced_record")).scalars().all()
    for req in requests:
        rules = rules_by_req.get(req["description"], [])
        indicators = []
        visits = sorted({int(m.group(1)) for v in pt for ln in v.lines[:6] for m in [re.search(r"Visit:\s*(\d+)", ln.text)] if m})
        max_rule = next((r for r in rules if r.get("max_visits")), None)
        if req["type"] == "pt_extension" and visits:
            last = pt[-1]
            visit_line = H.find_line(last, r"Visit:") or last.lines[0]
            indicators.append({"indicator": f"{visits[-1]} PT visits completed" + (f" vs guideline maximum of {max_rule['max_visits']}" if max_rule else ""),
                               "supports_necessity": not (max_rule and visits[-1] >= max_rule["max_visits"]),
                               "citations": [H.citation_for(last, visit_line)], "guideline_rule_code": max_rule["rule_code"] if max_rule else None})
        scores = [(v.service_date or "", s, v, ln) for v in pt for ln, s in H.pain_scores(v)]
        scores.sort(key=lambda x: x[0])
        if len(scores) >= 3:
            flat = max(s[1] for s in scores[-3:]) - min(s[1] for s in scores[-3:]) <= 1
            indicators.append({"indicator": f"Pain {scores[0][1]}/10 -> {scores[-1][1]}/10 over therapy; "
                                            + ("no meaningful change over the last 3 assessments" if flat else "improving"),
                               "supports_necessity": not flat,
                               "citations": [H.citation_for(scores[-3][2], scores[-3][3]), H.citation_for(scores[-1][2], scores[-1][3])],
                               "guideline_rule_code": max_rule["rule_code"] if max_rule else None})
        if fce:
            lv = H.first_labeled(fce, ["Can the patient meet job demands", "Work Capacity Classification"])
            wh = next((r for r in rules if "work hardening" in r["title"].lower()), None)
            if lv:
                indicators.append({"indicator": f"FCE: {lv.value}", "supports_necessity": True,
                                   "citations": [H.citation_for(fce, lv)], "guideline_rule_code": wh["rule_code"] if wh else None})
        plateau = any(not i["supports_necessity"] for i in indicators)
        assessments.append({
            "request_description": req["description"], "request_type": req["type"], "requesting_provider": req.get("provider"),
            "request_date": req.get("date"), "necessity_indicators": indicators,
            "appropriateness": ("Additional therapy beyond the guideline visit count is generally not appropriate when "
                                "functional progress has plateaued; the FCE recommends a work hardening program to close the "
                                "gap to the job's physical demand level.") if plateau else
                               "Request appears consistent with documented progress; confirm against the cited guideline criteria.",
            "progression": "Improvement after surgery followed by a functional plateau in therapy." if plateau else "Progressing.",
            "barriers": barriers,
            "unresolved_questions": [f"{g.description}" for g in gaps] + (["Has a work hardening program been requested or authorized?"] if fce else []),
            "guideline_rule_ids": [r["rule_id"] for r in rules],
            "ai_recommendation": ("AI DRAFT - not a determination: criteria for additional PT do not appear to be met "
                                  "(visit count exceeds guideline and no measurable functional gain). Consider work "
                                  "hardening per FCE. UR reviewer to determine.") if plateau else
                                 "AI DRAFT - not a determination: request may be consistent with guidelines; UR reviewer to determine.",
        })
    issues = []
    for g in gaps:
        issues.append({"issue_type": "missing_evidence", "description": g.description, "severity": "high",
                       "suggested_action": f"Request: {g.description.split(' is referenced')[0]}", "citations": g.evidence or []})
    codes = []
    for v in views:
        if v.doc_type in ("Medical Bill", "Pharmacy/Prescription Record"):
            continue
        for lv in H.labeled_values(v, ["Diagnosis", "Assessment"]):
            for c in H.icd_codes(lv.value):
                codes.append((v.service_date or "", c, v, lv))
    distinct = []
    for item in sorted(codes, key=lambda x: x[0]):
        if item[1] not in [d[1] for d in distinct]:
            distinct.append(item)
    if len(distinct) >= 3:
        issues.append({"issue_type": "conflicting_diagnosis", "severity": "low",
                       "description": "Diagnoses differ across providers over time: " + "; ".join(f"{d[1]} ({fmt_date(d[0])})" for d in distinct),
                       "suggested_action": "Confirm the current accepted diagnosis and that all providers document it consistently",
                       "citations": [H.citation_for(d[2], d[3]) for d in distinct[:3]]})
    visit_dates = {v.service_date for v in views if v.doc_type in ("Post-Op Follow-Up Note", "Orthopedic/Specialist Consultation", "ED Visit Record")}
    for v, ln in opioid_lines:
        m = re.search(r"Rx Date (\d{1,2}/\d{1,2}/\d{4})", ln.value)
        d = H.normalize_date(m.group(1)) if m else None
        if d and not any(vd and abs((date.fromisoformat(vd) - date.fromisoformat(d)).days) <= 7 for vd in visit_dates):
            issues.append({"issue_type": "unexplained_change", "severity": "medium",
                           "description": f"Opioid prescription dated {fmt_date(d)} has no corresponding office visit in the record",
                           "suggested_action": f"Request the prescriber's note supporting the {fmt_date(d)} prescription",
                           "citations": [H.citation_for(v, ln)]})
    if pt:
        rom = [(v.service_date or "", int(m.group(1)), v, ln) for v in pt for ln in v.lines
               for m in [re.search(r"flexion (\d+) percent", ln.text)] if m]
        scores = [(v.service_date or "", s) for v in pt for _ln, s in H.pain_scores(v)]
        if len(rom) >= 3 and scores and rom[-1][1] - rom[0][1] >= 15 and max(s for _, s in scores[-3:]) - min(s for _, s in scores[-3:]) <= 1:
            issues.append({"issue_type": "inconsistency", "severity": "low",
                           "description": f"Lumbar flexion improved from {rom[0][1]}% to {rom[-1][1]}% while reported pain stayed flat",
                           "suggested_action": "Correlate subjective pain reports with objective function (FCE consistency measures)",
                           "citations": [H.citation_for(rom[0][2], rom[0][3]), H.citation_for(rom[-1][2], rom[-1][3])]})
    for b, c in zip(barriers, barrier_cites, strict=False):
        issues.append({"issue_type": "barrier", "severity": "medium", "description": b,
                       "suggested_action": "Address in the care plan / RTW planning", "citations": [c]})
    return assessments, issues


@agent_node("utilization_agent", "clinical_review")
def utilization_agent(state: dict, ctx: AgentContext) -> dict:
    views = load_doc_views(ctx.db, ctx.claim_id)
    requests = find_requests(views)
    claim = ctx.claim
    rules_by_req = {}
    for r in requests:
        rules_by_req[r["description"]] = ctx.tools.call(
            "guideline_retrieval_tool", db=ctx.db, query=f"{r['description']} {r['type']} {' '.join(claim.body_parts or [])}",
            jurisdiction=claim.jurisdiction_state, body_part=" ".join(claim.body_parts or []))
    amap_rev = {a: i for i, a in alias_map(ctx.db, ctx.claim_id).items()}
    res, source = (None, "rules")
    if ctx.llm.enabled:
        summary = ctx.db.get(Summary, state.get("summary_id")) if state.get("summary_id") else None
        clin = [v for v in views if v.doc_type not in NON_CLINICAL_TYPES or v.doc_type == "Utilization Review Request/Decision"]
        res, source = run_llm(ctx, "utilization_assessment", UtilizationOut,
                              claim=f"{claim.claim_number}, DOI {claim.date_of_injury}, {claim.jurisdiction_state}",
                              summary=(summary.content_md[:6000] if summary else ""),
                              requests="\n".join(f"- {r['description']} ({r['provider']}, {fmt_date(r['date'])})" for r in requests) or "none",
                              rules="\n".join(f"[{x['rule_code']}] {x['title']}: {x['criteria_text']}" for rs in rules_by_req.values() for x in rs) or "none",
                              documents="\n\n".join(v.marked(15000) for v in clin)[:120000])
    if res is not None:
        code_to_id = {x["rule_code"]: x["rule_id"] for rs in rules_by_req.values() for x in rs}
        assessments = [{**a.model_dump(exclude={"necessity_indicators"}),
                        "necessity_indicators": [{**i.model_dump(exclude={"citations"}), "citations": resolve_cites(i.citations, amap_rev)}
                                                 for i in a.necessity_indicators],
                        "guideline_rule_ids": [code_to_id[i.guideline_rule_code] for i in a.necessity_indicators if i.guideline_rule_code in code_to_id]}
                       for a in res.requests]
        issues = [{**i.model_dump(exclude={"citations"}), "citations": resolve_cites(i.citations, amap_rev)} for i in res.issues]
        _, rule_issues = rules_utilization(ctx, views, requests, rules_by_req)
        known = {i["issue_type"] for i in issues}
        issues += [i for i in rule_issues if i["issue_type"] in ("missing_evidence",) and "missing_evidence" not in known]
    else:
        assessments, issues = rules_utilization(ctx, views, requests, rules_by_req)
    for a in assessments:
        if not a["ai_recommendation"].upper().startswith("AI DRAFT"):
            a["ai_recommendation"] = "AI DRAFT - not a determination: " + a["ai_recommendation"]
        ctx.db.add(UtilizationAssessment(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id,
                                         request_description=a["request_description"], request_type=a["request_type"],
                                         requesting_provider=a.get("requesting_provider"), request_date=H.normalize_date(a.get("request_date")),
                                         necessity_indicators=a["necessity_indicators"], appropriateness=a.get("appropriateness"),
                                         progression=a.get("progression"), barriers=a.get("barriers", []),
                                         unresolved_questions=a.get("unresolved_questions", []),
                                         guideline_rule_ids=a.get("guideline_rule_ids", []), ai_recommendation=a["ai_recommendation"]))
    existing = {(i.issue_type, i.description) for i in ctx.db.execute(select(ClinicalIssue).where(ClinicalIssue.claim_id == ctx.claim_id)).scalars()}
    new_issues = []
    for i in issues:
        if (i["issue_type"], i["description"]) in existing:
            continue
        row = ClinicalIssue(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, issue_type=i["issue_type"],
                            description=i["description"], severity=i["severity"], suggested_action=i.get("suggested_action"))
        ctx.db.add(row)
        save_citations(ctx.db, "issue", row.id, i.get("citations") or [])
        new_issues.append({"id": row.id, "type": i["issue_type"], "severity": i["severity"]})
    ctx.audit("utilization.draft", "claim", ctx.claim_id, after={"requests": len(assessments), "issues": len(new_issues), "source": source})
    return {"clinical_issues": new_issues, "stage_status": {"clinical_review": "completed"}}
