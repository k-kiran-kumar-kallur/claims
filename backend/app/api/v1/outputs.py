"""Chronology, summaries and reports (spec §12.7)."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import claim_access, envelope, get_db, require_permission
from app.api.v1.claims import clinical_access
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.ids import uuid7
from app.models import ChronologyEvent, Claim, Report, Review, Summary, User
from app.repositories.docs import citation_dict, citations_for
from app.services import audit, file_store
from app.services.actions import Principal, edit_chronology_event, edit_summary
from app.services.claims import get_claim_for, scoped_claims
from app.services.report_service import FORMATS, REPORT_TYPES
from app.services.runs import enqueue

router = APIRouter(tags=["outputs"])
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "json": "application/json", "html": "text/html"}


@router.get("/claims/{claim_id}/chronology")
def chronology(version: int | None = None, claim: Claim = Depends(claim_access), db: Session = Depends(get_db),
               user: Principal = Depends(require_permission("document:view_phi"))):
    """Attorneys may read the chronology once approved reports exist (claim scoping enforces that)."""
    q = select(ChronologyEvent).where(ChronologyEvent.claim_id == claim.id)
    q = q.where(ChronologyEvent.chronology_version == version) if version else q.where(ChronologyEvent.is_current.is_(True))
    rows = db.execute(q.order_by(ChronologyEvent.sort_order)).scalars().all()
    versions = sorted(set(db.execute(select(ChronologyEvent.chronology_version).where(ChronologyEvent.claim_id == claim.id)).scalars()))
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    audit.record(db, action="phi.view", entity_type="chronology", entity_id=claim.id, claim_id=claim.id, actor_id=user.id)
    return envelope([{**e.to_dict(), "edited_by_name": names.get(e.edited_by)} for e in rows], versions=versions)


class ChronologyPatch(BaseModel):
    description: str | None = None
    key_findings: str | None = None
    work_status: str | None = None
    provider: str | None = None
    event_date: str | None = None
    event_type: str | None = None
    reason: str = Field(min_length=3)


@router.patch("/chronology-events/{event_id}")
def patch_event(event_id: str, body: ChronologyPatch, db: Session = Depends(get_db),
                user: Principal = Depends(require_permission("chronology:edit"))):
    ev = db.get(ChronologyEvent, event_id)
    if ev is None:
        raise NotFound("Event not found")
    get_claim_for(db, user, ev.claim_id)
    out = edit_chronology_event(db, ev, user, body.model_dump(exclude_unset=True, exclude={"reason"}) | {"reason": body.reason})
    return envelope(out.to_dict())


def summary_dict(db: Session, s: Summary) -> dict:
    cites = citations_for(db, "summary", [s.id])
    names = {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_([x for x in (s.edited_by, s.approved_by) if x]))).scalars()}
    cite_map = {c.id: citation_dict(c) for c in cites.get(s.id, [])}
    if s.supersedes_id:  # edited versions keep the citations of earlier versions
        prev, seen = s.supersedes_id, set()
        while prev and prev not in seen:
            seen.add(prev)
            for c in citations_for(db, "summary", [prev]).get(prev, []):
                cite_map.setdefault(c.id, citation_dict(c))
            row = db.get(Summary, prev)
            prev = row.supersedes_id if row else None
    return {**s.to_dict(), "citations": cite_map, "edited_by_name": names.get(s.edited_by), "approved_by_name": names.get(s.approved_by),
            "label": None if s.status == "approved" else "AI draft - pending human review"}


@router.get("/claims/{claim_id}/summaries")
def summaries(type: str | None = None, status: str | None = None, include_history: bool = False,
              claim: Claim = Depends(clinical_access), db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    q = select(Summary).where(Summary.claim_id == claim.id)
    if type:
        q = q.where(Summary.summary_type == type)
    if status:
        q = q.where(Summary.status == status)
    elif not include_history:
        q = q.where(Summary.status != "superseded")
    rows = db.execute(q.order_by(Summary.summary_type, Summary.version.desc())).scalars().all()
    audit.record(db, action="phi.view", entity_type="summary", entity_id=claim.id, claim_id=claim.id, actor_id=user.id)
    return envelope([summary_dict(db, s) for s in rows])


@router.get("/summaries/{summary_id}")
def get_summary(summary_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    s = db.get(Summary, summary_id)
    if s is None:
        raise NotFound("Summary not found")
    if set(user.roles) == {"attorney"} and s.status != "approved":
        raise Forbidden("Only approved content is available")
    get_claim_for(db, user, s.claim_id)
    history = db.execute(select(Summary).where(Summary.claim_id == s.claim_id, Summary.summary_type == s.summary_type)
                         .order_by(Summary.version)).scalars().all()
    return envelope({**summary_dict(db, s), "history": [{"id": h.id, "version": h.version, "status": h.status, "author_type": h.author_type,
                                                         "created_at": h.created_at, "content_md": h.content_md} for h in history]})


class SummaryPut(BaseModel):
    content_md: str = Field(min_length=10)
    reason: str = Field(min_length=3)


@router.put("/summaries/{summary_id}")
def put_summary(summary_id: str, body: SummaryPut, db: Session = Depends(get_db), user: Principal = Depends(require_permission("summary:edit"))):
    s = db.get(Summary, summary_id)
    if s is None:
        raise NotFound("Summary not found")
    get_claim_for(db, user, s.claim_id)
    new = edit_summary(db, s, user, body.content_md, body.reason)
    db.flush()
    return envelope(summary_dict(db, new))


class RegenerateIn(BaseModel):
    instructions: str = Field(min_length=5)


@router.post("/summaries/{summary_id}/regenerate", status_code=202)
def regenerate(summary_id: str, body: RegenerateIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("summary:approve"))):
    """Regeneration runs through the HITL-3 loop of the active run (report_agent re-invoked with the instructions)."""
    s = db.get(Summary, summary_id)
    if s is None:
        raise NotFound("Summary not found")
    get_claim_for(db, user, s.claim_id)
    review = db.execute(select(Review).where(Review.claim_id == s.claim_id, Review.checkpoint == "HITL-3",
                                             Review.status.in_(["pending", "in_progress"]))).scalars().first()
    if review is None:
        raise Conflict("Regeneration is available while the summary is in HITL-3 review")
    from app.services.reviews import submit
    submit(db, review, user, {"action": "revise", "regenerate_instructions": body.instructions})
    return envelope({"review_id": review.id, "status": "regenerating"})


# ---- reports --------------------------------------------------------------------------------------------

class ReportIn(BaseModel):
    report_type: str
    format: str = "pdf"
    approved_only: bool = False


def report_dict(r: Report) -> dict:
    return {k: v for k, v in r.to_dict().items() if k != "file_path"} | {"available": bool(r.file_path)}


@router.post("/claims/{claim_id}/reports", status_code=202)
def create_report(body: ReportIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                  user: Principal = Depends(require_permission("report:export"))):
    if body.report_type not in REPORT_TYPES or body.format not in FORMATS:
        raise BadRequest(f"report_type must be one of {REPORT_TYPES}; format one of {FORMATS}")
    rep = Report(id=uuid7(), claim_id=claim.id, report_type=body.report_type, format=body.format, status="queued",
                 is_approved_content=body.approved_only, requested_by=user.id)
    db.add(rep)
    enqueue(db, "export_report", {"report_id": rep.id})
    audit.record(db, action="report.request", entity_type="report", entity_id=rep.id, claim_id=claim.id, actor_id=user.id,
                 after=body.model_dump())
    return envelope({"report_id": rep.id, "status": rep.status})


@router.get("/claims/{claim_id}/reports")
def claim_reports(claim: Claim = Depends(claim_access), db: Session = Depends(get_db), user: Principal = Depends(require_permission("report:export"))):
    q = select(Report).where(Report.claim_id == claim.id)
    if set(user.roles) == {"attorney"}:
        q = q.where(Report.is_approved_content.is_(True), Report.status == "approved")
    return envelope([report_dict(r) for r in db.execute(q.order_by(Report.created_at.desc())).scalars()])


@router.get("/reports")
def approved_reports(db: Session = Depends(get_db), user: Principal = Depends(require_permission("report:export"))):
    """Approved Reports (attorney read-only view and general export list)."""
    claims = {c.id: c for c in db.execute(scoped_claims(db, user)).scalars()}
    rows = db.execute(select(Report).where(Report.claim_id.in_(list(claims)), Report.is_approved_content.is_(True),
                                           Report.status == "approved").order_by(Report.created_at.desc())).scalars().all()
    return envelope([report_dict(r) | {"claim_number": claims[r.claim_id].claim_number} for r in rows])


@router.get("/reports/{report_id}")
def report_status(report_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("report:export"))):
    r = db.get(Report, report_id)
    if r is None:
        raise NotFound("Report not found")
    get_claim_for(db, user, r.claim_id)
    return envelope(report_dict(r))


@router.get("/reports/{report_id}/download")
def download(report_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("report:export"))):
    r = db.get(Report, report_id)
    if r is None:
        raise NotFound("Report not found")
    claim = get_claim_for(db, user, r.claim_id)
    if set(user.roles) == {"attorney"} and not (r.is_approved_content and r.status == "approved"):
        raise Forbidden("Only approved reports can be downloaded")
    if not r.file_path or r.status not in ("ready", "approved"):
        raise Conflict(f"Report is {r.status}" + (f": {r.error}" if r.error else ""))
    data = file_store.get(r.file_path)
    audit.record(db, action="report.export", entity_type="report", entity_id=r.id, claim_id=r.claim_id, actor_id=user.id,
                 after={"type": r.report_type, "format": r.format, "sha256": r.sha256})
    name = f"{claim.claim_number}_{r.report_type}_v{r.version}.{r.format}"
    return StreamingResponse(io.BytesIO(data), media_type=MIME.get(r.format, "application/octet-stream"),
                             headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


