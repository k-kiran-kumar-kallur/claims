"""Chronology Agent - Stage 6 Step 1 (POC-6, PW-6.1): deterministic assembly + optional concise LLM descriptions."""
from __future__ import annotations

from sqlalchemy import func, select

from app.agents import heuristics as H
from app.agents.common import run_llm
from app.agents.extraction.turning_points import validated_facts
from app.core.ids import uuid7
from app.models import ChronologyEvent, Citation, DocumentIndex, Milestone
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.repositories.docs import citation_dict, load_doc_views
from app.schemas.llm import ChronoDescriptionsOut

EVENT_LABELS = ["Assessment", "Procedure Performed", "Work Capacity Classification", "Interval History", "Reason for Consultation",
                "Chief Complaint", "Requested Treatment", "Response", "Description of Accident", "Plan"]


@agent_node("chronology_agent", "output")
def chronology_agent(state: dict, ctx: AgentContext) -> dict:
    ctx.claim.current_stage = "output"
    views = [v for v in load_doc_views(ctx.db, ctx.claim_id) if v.doc_type not in ("Medical Bill", "Administrative/Fax Cover")]
    version = ctx.db.execute(select(func.max(DocumentIndex.timeline_version)).where(DocumentIndex.claim_id == ctx.claim_id)).scalar()
    idx = {i.document_id: i for i in ctx.db.execute(select(DocumentIndex).where(DocumentIndex.claim_id == ctx.claim_id,
                                                                                  DocumentIndex.timeline_version == version)).scalars()}
    facts = validated_facts(ctx)
    by_doc: dict[str, list] = {}
    for f in facts:
        by_doc.setdefault(f.document_id, []).append(f)
    milestones = ctx.db.execute(select(Milestone).where(Milestone.claim_id == ctx.claim_id, Milestone.status != "superseded")).scalars().all()
    tp_facts = {fid for m in milestones for fid in (m.fact_ids or [])}
    events = []
    for v in views:
        dfacts = by_doc.get(v.id, [])
        key_line = next((lv for lb in EVENT_LABELS for lv in [H.first_labeled(v, [lb])] if lv), None)
        ws = next((f for f in dfacts if f.fact_type == "work_status"), None)
        findings = [f.label for f in dfacts if f.fact_type in ("diagnosis", "imaging", "procedure", "rtw", "mmi")][:4]
        cites = [citation_dict(c) for c in ctx.db.execute(select(Citation).where(
            Citation.owner_type == "fact", Citation.owner_id.in_([f.id for f in dfacts][:6]))).scalars()][:4]
        if not cites and key_line:
            cites = [H.citation_for(v, key_line)]
        events.append({"key": v.id, "date": v.service_date, "provider": v.provider or v.facility, "event_type": v.doc_type or "Other",
                       "description": (key_line.value if key_line else v.title)[:300], "key_findings": "; ".join(findings)[:500],
                       "work_status": ws.value.get("work_status", "").replace("_", " ") if ws else None,
                       "fact_ids": [f.id for f in dfacts], "citations": cites, "document_id": v.id,
                       "episode_id": idx[v.id].episode_id if v.id in idx else None,
                       "order": idx[v.id].sort_order if v.id in idx else 10_000,
                       "turning": any(f.id in tp_facts for f in dfacts)})
    events.sort(key=lambda e: (e["date"] or "9999-12-31", e["order"]))
    if ctx.llm.enabled and events:
        res, _ = run_llm(ctx, "chronology_descriptions", ChronoDescriptionsOut, events="\n".join(
            f"- key: {e['key']} | {e['date']} | {e['event_type']} | {e['description'][:200]} | findings: {e['key_findings'][:200]}" for e in events))
        if res is not None:
            m = {d.key: d for d in res.events}
            for e in events:
                if e["key"] in m:
                    e["description"], e["key_findings"] = m[e["key"]].description, m[e["key"]].key_findings or e["key_findings"]
    prev_version = ctx.db.execute(select(func.max(ChronologyEvent.chronology_version)).where(ChronologyEvent.claim_id == ctx.claim_id)).scalar() or 0
    for old in ctx.db.execute(select(ChronologyEvent).where(ChronologyEvent.claim_id == ctx.claim_id, ChronologyEvent.is_current.is_(True))).scalars():
        old.is_current = False
    for i, e in enumerate(events):
        ctx.db.add(ChronologyEvent(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, event_date=e["date"], provider=e["provider"],
                                   event_type=e["event_type"], description=e["description"], key_findings=e["key_findings"],
                                   work_status=e["work_status"], episode_id=e["episode_id"], document_id=e["document_id"],
                                   fact_ids=e["fact_ids"], citations=e["citations"], sort_order=i, is_turning_point=e["turning"],
                                   chronology_version=prev_version + 1, is_current=True))
    ctx.audit("chronology.build", "claim", ctx.claim_id, after={"events": len(events), "version": prev_version + 1})
    return {}
