"""Classification Agent - Stage 2 Step 1 (POC-2, PW-2.1).  Fan-out per document via the LangGraph Send API."""
from __future__ import annotations

from sqlalchemy import select

from app.agents.taxonomy import NOISE_TYPES
from app.core.ids import uuid7
from app.models import ClaimProvider, Document, DocumentClassification, Provider
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.repositories.docs import active_documents, alias_map, current_classification, load_doc_view
from app.tools.processing import stream_for, valid_cpt_codes


@agent_node("classification_agent", "classification")
def classification_agent(state: dict, ctx: AgentContext) -> dict:
    """Dispatcher: picks the documents to classify (new, or flagged for reclassification at HITL-1)."""
    docs = active_documents(ctx.db, ctx.claim_id, include_noise=True)
    reclassify = set(state.get("reclassify_document_ids") or [])
    targets = []
    for d in docs:
        cur = current_classification(ctx.db, d.id)
        if d.status == "noise" and d.status_reason == "blank page":
            continue
        if cur is None or d.id in reclassify:
            targets.append(d.id)
    ctx.emit("tool_called", {"tool": "classification_dispatch", "documents": len(targets)})
    return {"document_ids": targets, "reclassify_document_ids": []}


@agent_node("classify_document", "classification")
def classify_document(state: dict, ctx: AgentContext) -> dict:
    """One document (Send payload: run_id, claim_id, document_id)."""
    doc = ctx.db.get(Document, state["document_id"])
    if doc is None:
        return {}
    amap = alias_map(ctx.db, ctx.claim_id)
    view = load_doc_view(ctx.db, doc, amap[doc.id], cls=None)
    cur = current_classification(ctx.db, doc.id)
    if cur is not None and cur.classified_by != "agent":
        # human classification wins; only the stream/title are refreshed
        doc.stream = stream_for(cur.doc_type)
        return {}
    out, source = ctx.tools.call("classifier_tool", doc=view, llm=ctx.llm, call_ctx=ctx.call_ctx,
                                 valid_cpt=valid_cpt_codes(ctx.db))
    icd = ctx.tools.call("code_lookup_tool", db=ctx.db, codes=out.icd10_codes, system="icd10cm")
    out.icd10_codes = [c["code"] for c in icd]
    version = (cur.version + 1) if cur else 1
    if cur:
        cur.is_current = False
    threshold = ctx.settings.CONFIDENCE_THRESHOLD_CLASSIFICATION
    row = DocumentClassification(
        id=uuid7(), document_id=doc.id, doc_type=out.doc_type, confidence=out.confidence,
        provider_name=out.provider_name, provider_specialty=out.provider_specialty, facility=out.facility, npi=out.npi,
        service_date_start=out.service_date_start, service_date_end=out.service_date_end or out.service_date_start,
        encounter_type=out.encounter_type, body_parts=out.body_parts, tags=out.tags.model_dump(),
        icd10_codes=out.icd10_codes, cpt_codes=out.cpt_codes, rationale=f"[{source}] {out.rationale}",
        classified_by="agent", version=version, is_current=True, needs_attention=out.confidence < threshold)
    ctx.db.add(row)
    doc.stream = stream_for(out.doc_type)
    if out.doc_type in NOISE_TYPES:
        doc.title = doc.title or out.doc_type
    ctx.audit("document.classify", "document", doc.id,
              after={"doc_type": out.doc_type, "confidence": out.confidence, "source": source, "version": version})
    low = [doc.id] if out.confidence < threshold else []
    return {"low_confidence_items": low}


def upsert_provider(ctx: AgentContext, name: str, specialty: str | None, facility: str | None, npi: str | None,
                     seen: str | None, doc_type: str) -> None:
    """Provider directory, deduplicated by name - supports NCM provider coordination (PR-2).

    Called from the (single) Organization node so parallel classification branches never race on it."""
    name = name.strip()
    prov = ctx.db.execute(select(Provider).where(Provider.name == name)).scalars().first()
    if prov is None:
        prov = Provider(id=uuid7(), name=name, specialty=specialty, facility=facility, npi=npi)
        ctx.db.add(prov)
    else:
        prov.specialty = prov.specialty or specialty
        prov.facility = prov.facility or facility
    link = ctx.db.get(ClaimProvider, (ctx.claim_id, prov.id))
    if link is None:
        ctx.db.add(ClaimProvider(claim_id=ctx.claim_id, provider_id=prov.id, role=doc_type, first_seen=seen, last_seen=seen))
    elif seen:
        link.first_seen = min(filter(None, [link.first_seen, seen]))
        link.last_seen = max(filter(None, [link.last_seen, seen]))
