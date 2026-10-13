"""Human actions on AI output (facts, flags, classifications, episodes, gaps, summaries, chronology).

Every action is audited; overrides of AI flags require a reason (spec §3.3 rule 4)."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import heuristics as H
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.ids import now_iso, uuid7
from app.models import (
    ChronologyEvent,
    Citation,
    Discrepancy,
    Document,
    DocumentClassification,
    DocumentIndex,
    Episode,
    ExtractedFact,
    Flag,
    GuidelineFinding,
    Page,
    Summary,
    TimelineGap,
)
from app.repositories.docs import citation_dict, save_citations
from app.services import audit
from app.tools.processing import stream_for


@dataclass
class Principal:
    id: str
    email: str
    full_name: str
    roles: list[str]
    permissions: set[str]
    ip: str | None = None
    user_agent: str | None = None
    team: str = "default"
    extra: dict = field(default_factory=dict)

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def _audit(db: Session, user: Principal, action: str, entity_type: str, entity_id: str | None, claim_id: str | None,
           before=None, after=None) -> None:
    audit.record(db, action=action, entity_type=entity_type, entity_id=entity_id, claim_id=claim_id, actor_type="user",
                 actor_id=user.id, before=before, after=after, ip=user.ip, user_agent=user.user_agent)


# ---- facts (HITL-2) -------------------------------------------------------------------------------

def act_on_fact(db: Session, fact: ExtractedFact, user: Principal, action: str, reason: str | None = None,
                value: dict | None = None, label: str | None = None, citations: list[dict] | None = None,
                effective_date: str | None = None) -> ExtractedFact:
    if not fact.is_current:
        raise Conflict("This fact has been superseded; act on the current version")
    before = {"status": fact.validation_status, "value": fact.value}
    if action == "accept":
        if fact.validation_status == "rejected" and not reason:
            raise BadRequest("Accepting a rejected (ungrounded) fact requires a reason")
        fact.validation_status, fact.validated_by, fact.validated_at = "validated", user.id, now_iso()
        result = fact
    elif action == "reject":
        if not reason:
            raise BadRequest("A reason is required to reject a fact")
        fact.validation_status, fact.validated_by, fact.validated_at = "rejected", user.id, now_iso()
        fact.validation_notes = [*(fact.validation_notes or []), f"rejected by reviewer: {reason}"]
        result = fact
    elif action == "edit":
        if value is None:
            raise BadRequest("An edited value is required")
        if not reason:
            raise BadRequest("A reason is required when editing a fact")
        old_cites = db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id == fact.id)).scalars().all()
        new = ExtractedFact(id=uuid7(), claim_id=fact.claim_id, run_id=fact.run_id, document_id=fact.document_id,
                            episode_id=fact.episode_id, fact_type=fact.fact_type, label=label or fact.label, value=value,
                            normalized_value=value, effective_date=H.normalize_date(effective_date) if effective_date else fact.effective_date,
                            confidence=1.0, extractor=fact.extractor, extractor_version=fact.extractor_version,
                            is_milestone=fact.is_milestone, validation_status="edited", validated_by=user.id,
                            validated_at=now_iso(), supersedes_fact_id=fact.id, item_key=fact.item_key,
                            validation_notes=[f"edited by reviewer: {reason}"])
        db.add(new)
        fact.is_current = False
        cites = citations if citations else [citation_dict(c) for c in old_cites]
        if not cites:
            raise BadRequest("Edited facts must keep at least one source citation (zero extrapolation)")
        save_citations(db, "fact", new.id, cites, fact_id=new.id)
        result = new
    else:
        raise BadRequest("action must be accept, edit or reject")
    _audit(db, user, f"fact.{action}", "fact", fact.id, fact.claim_id, before=before,
           after={"status": result.validation_status, "value": result.value, "reason": reason, "new_id": result.id})
    return result


def resolve_discrepancy(db: Session, d: Discrepancy, user: Principal, resolution: str) -> Discrepancy:
    if not resolution:
        raise BadRequest("A resolution is required")
    d.status, d.resolution, d.resolved_by = "resolved", resolution, user.id
    _audit(db, user, "discrepancy.resolve", "discrepancy", d.id, d.claim_id, after={"resolution": resolution})
    return d


# ---- flags (HITL-4 one-click) -----------------------------------------------------------------------

def act_on_flag(db: Session, flag: Flag, user: Principal, action: str, reason: str | None = None,
                value: str | None = None) -> Flag:
    if action not in ("approve", "reject", "modify"):
        raise BadRequest("action must be approve, reject or modify")
    override = action in ("reject", "modify")
    if override and not (reason and reason.strip()):
        raise BadRequest("A reason is mandatory when overriding an AI flag")
    if action == "modify" and not value:
        raise BadRequest("A modified value is required")
    before = {"human_action": flag.human_action}
    flag.human_action = {"approve": "approved", "reject": "rejected", "modify": "modified"}[action]
    flag.modified_value, flag.reason, flag.is_override = value, reason, override
    flag.acted_by, flag.acted_at = user.id, now_iso()
    if flag.ref_type == "guideline_finding" and flag.ref_id:
        finding = db.get(GuidelineFinding, flag.ref_id)
        if finding:
            finding.status = "accepted" if action == "approve" else "dismissed"
            finding.reviewed_by, finding.review_reason = user.id, reason
    _audit(db, user, f"flag.{action}" + (".override" if override else ""), "flag", flag.id, flag.claim_id, before=before,
           after={"action": action, "reason": reason, "value": value})
    return flag


def act_on_finding(db: Session, finding: GuidelineFinding, user: Principal, status: str, reason: str | None) -> GuidelineFinding:
    if status not in ("accepted", "dismissed"):
        raise BadRequest("status must be accepted or dismissed")
    if status == "dismissed" and not reason:
        raise BadRequest("A reason is required to dismiss a guideline finding")
    finding.status, finding.reviewed_by, finding.review_reason = status, user.id, reason
    flag = db.execute(select(Flag).where(Flag.ref_type == "guideline_finding", Flag.ref_id == finding.id)).scalar_one_or_none()
    if flag and flag.human_action is None:
        act_on_flag(db, flag, user, "approve" if status == "accepted" else "reject", reason)
    _audit(db, user, f"guideline_finding.{status}", "guideline_finding", finding.id, finding.claim_id, after={"reason": reason})
    return finding


# ---- classification / documents (HITL-1, PW-2.1 corrections) -------------------------------------------

def reclassify(db: Session, doc: Document, user: Principal, doc_type: str, tags: dict | None, reason: str) -> DocumentClassification:
    from app.agents.taxonomy import DOC_TYPES

    if doc_type not in DOC_TYPES:
        raise BadRequest(f"Unknown document type {doc_type}")
    if not reason:
        raise BadRequest("A reason is required")
    cur = db.execute(select(DocumentClassification).where(DocumentClassification.document_id == doc.id,
                                                          DocumentClassification.is_current.is_(True))).scalar_one_or_none()
    if cur:
        cur.is_current = False
    row = DocumentClassification(id=uuid7(), document_id=doc.id, doc_type=doc_type, confidence=1.0,
                                 provider_name=cur.provider_name if cur else None, provider_specialty=cur.provider_specialty if cur else None,
                                 facility=cur.facility if cur else None, service_date_start=(tags or {}).get("service_date_start") or (cur.service_date_start if cur else None),
                                 service_date_end=cur.service_date_end if cur else None, body_parts=cur.body_parts if cur else [],
                                 tags={**(cur.tags if cur else {}), **(tags or {})}, icd10_codes=cur.icd10_codes if cur else [],
                                 cpt_codes=cur.cpt_codes if cur else [], rationale="Human classification", classified_by=user.id,
                                 reason=reason, version=(cur.version + 1) if cur else 1, is_current=True)
    db.add(row)
    doc.stream = stream_for(doc_type)
    if doc.status == "noise" and doc_type != "Administrative/Fax Cover":
        doc.status, doc.status_reason = "processed", "restored by reviewer"
    _audit(db, user, "document.reclassify", "document", doc.id, doc.claim_id,
           before={"doc_type": cur.doc_type if cur else None}, after={"doc_type": doc_type, "reason": reason})
    return row


def split_document(db: Session, doc: Document, user: Principal, page_ranges: list[list[int]], reason: str | None) -> list[Document]:
    pages = db.execute(select(Page).where(Page.document_id == doc.id).order_by(Page.page_number)).scalars().all()
    n = len(pages)
    covered = sorted(p for a, b in page_ranges for p in range(a, b + 1))
    if not page_ranges or covered != list(range(1, n + 1)):
        raise BadRequest(f"page_ranges must cover pages 1..{n} exactly once")
    children = []
    for a, b in page_ranges:
        child = Document(id=uuid7(), claim_id=doc.claim_id, source_channel=doc.source_channel,
                         original_filename=f"{doc.title or doc.original_filename} [pp. {a}-{b}]", mime_type=doc.mime_type,
                         storage_path=doc.storage_path, parent_document_id=doc.id, page_start=a, page_end=b,
                         page_count=b - a + 1, status="processed", title=f"{doc.title or 'Document'} (pp. {a}-{b})",
                         received_at=doc.received_at, uploaded_by=user.id, stream=doc.stream)
        db.add(child)
        for i, p in enumerate(pages[a - 1:b], 1):
            p.document_id, p.page_number = child.id, i
        children.append(child)
    doc.status, doc.is_container, doc.status_reason = "split", True, f"split by reviewer: {reason or ''}"
    _audit(db, user, "document.split", "document", doc.id, doc.claim_id, after={"page_ranges": page_ranges, "children": [c.id for c in children]})
    return children


# ---- timeline (HITL-1) ----------------------------------------------------------------------------------

def update_episode(db: Session, ep: Episode, user: Principal, label: str | None = None, merge_into: str | None = None,
                   move_document_ids: list[str] | None = None, new_label_for_moved: str | None = None) -> Episode:
    before = {"label": ep.label}
    if label:
        ep.label, ep.edited_by = label, user.id
    if merge_into:
        target = db.get(Episode, merge_into)
        if target is None or target.claim_id != ep.claim_id or target.timeline_version != ep.timeline_version:
            raise BadRequest("Merge target must be an episode of the same timeline version")
        for idx in db.execute(select(DocumentIndex).where(DocumentIndex.episode_id == ep.id)).scalars():
            idx.episode_id = target.id
        target.start_date = min(filter(None, [target.start_date, ep.start_date]), default=None)
        target.end_date = max(filter(None, [target.end_date, ep.end_date]), default=None)
        db.delete(ep)
        _audit(db, user, "episode.merge", "episode", ep.id, ep.claim_id, after={"into": target.id})
        return target
    if move_document_ids:  # split: move documents into a new episode
        new = Episode(id=uuid7(), claim_id=ep.claim_id, label=new_label_for_moved or f"{ep.label} (split)",
                      episode_type=ep.episode_type, timeline_version=ep.timeline_version, sort_order=ep.sort_order + 1, edited_by=user.id)
        db.add(new)
        for idx in db.execute(select(DocumentIndex).where(DocumentIndex.episode_id == ep.id,
                                                          DocumentIndex.document_id.in_(move_document_ids))).scalars():
            idx.episode_id = new.id
        _audit(db, user, "episode.split", "episode", ep.id, ep.claim_id, after={"new_episode": new.id, "documents": move_document_ids})
    _audit(db, user, "episode.update", "episode", ep.id, ep.claim_id, before=before, after={"label": ep.label})
    return ep


def update_gap(db: Session, gap: TimelineGap, user: Principal, status: str, note: str | None) -> TimelineGap:
    if status not in ("open", "explained", "requested", "resolved"):
        raise BadRequest("invalid gap status")
    if status in ("explained", "resolved") and not note:
        raise BadRequest("A resolution note is required")
    before = {"status": gap.status}
    gap.status, gap.resolution_note = status, note
    flag = db.execute(select(Flag).where(Flag.ref_type == "timeline_gap", Flag.ref_id == gap.id)).scalar_one_or_none()
    if flag and flag.human_action is None and status in ("explained", "resolved"):
        flag.human_action, flag.acted_by, flag.acted_at, flag.reason = "approved", user.id, now_iso(), note
    _audit(db, user, "gap.update", "timeline_gap", gap.id, gap.claim_id, before=before, after={"status": status, "note": note})
    return gap


# ---- summaries & chronology (HITL-3, PW-6.1) -------------------------------------------------------------

def edit_summary(db: Session, s: Summary, user: Principal, content_md: str, reason: str) -> Summary:
    if s.status == "approved":
        raise Conflict("Approved summaries are locked; regenerate to create a new draft")
    if s.status == "superseded":
        raise Conflict("Edit the current version")
    if not reason:
        raise BadRequest("A reason is required")
    import re

    js = dict(s.content_json or {})
    js["edited_markdown"] = True
    # keep structured sections in sync: rebuild sentences from the edited markdown, preserving citation tokens
    sections, cur = [], None
    for line in content_md.splitlines():
        if line.startswith("### "):
            cur = {"heading": line[4:].strip(), "sentences": []}
            sections.append(cur)
        elif line.strip().startswith("- ") and cur is not None:
            ids = re.findall(r"\[\[cite:([0-9a-f-]{36})\]\]", line)
            text = re.sub(r"\s*\[\[cite:[0-9a-f-]{36}\]\]", "", line.strip()[2:]).strip()
            cur["sentences"].append({"text": text, "citation_ids": ids, "evidence_type": "mixed"})
    if sections:
        js["sections"] = sections
    new = Summary(id=uuid7(), claim_id=s.claim_id, summary_type=s.summary_type, content_md=content_md, content_json=js,
                  status="in_review" if s.status == "in_review" else "draft", generated_by_run_id=s.generated_by_run_id,
                  author_type="user", edited_by=user.id, edit_reason=reason, version=s.version + 1, supersedes_id=s.id,
                  word_count=sum(len(x["text"].split()) for sec in sections for x in sec["sentences"]) or None)
    db.add(new)
    s.status = "superseded"
    _audit(db, user, "summary.edit", "summary", s.id, s.claim_id, after={"new_version": new.id, "reason": reason})
    return new


def edit_chronology_event(db: Session, ev: ChronologyEvent, user: Principal, changes: dict) -> ChronologyEvent:
    if not ev.is_current:
        raise Conflict("Edit the current version of the event")
    allowed = {"description", "key_findings", "work_status", "provider", "event_date", "event_type"}
    bad = set(changes) - allowed - {"reason"}
    if bad:
        raise BadRequest(f"Fields not editable: {sorted(bad)}")
    new = ChronologyEvent(**{c.key: getattr(ev, c.key) for c in ChronologyEvent.__table__.columns if c.key not in ("id", "created_at", "updated_at", "version")})
    new.id = uuid7()
    for k, v in changes.items():
        if k in allowed:
            setattr(new, k, v)
    new.edited_by, new.supersedes_id, new.version = user.id, ev.id, ev.version + 1
    ev.is_current = False
    db.add(new)
    _audit(db, user, "chronology.edit", "chronology_event", ev.id, ev.claim_id, after={**changes, "new_id": new.id})
    return new


def require_claim_member(user: Principal, claim_id: str, allowed: bool) -> None:
    if not allowed:
        raise Forbidden("You do not have access to this claim")


def get_or_404(db: Session, model, id_: str):
    obj = db.get(model, id_)
    if obj is None:
        raise NotFound(f"{model.__name__} not found")
    return obj
