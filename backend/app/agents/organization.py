"""Organization Agent - Stage 2 Steps 2-3 (PW-2.2, PW-2.3) and HITL-1 NCM Timeline Check."""
from __future__ import annotations

import re

from sqlalchemy import func, select

from app.agents import heuristics as H
from app.agents.classification import upsert_provider
from app.agents.common import upsert_document_request, upsert_flag
from app.agents.taxonomy import EPISODE_TYPES, NOISE_TYPES
from app.core.ids import uuid7
from app.models import DedupGroup, Document, DocumentIndex, DocumentRequest, Episode, TimelineGap
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import await_human
from app.orchestration.supervisor import route_after_timeline
from app.repositories.docs import active_documents, alias_map, classifications_for, load_doc_view

ADMIN_EPISODES = {"Medical Bill": "billing", "Pharmacy/Prescription Record": "pharmacy",
                  "Employer's First Report of Injury (FROI)": "administrative", "Employer Accident Report": "administrative",
                  "Legal/Correspondence": "administrative", "Policy/Coverage Information": "administrative",
                  "Utilization Review Request/Decision": "administrative", "Other": "administrative"}
ADMIN_LABELS = {"billing": "Billing records (CMS-1500 / UB-04)", "pharmacy": "Pharmacy / prescription records",
                "administrative": "Employer, legal and administrative records"}


