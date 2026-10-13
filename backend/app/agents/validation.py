"""Validation Agent - Stage 4 Step 2 automated part (PW-4.2: traceability, discrepancy resolution, zero extrapolation)
and HITL-2 Clinical Fact Validation."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from sqlalchemy import select

from app.agents import heuristics as H
from app.agents.common import fmt_date, run_llm
from app.core.ids import uuid7
from app.models import Citation, Discrepancy, ExtractedFact
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import await_human
from app.orchestration.supervisor import route_after_validation
from app.repositories.docs import best_match, citation_dict, load_doc_views
from app.schemas.llm import JudgeOut

USABLE = ("auto_verified", "validated", "edited")


def _value_tokens(value) -> list[str]:
    """Checkable tokens of a value: codes, numbers, dates (as written in records)."""
    toks: list[str] = []
    for v in (value.values() if isinstance(value, dict) else [value]):
        if isinstance(v, list):
            for x in v:
                toks += _value_tokens(x if isinstance(x, dict) else {"x": x})
            continue
        if v is None or isinstance(v, bool):
            continue
        s = str(v)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            y, m, d = s.split("-")
            toks.append(f"{m}/{d}/{y}")
        elif re.fullmatch(r"[A-TV-Z]\d{2}\.[0-9A-Z]{1,4}|\d{5}", s):
            toks.append(s)
        elif isinstance(v, int | float):
            toks.append(str(v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
    return toks


def deterministic_entailment(value, quote: str) -> str:
    toks = _value_tokens(value)
    if not toks:
        return "yes"
    q = quote.replace(" ", "")
    hits = sum(1 for t in toks if t.replace(" ", "") in q or t.lstrip("0") in q)
    return "yes" if hits == len(toks) else ("partial" if hits else "no")


def _judge(ctx: AgentContext, items: list[tuple[ExtractedFact, str]]) -> dict[str, tuple[str, str]]:
    verdicts: dict[str, tuple[str, str]] = {}
    for f, quote in items:
        verdicts[f.id] = (deterministic_entailment(f.value, quote), "deterministic token check")
    llm_items = [(f, q) for f, q in items if "-llm" in (f.extractor_version or "")]
    for i in range(0, len(llm_items), 30):
        batch = llm_items[i:i + 30]
        payload = "\n".join(f"- key: {f.id}\n  value: {json.dumps(f.value, default=str)[:400]}\n  quote: \"{q[:500]}\"" for f, q in batch)
        res, _ = run_llm(ctx, "fact_judge", JudgeOut, items=payload)
        if res is None:
            continue
        for v in res.verdicts:
            if v.key in verdicts:
                det = verdicts[v.key][0]
                # the stricter of LLM judge and deterministic check wins
                order = {"yes": 2, "partial": 1, "no": 0}
                verdicts[v.key] = (v.verdict if order[v.verdict] <= order[det] else det, v.reason)
    return verdicts


def _consistency(ctx: AgentContext, facts: list[ExtractedFact]) -> list[dict]:
    issues: list[dict] = []
    views = load_doc_views(ctx.db, ctx.claim_id)
    # surgery date: operative report vs post-op references vs CMS-1500 date of service
    from app.repositories.docs import classifications_for
    cls = classifications_for(ctx.db, list({f.document_id for f in facts if f.document_id}))

    def is_surgery(f) -> bool:  # only operative procedures (not therapy sessions) are cross-checked
        cpt = str(f.value.get("cpt") or "")
        return (cls.get(f.document_id) is not None and cls[f.document_id].doc_type == "Operative Report") or \
            (cpt[:1] in "123456" and len(cpt) == 5 and cpt[:1] != "") or \
            bool(re.search(r"ectomy|otomy|fusion|arthroscop|repair|surgery", str(f.value.get("description", "")) + f.label, re.I))

    for p in [f for f in facts if f.fact_type == "procedure" and isinstance(f.value, dict) and f.value.get("date") and is_surgery(f)]:
        op_date, cpt = H.normalize_date(str(p.value["date"])), p.value.get("cpt")
        if not op_date:
            continue
        refs = []
        for v in views:
            if v.id == p.document_id:
                continue
            for ln in v.lines:
                if (cpt and cpt in ln.text) or re.search(r"microdiscectomy|laminotomy|surgery performed", ln.text, re.I):
                    for d in H.find_dates(ln.text):
                        if abs((date.fromisoformat(d) - date.fromisoformat(op_date)).days) <= 30:
                            refs.append((d, v, ln))
        conflicting = [r for r in refs if r[0] != op_date]
        if conflicting:
            d, v, ln = conflicting[0]
            issues.append({"type": "consistency", "fact_ids": [p.id],
                           "description": f"Surgery date {fmt_date(op_date)} in the operative report differs from {fmt_date(d)} in {v.title.title()}",
                           "evidence": H.citation_for(v, ln)})
    # conflicting MMI opinions (treating vs IME)
    mmi = [f for f in facts if f.fact_type == "mmi" and isinstance(f.value, dict)]
    statuses = {(f.value.get("declaring_provider"), f.value.get("status")) for f in mmi if f.value.get("declaring_provider")}
    providers = {p for p, _ in statuses}
    if len(providers) > 1 and len({s for _, s in statuses}) > 1 and any(s == "reached" for _, s in statuses):
        issues.append({"type": "conflicting_mmi", "fact_ids": [f.id for f in mmi],
                       "description": "Conflicting MMI opinions between providers: " + "; ".join(f"{p}: {s}" for p, s in statuses)})
    # RTW restrictions vs FCE capacity
    fce = [f for f in facts if f.fact_type == "rtw" and isinstance(f.value, dict) and f.value.get("capacity")]
    if fce:
        cap = fce[-1]
        for ws in [f for f in facts if f.fact_type == "work_status" and isinstance(f.value, dict)]:
            if ws.value.get("work_status") == "full_duty" and cap.value.get("meets_job_demands") is False and \
                    (ws.effective_date or "") >= (cap.effective_date or ""):
                issues.append({"type": "plausibility", "fact_ids": [ws.id, cap.id],
                               "description": f"Full-duty release on {fmt_date(ws.effective_date)} conflicts with FCE showing {cap.value['capacity']} capacity below job demands"})
    return issues


def _plausible(ctx: AgentContext, f: ExtractedFact) -> str | None:
    doi = ctx.claim.date_of_injury
    today = date.today().isoformat()
    if f.effective_date and f.effective_date > today:
        return f"effective date {f.effective_date} is in the future"
    if doi and f.effective_date and f.fact_type not in ("medication",) and f.effective_date < (date.fromisoformat(doi) - timedelta(days=730)).isoformat():
        return f"effective date {f.effective_date} is outside the review time window"
    if f.fact_type == "mmi" and isinstance(f.value, dict) and doi:
        for k in ("date", "anticipated_date"):
            d = f.value.get(k)
            if d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)) and d < doi:
                return f"MMI {k.replace('_', ' ')} {d} is before the date of injury"
    return None


@agent_node("validation_agent", "extraction")
def validation_agent(state: dict, ctx: AgentContext) -> dict:
    facts = ctx.db.execute(select(ExtractedFact).where(ExtractedFact.claim_id == ctx.claim_id, ExtractedFact.is_current.is_(True),
                                                       ExtractedFact.validation_status == "pending")).scalars().all()
    threshold = ctx.settings.QUOTE_MATCH_THRESHOLD
    grounded: list[tuple[ExtractedFact, str]] = []
    notes: dict[str, list[str]] = {f.id: [] for f in facts}
    per_doc: dict[str, list[int]] = {}
    for f in facts:
        cites = ctx.db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id == f.id)).scalars().all()
        best_quote, ok = "", False
        for c in cites:
            m = best_match(ctx.db, c.document_id, c.page_number, c.line_start, c.line_end, c.quote)
            c.page_id, c.page_number, c.line_start, c.line_end = m["page_id"], m["page_number"], m["line_start"], m["line_end"]
            c.match_score = round(m["score"], 3)
            if m["score"] >= threshold:
                ok, best_quote = True, best_quote or c.quote
        if not cites:
            notes[f.id].append("ungrounded: no citation")
        elif not ok:
            notes[f.id].append(f"citation quote does not match the source text (best score {max(c.match_score or 0 for c in cites):.2f})")
        if ok:
            grounded.append((f, best_quote))
        stats = per_doc.setdefault(f.document_id or "", [0, 0])
        stats[1] += 1
        if not ok:
            stats[0] += 1
            f.validation_status = "rejected"  # zero extrapolation: ungrounded facts never pass downstream
    verdicts = _judge(ctx, grounded)
    issues = _consistency(ctx, [f for f, _ in grounded] + list(ctx.db.execute(
        select(ExtractedFact).where(ExtractedFact.claim_id == ctx.claim_id, ExtractedFact.is_current.is_(True),
                                    ExtractedFact.validation_status.in_(USABLE))).scalars()))
    in_discrepancy = {fid for i in issues for fid in i["fact_ids"]}
    for f, _q in grounded:
        verdict, reason = verdicts.get(f.id, ("yes", ""))
        problem = _plausible(ctx, f)
        if verdict != "yes":
            notes[f.id].append(f"entailment: {verdict} ({reason})")
        if problem:
            notes[f.id].append(f"plausibility: {problem}")
        if f.confidence < ctx.settings.CONFIDENCE_THRESHOLD_FACT:
            notes[f.id].append(f"confidence {f.confidence:.2f} below threshold")
        if f.id in in_discrepancy:
            notes[f.id].append("involved in a cross-document discrepancy")
        f.validation_status = "needs_review" if (verdict != "yes" or problem or f.confidence < ctx.settings.CONFIDENCE_THRESHOLD_FACT
                                                 or f.id in in_discrepancy) else "auto_verified"
    for f in facts:
        f.validation_notes = notes[f.id]
    existing = {d.description for d in ctx.db.execute(select(Discrepancy).where(Discrepancy.claim_id == ctx.claim_id)).scalars()}
    for i in issues:
        if i["description"] not in existing:
            ctx.db.add(Discrepancy(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, fact_ids=i["fact_ids"],
                                   discrepancy_type=i["type"], description=i["description"]))
    loops = (state.get("retry_counts") or {}).get("extraction_loop", 0)
    route, bad_docs = route_after_validation(ctx, {d: (s[0], s[1]) for d, s in per_doc.items()}, loops)
    if route == "rerun_extraction":
        for f in facts:
            if f.document_id in bad_docs and f.validation_status == "rejected":
                f.is_current = False
    counts = {s: sum(1 for f in facts if f.validation_status == s) for s in ("auto_verified", "needs_review", "rejected")}
    ctx.audit("facts.validate", "claim", ctx.claim_id, after={**counts, "discrepancies": len(issues), "route": route})
    return {"last_route": route, "rerun_extraction_document_ids": bad_docs,
            "retry_counts": {"extraction_loop": loops + (1 if route == "rerun_extraction" else 0)}}


def fact_payload(ctx: AgentContext) -> dict:
    facts = ctx.db.execute(select(ExtractedFact).where(ExtractedFact.claim_id == ctx.claim_id, ExtractedFact.is_current.is_(True),
                                                       ExtractedFact.validation_status != "rejected")
                           .order_by(ExtractedFact.effective_date)).scalars().all()
    review = [f for f in facts if f.validation_status in ("needs_review", "pending") or (f.is_milestone and f.validation_status == "auto_verified")]
    cites = {}
    for c in ctx.db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id.in_([f.id for f in review]))).scalars():
        cites.setdefault(c.owner_id, []).append(citation_dict(c))
    discrepancies = ctx.db.execute(select(Discrepancy).where(Discrepancy.claim_id == ctx.claim_id, Discrepancy.status == "open")).scalars().all()
    rejected = ctx.db.execute(select(ExtractedFact.id).where(ExtractedFact.claim_id == ctx.claim_id, ExtractedFact.is_current.is_(True),
                                                             ExtractedFact.validation_status == "rejected")).scalars().all()
    return {"fact_ids": [f.id for f in review],
            "facts": [{"id": f.id, "fact_type": f.fact_type, "label": f.label, "value": f.value, "effective_date": f.effective_date,
                       "confidence": f.confidence, "validation_status": f.validation_status, "is_milestone": f.is_milestone,
                       "notes": f.validation_notes, "citations": cites.get(f.id, [])} for f in review],
            "discrepancies": [{"id": d.id, "description": d.description, "fact_ids": d.fact_ids, "type": d.discrepancy_type} for d in discrepancies],
            "stats": {"total": len(facts), "to_review": len(review), "rejected_ungrounded": len(rejected)}}


@agent_node("hitl_fact_validation", "extraction")
def hitl_fact_validation(state: dict, ctx: AgentContext) -> dict:
    """HITL-2: always for milestone facts; otherwise only needs_review facts (spec §6.5)."""
    payload = fact_payload(ctx)
    if not payload["fact_ids"] and not payload["discrepancies"]:
        return {"stage_status": {"extraction": "in_progress"}}
    iteration = (state.get("retry_counts") or {}).get("extraction_loop", 0)
    review, response = await_human(ctx, "HITL-2", iteration, f"Validate {len(payload['fact_ids'])} facts against source", lambda: payload)
    return {"human_feedback": [{"checkpoint": "HITL-2", "review_id": review.id, "response": response}]}
