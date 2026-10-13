"""Timeline, facts, milestones, discrepancies, clinical issues, citations, RTW, providers and guideline findings
(spec §12.5, §12.6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import envelope, get_db, require_permission
from app.api.v1.claims import clinical_access
from app.core.errors import BadRequest, NotFound
from app.core.ids import now_iso, uuid7
from app.models import (
    Citation,
    Claim,
    ClaimProvider,
    ClinicalIssue,
    Discrepancy,
    Document,
    DocumentClassification,
    DocumentIndex,
    Episode,
    ExtractedFact,
    GuidelineFinding,
    GuidelineRule,
    Milestone,
    Provider,
    ProviderContact,
    RtwStatus,
    TimelineGap,
    URDetermination,
    User,
    UtilizationAssessment,
)
from app.repositories.docs import citation_dict
from app.services import audit
from app.services.actions import (
    Principal,
    act_on_fact,
    act_on_finding,
    resolve_discrepancy,
    update_episode,
    update_gap,
)
from app.services.claims import get_claim_for

router = APIRouter(tags=["clinical"])


def _owned(db: Session, user: Principal, model, id_: str):
    obj = db.get(model, id_)
    if obj is None:
        raise NotFound(f"{model.__name__} not found")
    get_claim_for(db, user, obj.claim_id)
    return obj


def _cites(db: Session, owner_type: str, ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if ids:
        for c in db.execute(select(Citation).where(Citation.owner_type == owner_type, Citation.owner_id.in_(ids))).scalars():
            out.setdefault(c.owner_id, []).append(citation_dict(c))
    return out


# ---- timeline (HITL-1) ---------------------------------------------------------------------------------

@router.get("/claims/{claim_id}/timeline")
def timeline(version: int | None = None, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    v = version or db.execute(select(func.max(Episode.timeline_version)).where(Episode.claim_id == claim.id)).scalar()
    if v is None:
        return envelope({"timeline_version": None, "episodes": [], "gaps": [], "versions": []})
    eps = db.execute(select(Episode).where(Episode.claim_id == claim.id, Episode.timeline_version == v).order_by(Episode.sort_order)).scalars().all()
    idx = db.execute(select(DocumentIndex).where(DocumentIndex.claim_id == claim.id, DocumentIndex.timeline_version == v)
                     .order_by(DocumentIndex.sort_order)).scalars().all()
    docs = {d.id: d for d in db.execute(select(Document).where(Document.claim_id == claim.id)).scalars()}
    cls = {c.document_id: c for c in db.execute(select(DocumentClassification).where(
        DocumentClassification.document_id.in_(list(docs)), DocumentClassification.is_current.is_(True))).scalars()}
    by_ep: dict[str, list] = {}
    for i in idx:
        d, c = docs[i.document_id], cls.get(i.document_id)
        by_ep.setdefault(i.episode_id, []).append({
            "document_id": d.id, "title": d.title, "doc_type": c.doc_type if c else None, "date": c.service_date_start if c else None,
            "provider": c.provider_name if c else None, "confidence": c.confidence if c else None,
            "needs_attention": bool(c and c.needs_attention), "stream": d.stream, "pages": d.page_count, "sort_order": i.sort_order})
    gaps = db.execute(select(TimelineGap).where(TimelineGap.claim_id == claim.id).order_by(TimelineGap.start_date)).scalars().all()
    milestones = db.execute(select(Milestone).where(Milestone.claim_id == claim.id, Milestone.status != "superseded")).scalars().all()
    versions = sorted(set(db.execute(select(Episode.timeline_version).where(Episode.claim_id == claim.id)).scalars()))
    removed = [{"document_id": d.id, "title": d.title or d.original_filename, "status": d.status, "reason": d.status_reason}
               for d in docs.values() if d.status in ("duplicate", "noise", "failed")]
    return envelope({"timeline_version": v, "versions": versions,
                     "episodes": [{**e.to_dict(), "documents": by_ep.get(e.id, [])} for e in eps],
                     "gaps": [g.to_dict() for g in gaps], "milestones": [m.to_dict() for m in milestones], "removed_documents": removed})


class EpisodePatch(BaseModel):
    label: str | None = None
    merge_into: str | None = None
    move_document_ids: list[str] | None = None
    new_label: str | None = None


@router.patch("/claims/{claim_id}/episodes/{episode_id}")
def patch_episode(episode_id: str, body: EpisodePatch, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                  user: Principal = Depends(require_permission("timeline:approve", "classification:edit"))):
    ep = db.get(Episode, episode_id)
    if ep is None or ep.claim_id != claim.id:
        raise NotFound("Episode not found")
    out = update_episode(db, ep, user, body.label, body.merge_into, body.move_document_ids, body.new_label)
    return envelope(out.to_dict())


class GapPatch(BaseModel):
    status: str
    resolution_note: str | None = None


@router.patch("/claims/{claim_id}/gaps/{gap_id}")
def patch_gap(gap_id: str, body: GapPatch, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
              user: Principal = Depends(require_permission("timeline:approve", "care:coordinate"))):
    gap = db.get(TimelineGap, gap_id)
    if gap is None or gap.claim_id != claim.id:
        raise NotFound("Gap not found")
    return envelope(update_gap(db, gap, user, body.status, body.resolution_note).to_dict())


# ---- facts (HITL-2) -----------------------------------------------------------------------------------

@router.get("/claims/{claim_id}/facts")
def facts(fact_type: str | None = None, validation_status: str | None = None, episode_id: str | None = None, include_history: bool = False,
          claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    q = select(ExtractedFact).where(ExtractedFact.claim_id == claim.id)
    if not include_history:
        q = q.where(ExtractedFact.is_current.is_(True))
    if fact_type:
        q = q.where(ExtractedFact.fact_type == fact_type)
    if validation_status:
        q = q.where(ExtractedFact.validation_status == validation_status)
    if episode_id:
        docs = select(DocumentIndex.document_id).where(DocumentIndex.episode_id == episode_id)
        q = q.where(ExtractedFact.document_id.in_(docs))
    rows = db.execute(q.order_by(ExtractedFact.effective_date, ExtractedFact.created_at)).scalars().all()
    cites = _cites(db, "fact", [f.id for f in rows])
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    return envelope([{**f.to_dict(exclude={"item_key"}), "citations": cites.get(f.id, []), "validated_by_name": names.get(f.validated_by)}
                     for f in rows])


class FactAction(BaseModel):
    action: str = Field(pattern="^(accept|edit|reject)$")
    value: dict | None = None
    label: str | None = None
    effective_date: str | None = None
    citations: list[dict] | None = None
    reason: str | None = None


@router.patch("/facts/{fact_id}")
def patch_fact(fact_id: str, body: FactAction, db: Session = Depends(get_db), user: Principal = Depends(require_permission("fact:validate"))):
    f = _owned(db, user, ExtractedFact, fact_id)
    out = act_on_fact(db, f, user, body.action, body.reason, body.value, body.label, body.citations, body.effective_date)
    db.flush()
    return envelope({**out.to_dict(exclude={"item_key"}), "citations": _cites(db, "fact", [out.id]).get(out.id, [])})


class BulkFactAction(BaseModel):
    fact_ids: list[str] = Field(min_length=1)
    action: str = Field(pattern="^(accept)$")
    reason: str | None = None


@router.post("/facts/bulk-action")
def bulk_facts(body: BulkFactAction, db: Session = Depends(get_db), user: Principal = Depends(require_permission("fact:validate"))):
    out = []
    for fid in body.fact_ids:
        f = _owned(db, user, ExtractedFact, fid)
        if f.validation_status in ("rejected",):
            continue
        out.append(act_on_fact(db, f, user, "accept", body.reason).id)
    return envelope({"accepted": out})


@router.get("/claims/{claim_id}/milestones")
def milestones(type: str | None = None, turning_points_only: bool = False, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    q = select(Milestone).where(Milestone.claim_id == claim.id, Milestone.status != "superseded")
    if type:
        q = q.where(Milestone.milestone_type == type)
    if turning_points_only:
        q = q.where(Milestone.is_turning_point.is_(True))
    rows = db.execute(q.order_by(Milestone.milestone_date)).scalars().all()
    fact_cites = _cites(db, "fact", [fid for m in rows for fid in (m.fact_ids or [])])
    return envelope([{**m.to_dict(), "citations": [c for fid in (m.fact_ids or []) for c in fact_cites.get(fid, [])][:4]} for m in rows])


@router.get("/claims/{claim_id}/discrepancies")
def discrepancies(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    return envelope([d.to_dict() for d in db.execute(select(Discrepancy).where(Discrepancy.claim_id == claim.id)).scalars()])


class DiscrepancyPatch(BaseModel):
    resolution: str = Field(min_length=3)


@router.patch("/discrepancies/{did}")
def patch_discrepancy(did: str, body: DiscrepancyPatch, db: Session = Depends(get_db), user: Principal = Depends(require_permission("fact:validate"))):
    d = _owned(db, user, Discrepancy, did)
    return envelope(resolve_discrepancy(db, d, user, body.resolution).to_dict())


@router.get("/claims/{claim_id}/clinical-issues")
def issues(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(ClinicalIssue).where(ClinicalIssue.claim_id == claim.id).order_by(ClinicalIssue.created_at)).scalars().all()
    cites = _cites(db, "issue", [r.id for r in rows])
    return envelope([{**r.to_dict(), "citations": cites.get(r.id, [])} for r in rows])


class IssuePatch(BaseModel):
    status: str = Field(pattern="^(open|in_progress|resolved|dismissed)$")
    owner_id: str | None = None
    note: str | None = None


@router.patch("/clinical-issues/{iid}")
def patch_issue(iid: str, body: IssuePatch, db: Session = Depends(get_db),
                user: Principal = Depends(require_permission("fact:validate", "care:coordinate", "timeline:approve"))):
    row = _owned(db, user, ClinicalIssue, iid)
    before = {"status": row.status, "owner_id": row.owner_id}
    row.status, row.owner_id = body.status, body.owner_id or row.owner_id
    audit.record(db, action="clinical_issue.update", entity_type="clinical_issue", entity_id=row.id, claim_id=row.claim_id,
                 actor_id=user.id, before=before, after=body.model_dump())
    return envelope(row.to_dict())


@router.get("/citations/{citation_id}")
def citation(citation_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    c = db.get(Citation, citation_id)
    if c is None:
        raise NotFound("Citation not found")
    doc = db.get(Document, c.document_id)
    get_claim_for(db, user, doc.claim_id)
    from app.tools.retrieval import citation_resolver_tool
    resolved = citation_resolver_tool(db, c.document_id, c.page_number, c.line_start, c.line_end)
    return envelope({**citation_dict(c), "document_title": doc.title, "text": resolved["text"], "bboxes": resolved["bboxes"]})


# ---- RTW tracker and care coordination (PR-2) ------------------------------------------------------------

@router.get("/claims/{claim_id}/rtw-status")
def rtw(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(RtwStatus).where(RtwStatus.claim_id == claim.id).order_by(RtwStatus.effective_date)).scalars().all()
    cites = _cites(db, "fact", [r.source_fact_id for r in rows if r.source_fact_id])
    fce = db.execute(select(ExtractedFact).where(ExtractedFact.claim_id == claim.id, ExtractedFact.fact_type == "rtw",
                                                 ExtractedFact.is_current.is_(True))).scalars().all()
    return envelope({"history": [{**r.to_dict(), "citations": cites.get(r.source_fact_id, [])} for r in rows],
                     "work_capacity": [{"id": f.id, "label": f.label, "value": f.value, "effective_date": f.effective_date,
                                        "validation_status": f.validation_status} for f in fce]})


@router.get("/claims/{claim_id}/providers")
def providers(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(Provider, ClaimProvider).join(ClaimProvider, ClaimProvider.provider_id == Provider.id)
                      .where(ClaimProvider.claim_id == claim.id).order_by(ClaimProvider.first_seen)).all()
    return envelope([{**p.to_dict(), "role": cp.role, "first_seen": cp.first_seen, "last_seen": cp.last_seen} for p, cp in rows])


class ProviderPatch(BaseModel):
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    address: str | None = None


@router.patch("/claims/{claim_id}/providers/{provider_id}")
def patch_provider(provider_id: str, body: ProviderPatch, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                   user: Principal = Depends(require_permission("care:coordinate"))):
    p = db.get(Provider, provider_id)
    if p is None or db.get(ClaimProvider, (claim.id, provider_id)) is None:
        raise NotFound("Provider not found on this claim")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    audit.record(db, action="provider.update", entity_type="provider", entity_id=p.id, claim_id=claim.id, actor_id=user.id,
                 after=body.model_dump(exclude_unset=True))
    return envelope(p.to_dict())


class ContactIn(BaseModel):
    provider_id: str
    contact_type: str = Field(pattern="^(call|fax|email|meeting)$")
    purpose: str = Field(min_length=3, max_length=64)
    notes: str | None = None
    follow_up_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.get("/claims/{claim_id}/provider-contacts")
def contacts(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(ProviderContact, Provider).join(Provider, Provider.id == ProviderContact.provider_id)
                      .where(ProviderContact.claim_id == claim.id).order_by(ProviderContact.contacted_at.desc())).all()
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    return envelope([{**c.to_dict(), "provider_name": p.name, "contacted_by_name": names.get(c.contacted_by)} for c, p in rows])


@router.post("/claims/{claim_id}/provider-contacts", status_code=201)
def add_contact(body: ContactIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                user: Principal = Depends(require_permission("care:coordinate"))):
    if db.get(ClaimProvider, (claim.id, body.provider_id)) is None:
        raise BadRequest("Provider is not associated with this claim")
    row = ProviderContact(id=uuid7(), claim_id=claim.id, contacted_by=user.id, contacted_at=now_iso(), **body.model_dump())
    db.add(row)
    audit.record(db, action="provider_contact.create", entity_type="provider_contact", entity_id=row.id, claim_id=claim.id,
                 actor_id=user.id, after=body.model_dump())
    return envelope(row.to_dict())


# ---- guideline findings and utilization drafts (spec §12.6) -----------------------------------------------

@router.get("/claims/{claim_id}/guideline-findings")
def findings(finding_type: str | None = None, status: str | None = None, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    q = select(GuidelineFinding).where(GuidelineFinding.claim_id == claim.id)
    if finding_type:
        q = q.where(GuidelineFinding.finding_type == finding_type)
    if status:
        q = q.where(GuidelineFinding.status == status)
    rows = db.execute(q).scalars().all()
    cites = _cites(db, "finding", [r.id for r in rows])
    rules = {r.id: r for r in db.execute(select(GuidelineRule).where(GuidelineRule.id.in_([x.guideline_rule_id for x in rows if x.guideline_rule_id]))).scalars()}
    order = {"high": 0, "medium": 1, "low": 2}
    out = [{**r.to_dict(exclude={"item_key"}), "citations": cites.get(r.id, []),
            "rule": {"rule_code": rules[r.guideline_rule_id].rule_code, "title": rules[r.guideline_rule_id].title,
                     "recommendation": rules[r.guideline_rule_id].recommendation} if r.guideline_rule_id in rules else None}
           for r in rows]
    return envelope(sorted(out, key=lambda x: (x["finding_type"] in ("compliant", "no_applicable_guideline"), order.get(x["severity"], 3))))


class FindingPatch(BaseModel):
    status: str = Field(pattern="^(accepted|dismissed)$")
    reason: str | None = None


@router.patch("/guideline-findings/{fid}")
def patch_finding(fid: str, body: FindingPatch, db: Session = Depends(get_db), user: Principal = Depends(require_permission("flag:act", "fact:validate"))):
    f = _owned(db, user, GuidelineFinding, fid)
    return envelope(act_on_finding(db, f, user, body.status, body.reason).to_dict())


@router.get("/claims/{claim_id}/utilization-assessments")
def utilization(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                _: Principal = Depends(require_permission("ur:determine", "decision:make", "decision:signoff", "timeline:approve"))):
    rows = db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == claim.id)
                      .order_by(UtilizationAssessment.created_at.desc())).scalars().all()
    dets = {d.utilization_assessment_id: d for d in db.execute(select(URDetermination).where(URDetermination.claim_id == claim.id)).scalars()}
    return envelope([{**r.to_dict(), "label": "AI draft - not a determination",
                      "determination": dets[r.id].to_dict() if r.id in dets else None} for r in rows])