@agent_node("organization_agent", "classification")
def organization_agent(state: dict, ctx: AgentContext) -> dict:
    docs = active_documents(ctx.db, ctx.claim_id)
    cls = classifications_for(ctx.db, [d.id for d in docs])

    # 1. administrative noise removal (fax covers, privacy notices, blank pages)
    noise = 0
    for d in docs:
        c = cls.get(d.id)
        if c and c.doc_type in NOISE_TYPES:
            d.status, d.status_reason = "noise", f"administrative noise ({c.doc_type})"
            noise += 1
    docs = [d for d in docs if d.status == "processed"]

    # 2. duplicates across streams (same note faxed twice, provider vs billing packets)
    items = [{"id": d.id, "text": load_doc_view(ctx.db, d, "").text, "received_at": d.created_at} for d in docs]
    dupes = 0
    for g in ctx.tools.call("dedup_tool", items=items):
        for m in g["members"]:
            doc = ctx.db.get(Document, m)
            doc.status, doc.duplicate_of_id = "duplicate", g["canonical"]
            doc.status_reason = f"{g['method']} duplicate (similarity {g['similarity']})"
            dupes += 1
        ctx.db.add(DedupGroup(id=uuid7(), claim_id=ctx.claim_id, canonical_document_id=g["canonical"],
                              member_document_ids=g["members"], method=g["method"], similarity=g["similarity"]))
    docs = [d for d in docs if d.status == "processed"]

    # 3. provider directory (PR-2 care coordination)
    for d in docs:
        c = cls.get(d.id)
        if c and c.provider_name:
            upsert_provider(ctx, c.provider_name, c.provider_specialty, c.facility, c.npi, c.service_date_start, c.doc_type)

    # 4. chronological order and episodes of care
    timeline_items = []
    for i, d in enumerate(docs):
        c = cls.get(d.id)
        dt = c.doc_type if c else "Other"
        timeline_items.append({"id": d.id, "date": c.service_date_start if c else None, "doc_type": dt,
                               "episode_type": ADMIN_EPISODES.get(dt) or EPISODE_TYPES.get(dt, "specialist"),
                               "provider": c.provider_name if c else None, "order": i})
    clinical_items = [t for t in timeline_items if t["episode_type"] not in ADMIN_LABELS]
    episodes = ctx.tools.call("timeline_builder_tool", docs=clinical_items)
    for et, label in ADMIN_LABELS.items():
        members = sorted([t for t in timeline_items if t["episode_type"] == et], key=lambda t: t["date"] or "9999")
        if members:
            dates = [t["date"] for t in members if t["date"]]
            episodes.append({"episode_type": et, "label": label, "doc_ids": [t["id"] for t in members],
                             "start": min(dates) if dates else None, "end": max(dates) if dates else None, "providers": []})
    prev = ctx.db.execute(select(func.max(Episode.timeline_version)).where(Episode.claim_id == ctx.claim_id)).scalar() or 0
    version = max(prev, state.get("timeline_version") or 0) + 1
    by_id = {t["id"]: t for t in timeline_items}
    sort = 0
    for idx, ep in enumerate(episodes):
        row = Episode(id=uuid7(), claim_id=ctx.claim_id, label=ep["label"], episode_type=ep["episode_type"],
                      start_date=ep["start"], end_date=ep["end"], provider_ids=ep.get("providers", []),
                      timeline_version=version, sort_order=idx)
        ctx.db.add(row)
        for doc_id in sorted(ep["doc_ids"], key=lambda i: (by_id[i]["date"] or "9999", by_id[i]["order"])):
            ctx.db.add(DocumentIndex(claim_id=ctx.claim_id, document_id=doc_id, episode_id=row.id, sort_order=sort,
                                     timeline_version=version))
            sort += 1

    # 5. gap detection (missing referenced records, interval gaps, visit-count mismatches, date anomalies)
    amap = alias_map(ctx.db, ctx.claim_id)
    views = [load_doc_view(ctx.db, d, amap[d.id], cls.get(d.id)) for d in docs]
    doc_types = {d.id: (cls[d.id].doc_type if d.id in cls else "Other") for d in docs}
    doc_dates = {d.id: (cls[d.id].service_date_start if d.id in cls else None) for d in docs}
    billed = []
    for v in views:
        if doc_types[v.id] != "Medical Bill":
            continue
        for ln in v.lines:
            m = re.match(r"\s*(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*\d+\s*\|\s*(7\d{4})", ln.text)
            if m:
                billed.append({"kind": "imaging", "code": m.group(2), "date": H.normalize_date(m.group(1)),
                               "citation": H.citation_for(v, ln)})
    gaps = ctx.tools.call("gap_detector_tool", docs=views, doc_types=doc_types, doc_dates=doc_dates,
                          date_of_injury=ctx.claim.date_of_injury, gap_days=ctx.settings.TREATMENT_GAP_DAYS, billed=billed)
    existing = {g.dedup_key: g for g in ctx.db.execute(select(TimelineGap).where(TimelineGap.claim_id == ctx.claim_id)).scalars()}
    seen_keys, missing = set(), []
    for g in gaps:
        if g["dedup_key"] in seen_keys:
            continue
        seen_keys.add(g["dedup_key"])
        row = existing.get(g["dedup_key"])
        if row is None:
            row = TimelineGap(id=uuid7(), claim_id=ctx.claim_id, gap_type=g["gap_type"], description=g["description"],
                              start_date=g.get("start_date"), end_date=g.get("end_date"), severity=g["severity"],
                              evidence=g.get("evidence", []), timeline_version=version, dedup_key=g["dedup_key"])
            ctx.db.add(row)
        else:
            row.timeline_version = version
        if g["gap_type"] == "missing_referenced_record" and row.status == "open":
            req = upsert_document_request(ctx, g["dedup_key"], g.get("request") or g["description"], g["description"],
                                          _requested_from(views, g))
            missing.append({"key": g["dedup_key"], "description": req.description})
        upsert_flag(ctx, f"gap:{g['dedup_key']}", flag_type="gap", severity=g["severity"], title=g["description"][:250],
                    evidence=g.get("evidence", []), ref_type="timeline_gap", ref_id=row.id,
                    ai_recommendation="Request the missing record" if g["gap_type"] == "missing_referenced_record"
                    else "Confirm whether the gap is explained")
    for key, row in existing.items():  # previously missing records that have now arrived
        if key not in seen_keys and row.status in ("open", "requested") and row.gap_type == "missing_referenced_record":
            row.status, row.resolution_note = "resolved", "Referenced record now present in the file"
            req = ctx.db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == ctx.claim_id,
                                                               DocumentRequest.dedup_key == key)).scalar_one_or_none()
            if req:
                req.status = "received"

    # quality gate: every non-noise document belongs to exactly one episode
    indexed = {doc_id for ep in episodes for doc_id in ep["doc_ids"]}
    unassigned = [d.id for d in docs if d.id not in indexed]
    ctx.audit("timeline.organize", "claim", ctx.claim_id,
              after={"timeline_version": version, "episodes": len(episodes), "gaps": len(seen_keys),
                     "duplicates_removed": dupes, "noise_removed": noise, "unassigned": unassigned})
    ctx.claim.current_stage = "classification"
    return {"timeline_version": version, "missing_documents": missing,
            "errors": [{"node": "organization_agent", "error": f"unassigned documents {unassigned}"}] if unassigned else []}


