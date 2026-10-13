"""Shared machinery for the parallel extractors (spec §7.6)."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from sqlalchemy import func, select

from app.agents import heuristics as H
from app.agents.common import run_llm
from app.agents.taxonomy import FACT_TYPES, MILESTONE_FACT_TYPES
from app.core.ids import uuid7
from app.models import Document, DocumentIndex, Episode, ExtractedFact
from app.orchestration.context import AgentContext
from app.repositories.docs import load_doc_views, resolve_cites, save_citations
from app.schemas.llm import FactsOut

EXTRACTOR_VERSION = "1.0"


def fact(fact_type: str, label: str, value: dict, doc: H.DocView, item, confidence: float,
         effective_date: str | None = None) -> dict:
    return {"fact_type": fact_type, "label": label[:250], "value": value, "document_id": doc.id,
            "effective_date": effective_date or doc.service_date, "confidence": confidence,
            "citations": [H.citation_for(doc, item)]}


def normalize_value(value: dict, reference: str | None = None) -> dict:
    """ISO-8601 dates and normalised units (lb, %) inside structured fact values (spec §7.6 quality gates)."""
    out = {}
    for k, v in value.items():
        if isinstance(v, dict):
            out[k] = normalize_value(v, reference)
            continue
        if isinstance(v, list):
            out[k] = [normalize_value(x, reference) if isinstance(x, dict) else x for x in v]
            continue
        if isinstance(v, str) and ("date" in k or k in ("effective", "next_reevaluation")):
            out[k] = H.normalize_date(v, reference) or v
        elif isinstance(v, str) and re.fullmatch(r"\d+\s*(lb|lbs|pounds)", v.strip(), re.I):
            out[k] = int(re.match(r"\d+", v.strip()).group(0))
        elif isinstance(v, str) and k.endswith("_pct") and v.strip().rstrip("%").isdigit():
            out[k] = int(v.strip().rstrip("%"))
        else:
            out[k] = v
    return out


def target_views(ctx: AgentContext, state: dict) -> list[H.DocView]:
    ids = state.get("rerun_extraction_document_ids")
    views = load_doc_views(ctx.db, ctx.claim_id)
    if ids:
        views = [v for v in views if v.id in set(ids)]
    elif state.get("mode") == "incremental":
        done = set(ctx.db.execute(select(ExtractedFact.document_id).where(ExtractedFact.claim_id == ctx.claim_id)).scalars())
        views = [v for v in views if v.id not in done]
    return views


def episode_groups(ctx: AgentContext, views: list[H.DocView]) -> list[list[H.DocView]]:
    """Group documents by episode of care (spec: extraction runs per episode)."""
    version = ctx.db.execute(select(func.max(Episode.timeline_version)).where(Episode.claim_id == ctx.claim_id)).scalar()
    idx = ctx.db.execute(select(DocumentIndex).where(DocumentIndex.claim_id == ctx.claim_id,
                                                     DocumentIndex.timeline_version == version)).scalars().all()
    ep_of = {i.document_id: i.episode_id for i in idx}
    groups: dict[str, list[H.DocView]] = {}
    for v in views:
        groups.setdefault(ep_of.get(v.id, v.id), []).append(v)
    out = []
    for g in groups.values():  # keep prompts small: split large episodes
        chunk, size = [], 0
        for v in g:
            if chunk and size + len(v.text) > 40000:
                out.append(chunk)
                chunk, size = [], 0
            chunk.append(v)
            size += len(v.text)
        if chunk:
            out.append(chunk)
    return out


def run_extractor(ctx: AgentContext, state: dict, extractor: str, prompt: str, allowed: set[str],
                  select_docs: Callable[[H.DocView], bool], rules_fn: Callable[[H.DocView], list[dict]]) -> dict:
    views = [v for v in target_views(ctx, state) if select_docs(v)]
    facts: list[dict] = []
    source = "rules"
    if ctx.llm.enabled and views:
        for group in episode_groups(ctx, views):
            res, source = run_llm(ctx, prompt, FactsOut, documents="\n\n".join(v.marked(20000) for v in group))
            if res is None:  # graceful degradation for this group
                for v in group:
                    facts += rules_fn(v)
                continue
            rev = {v.alias: v.id for v in group}
            for f in res.facts:
                if f.fact_type not in allowed:
                    continue
                cites = resolve_cites(f.citations, rev)
                facts.append({"fact_type": f.fact_type, "label": f.label, "value": f.value,
                              "document_id": cites[0]["document_id"] if cites else group[0].id,
                              "effective_date": H.normalize_date(f.effective_date) if f.effective_date else None,
                              "confidence": f.confidence, "citations": cites})
    else:
        for v in views:
            facts += rules_fn(v)
    return persist_facts(ctx, extractor, facts, source)


def persist_facts(ctx: AgentContext, extractor: str, facts: list[dict], source: str) -> dict:
    created, low = 0, []
    for f in facts:
        if f["fact_type"] not in FACT_TYPES:
            continue
        cite0 = f["citations"][0] if f["citations"] else {}
        digest = hashlib.sha1(f"{f['label']}|{sorted(f['value'].items()) if isinstance(f['value'], dict) else f['value']}".encode()).hexdigest()[:12]
        key = f"{extractor}:{f['document_id']}:{f['fact_type']}:{cite0.get('page_number')}:{cite0.get('line_start')}:{digest}"
        existing = ctx.db.execute(select(ExtractedFact).where(ExtractedFact.claim_id == ctx.claim_id,
                                                              ExtractedFact.item_key == key,
                                                              ExtractedFact.is_current.is_(True))).scalar_one_or_none()
        if existing is not None:
            continue  # idempotent: previously extracted (and possibly validated) facts are kept
        doc = ctx.db.get(Document, f["document_id"])
        value = normalize_value(f["value"], f.get("effective_date")) if isinstance(f["value"], dict) else {"value": f["value"]}
        if f["fact_type"] == "medication":  # deterministic drug-class tagging (never left to the model)
            name = str(value.get("name") or f["label"]).lower()
            value["is_opioid"] = any(o in name for o in H.OPIOIDS)
        row = ExtractedFact(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, document_id=doc.id if doc else None,
                            fact_type=f["fact_type"], label=f["label"], value=value, normalized_value=value,
                            effective_date=f.get("effective_date"), confidence=float(f["confidence"]),
                            extractor=extractor, extractor_version=f"{EXTRACTOR_VERSION}-{source}",
                            is_milestone=f["fact_type"] in MILESTONE_FACT_TYPES, validation_status="pending", item_key=key)
        ctx.db.add(row)
        save_citations(ctx.db, "fact", row.id, f["citations"], fact_id=row.id, rescore=False)
        created += 1
        if f["confidence"] < ctx.settings.CONFIDENCE_THRESHOLD_FACT:
            low.append(row.id)
    ctx.audit("facts.extract", "claim", ctx.claim_id, after={"extractor": extractor, "facts": created, "source": source})
    return {"low_confidence_items": low}