def _requested_from(views: list[H.DocView], gap: dict) -> str | None:
    for ev in gap.get("evidence") or []:
        for v in views:
            if v.id == ev.get("document_id"):
                return v.provider or v.facility
    return None


def timeline_payload(ctx: AgentContext, version: int) -> dict:
    eps = ctx.db.execute(select(Episode).where(Episode.claim_id == ctx.claim_id, Episode.timeline_version == version)
                         .order_by(Episode.sort_order)).scalars().all()
    idx = ctx.db.execute(select(DocumentIndex).where(DocumentIndex.claim_id == ctx.claim_id,
                                                     DocumentIndex.timeline_version == version)
                         .order_by(DocumentIndex.sort_order)).scalars().all()
    docs = {d.id: d for d in ctx.db.execute(select(Document).where(Document.claim_id == ctx.claim_id)).scalars()}
    cls = classifications_for(ctx.db, list(docs))
    by_ep: dict[str, list[dict]] = {}
    for i in idx:
        d, c = docs[i.document_id], cls.get(i.document_id)
        by_ep.setdefault(i.episode_id, []).append({
            "document_id": d.id, "title": d.title, "doc_type": c.doc_type if c else None,
            "date": c.service_date_start if c else None, "provider": c.provider_name if c else None,
            "confidence": c.confidence if c else None, "needs_attention": bool(c and c.needs_attention), "pages": d.page_count})
    gaps = ctx.db.execute(select(TimelineGap).where(TimelineGap.claim_id == ctx.claim_id)).scalars().all()
    removed = [{"document_id": d.id, "title": d.title or d.original_filename, "status": d.status, "reason": d.status_reason}
               for d in docs.values() if d.status in ("duplicate", "noise", "failed")]
    reqs = ctx.db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == ctx.claim_id,
                                                        DocumentRequest.status.in_(["open", "sent"]))).scalars().all()
    return {"timeline_version": version,
            "episodes": [{"id": e.id, "label": e.label, "episode_type": e.episode_type, "start_date": e.start_date,
                          "end_date": e.end_date, "documents": by_ep.get(e.id, [])} for e in eps],
            "gaps": [{"id": g.id, "gap_type": g.gap_type, "description": g.description, "severity": g.severity,
                      "status": g.status, "start_date": g.start_date, "end_date": g.end_date} for g in gaps],
            "removed_documents": removed,
            "document_requests": [{"id": r.id, "description": r.description, "status": r.status} for r in reqs],
            "summary": f"{sum(len(v) for v in by_ep.values())} documents in {len(eps)} episodes; "
                       f"{len([g for g in gaps if g.status == 'open'])} open gaps; {len(removed)} removed (duplicates/noise)"}


@agent_node("hitl_timeline_check", "classification")
def hitl_timeline_check(state: dict, ctx: AgentContext) -> dict:
    """HITL-1 NCM Timeline Check (PW-2.3): verify completeness and chronological integrity."""
    counts = state.get("retry_counts") or {}
    iteration = counts.get("timeline_loop", 0)
    version = state.get("timeline_version") or 1
    review, response = await_human(ctx, "HITL-1", iteration, f"Verify timeline (version {version})",
                                   lambda: timeline_payload(ctx, version))
    route, extra = route_after_timeline(ctx, response, iteration)
    return {"human_feedback": [{"checkpoint": "HITL-1", "review_id": review.id, "response": response}],
            "last_route": route, "retry_counts": {"timeline_loop": iteration + 1}, **extra,
            "stage_status": {"classification": "completed"} if route == "continue" else {}}

