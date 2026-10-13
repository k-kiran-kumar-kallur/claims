"""Claims, review context, dashboard, document requests, follow-ups, membership (spec §12.2, §12.3, §12.8)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Paging, claim_access, current_user, envelope, get_db, require_permission
from app.core.errors import Forbidden, NotFound
from app.core.ids import uuid7
from app.models import (
    AgentRun,
    Claim,
    ClaimMember,
    DocumentRequest,
    Flag,
    FollowUp,
    GuidelineFinding,
    Milestone,
    Review,
    ReviewContext,
    RtwStatus,
    Summary,
    TimelineGap,
    User,
)
from app.services import audit
from app.services.actions import Principal
from app.services.claims import claimant_view, create_claim, get_claim_for, scoped_claims
from app.services.reviews import follow_up

router = APIRouter(tags=["claims"])


def clinical_access(claim_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))) -> Claim:
    """PHI detail access: attorneys only see approved reports and the chronology (spec §3.2)."""
    if set(user.roles) == {"attorney"}:
        raise Forbidden("Defence counsel can access approved reports and the chronology only")
    return get_claim_for(db, user, claim_id)


class ClaimantIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    dob: str | None = None
    ssn_last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    contact: str | None = None


class ClaimIn(BaseModel):
    claim_number: str
    claimant: ClaimantIn
    employer_name: str | None = None
    employer_contact: str | None = None
    insurer: str | None = None
    tpa: str | None = None
    date_of_injury: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    jurisdiction_state: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    body_parts: list[str] = []
    mechanism_of_injury: str | None = None
    assigned_adjuster_id: str | None = None
    assigned_ncm_id: str | None = None
    assigned_reviewer_id: str | None = None
    assigned_supervisor_id: str | None = None
    adjuster_name: str | None = None
    litigated: bool = False


class ClaimPatch(BaseModel):
    employer_name: str | None = None
    employer_contact: str | None = None
    insurer: str | None = None
    tpa: str | None = None
    date_of_injury: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    jurisdiction_state: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    body_parts: list[str] | None = None
    mechanism_of_injury: str | None = None
    assigned_adjuster_id: str | None = None
    assigned_ncm_id: str | None = None
    assigned_reviewer_id: str | None = None
    assigned_supervisor_id: str | None = None
    litigated: bool | None = None
    status: str | None = Field(default=None, pattern="^(open|in_review|decided|closed)$")
    legal_hold: bool | None = None


def _names(db: Session) -> dict[str, str]:
    return {u.id: u.full_name for u in db.execute(select(User)).scalars()}


def claim_dict(db: Session, c: Claim, names: dict | None = None, detail: bool = False) -> dict:
    names = names or _names(db)
    run = db.execute(select(AgentRun).where(AgentRun.claim_id == c.id).order_by(AgentRun.created_at.desc()).limit(1)).scalar_one_or_none()
    pending = db.execute(select(func.count(Review.id)).where(Review.claim_id == c.id, Review.status.in_(["pending", "in_progress"]))).scalar()
    out = {"id": c.id, "claim_number": c.claim_number, "claimant": claimant_view(db, c)["full_name"], "employer_name": c.employer_name,
           "insurer": c.insurer, "tpa": c.tpa, "date_of_injury": c.date_of_injury, "jurisdiction_state": c.jurisdiction_state,
           "body_parts": c.body_parts, "status": c.status, "risk_score": c.risk_score, "complexity": c.complexity,
           "current_stage": c.current_stage, "baseline_locked": c.baseline_locked, "litigated": c.litigated,
           "is_synthetic": c.is_synthetic, "pending_reviews": pending, "adjuster_name": c.adjuster_name,
           "assigned": {k: {"id": getattr(c, f"assigned_{k}_id"), "name": names.get(getattr(c, f"assigned_{k}_id"))}
                        for k in ("adjuster", "ncm", "reviewer", "supervisor")},
           "latest_run": {"id": run.id, "status": run.status, "current_stage": run.current_stage, "current_node": run.current_node,
                          "stage_status": run.stage_status, "pending_review_id": run.pending_review_id} if run else None,
           "created_at": c.created_at, "updated_at": c.updated_at}
    if detail:
        rc = db.execute(select(ReviewContext).where(ReviewContext.claim_id == c.id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
        out.update({"claimant_detail": claimant_view(db, c), "employer_contact": c.employer_contact,
                    "mechanism_of_injury": c.mechanism_of_injury, "baseline": c.baseline,
                    "time_window": {"start": c.time_window_start, "end": c.time_window_end}, "legal_hold": c.legal_hold,
                    "review_context": rc.to_dict() if rc else None})
    return out


@router.post("/claims", status_code=201)
def create(body: ClaimIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("claim:create"))):
    claim = create_claim(db, user, body.model_dump())
    return envelope(claim_dict(db, claim, detail=True))


@router.get("/claims")
def list_claims(paging: Paging = Depends(), status: str | None = None, assigned_to: str | None = None, risk_min: float | None = None,
                complexity: str | None = None, q: str | None = None, db: Session = Depends(get_db),
                user: Principal = Depends(require_permission("document:view_phi"))):
    stmt = scoped_claims(db, user)
    if status:
        stmt = stmt.where(Claim.status == status)
    if complexity:
        stmt = stmt.where(Claim.complexity == complexity)
    if risk_min is not None:
        stmt = stmt.where(Claim.risk_score >= risk_min)
    if assigned_to:
        uid = user.id if assigned_to == "me" else assigned_to
        stmt = stmt.where(or_(Claim.assigned_adjuster_id == uid, Claim.assigned_ncm_id == uid, Claim.assigned_reviewer_id == uid,
                              Claim.assigned_supervisor_id == uid))
    if q:
        stmt = stmt.where(or_(Claim.claim_number.ilike(f"%{q}%"), Claim.employer_name.ilike(f"%{q}%")))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(Claim.risk_score.desc().nulls_last(), Claim.created_at.desc())
                      .offset(paging.offset).limit(paging.page_size)).scalars().all()
    names = _names(db)
    return envelope([claim_dict(db, c, names) for c in rows], page=paging.page, page_size=paging.page_size, total=total)


@router.get("/claims/{claim_id}")
def get_claim(claim: Claim = Depends(claim_access), db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    audit.record(db, action="phi.view", entity_type="claim", entity_id=claim.id, claim_id=claim.id, actor_id=user.id, ip=user.ip)
    return envelope(claim_dict(db, claim, detail=set(user.roles) != {"attorney"}))


@router.patch("/claims/{claim_id}")
def patch_claim(body: ClaimPatch, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                user: Principal = Depends(require_permission("decision:make", "baseline:confirm"))):
    data = body.model_dump(exclude_unset=True)
    baseline_fields = {"employer_name", "insurer", "tpa", "date_of_injury", "jurisdiction_state", "body_parts", "mechanism_of_injury"}
    if claim.baseline_locked and baseline_fields & set(data) and "claims_supervisor" not in user.roles:
        raise Forbidden("Baseline is locked; only a supervisor can change baseline fields")
    if "legal_hold" in data and "claims_supervisor" not in user.roles:
        raise Forbidden("Only a supervisor can set a legal hold")
    before = {k: getattr(claim, k) for k in data}
    for k, v in data.items():
        setattr(claim, k, v.upper() if k == "jurisdiction_state" and v else v)
    audit.record(db, action="claim.update", entity_type="claim", entity_id=claim.id, claim_id=claim.id, actor_id=user.id,
                 before=before, after=data, ip=user.ip)
    return envelope(claim_dict(db, claim, detail=True))


class ReviewContextIn(BaseModel):
    review_goals: list[str] = Field(min_length=1)
    clinical_question: str = Field(min_length=10)
    required_evidence: list[str] = []
    applicable_guidelines: list[str] = []
    state_rules: list[str] = []


@router.get("/claims/{claim_id}/review-context")
def get_review_context(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rc = db.execute(select(ReviewContext).where(ReviewContext.claim_id == claim.id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
    return envelope(rc.to_dict() if rc else None)


@router.put("/claims/{claim_id}/review-context")
def put_review_context(body: ReviewContextIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                       user: Principal = Depends(require_permission("baseline:confirm", "decision:make"))):
    for rc in db.execute(select(ReviewContext).where(ReviewContext.claim_id == claim.id, ReviewContext.is_current.is_(True))).scalars():
        rc.is_current = False
    row = ReviewContext(id=uuid7(), claim_id=claim.id, source="user", created_by=user.id, approved_by=user.id, is_current=True,
                        **body.model_dump())
    db.add(row)
    audit.record(db, action="review_context.update", entity_type="review_context", entity_id=row.id, claim_id=claim.id,
                 actor_id=user.id, after=body.model_dump())
    return envelope(row.to_dict())


@router.get("/claims/{claim_id}/dashboard")
def dashboard(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    """One-page first (POC-OUT): summary, milestones, flags, gaps, RTW status, exposure indicators."""
    one = db.execute(select(Summary).where(Summary.claim_id == claim.id, Summary.summary_type == "one_page", Summary.status != "superseded")
                     .order_by(Summary.created_at.desc()).limit(1)).scalar_one_or_none()
    milestones = db.execute(select(Milestone).where(Milestone.claim_id == claim.id, Milestone.status != "superseded")
                            .order_by(Milestone.milestone_date)).scalars().all()
    flags = db.execute(select(Flag).where(Flag.claim_id == claim.id)).scalars().all()
    gaps = db.execute(select(TimelineGap).where(TimelineGap.claim_id == claim.id)).scalars().all()
    rtw = db.execute(select(RtwStatus).where(RtwStatus.claim_id == claim.id).order_by(RtwStatus.effective_date)).scalars().all()
    findings = db.execute(select(GuidelineFinding).where(GuidelineFinding.claim_id == claim.id,
                                                         GuidelineFinding.finding_type.notin_(["compliant", "no_applicable_guideline"]))).scalars().all()
    from app.services.report_builder import cited_sections
    ttd_days = None
    if claim.date_of_injury:
        first_rtw = next((r.effective_date for r in rtw if r.work_status in ("modified_duty", "full_duty") and r.effective_date), None)
        ttd_days = (date.fromisoformat(first_rtw or date.today().isoformat()) - date.fromisoformat(claim.date_of_injury)).days
    routing = (claim.baseline or {}).get("routing") or {}
    audit.record(db, action="phi.view", entity_type="dashboard", entity_id=claim.id, claim_id=claim.id, actor_id=user.id, ip=user.ip)
    one_page = None
    if one:
        sections, table = cited_sections(db, one)
        one_page = {"id": one.id, "status": one.status, "version": one.version, "content_md": one.content_md,
                    "sections": one.content_json.get("sections", []), "rendered": sections, "evidence": table["rows"],
                    "word_count": one.word_count, "approved_at": one.approved_at}
    order = {"high": 0, "medium": 1, "low": 2}
    return envelope({
        "claim": claim_dict(db, claim, detail=True), "one_page_summary": one_page,
        "milestones": [m.to_dict() for m in milestones],
        "flags": sorted([f.to_dict() for f in flags], key=lambda f: (f["human_action"] is not None, order.get(f["severity"], 3))),
        "gaps": [g.to_dict() for g in gaps], "rtw_status": [r.to_dict() for r in rtw],
        "exposure": {"risk_score": claim.risk_score, "complexity": claim.complexity, "risk_factors": routing.get("factors", []),
                     "routing_rationale": routing.get("rationale"), "ttd_days": ttd_days, "open_guideline_deviations": len(findings),
                     "litigated": claim.litigated, "open_gaps": len([g for g in gaps if g.status == "open"])},
    })


class MemberIn(BaseModel):
    user_id: str
    role_key: str


@router.get("/claims/{claim_id}/members")
def members(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(ClaimMember, User).join(User, User.id == ClaimMember.user_id).where(ClaimMember.claim_id == claim.id)).all()
    return envelope([{"user_id": u.id, "full_name": u.full_name, "role_key": m.role_key} for m, u in rows])


@router.post("/claims/{claim_id}/members", status_code=201)
def add_member(body: MemberIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
               user: Principal = Depends(require_permission("decision:signoff"))):
    if db.get(User, body.user_id) is None:
        raise NotFound("User not found")
    if db.get(ClaimMember, (claim.id, body.user_id)) is None:
        db.add(ClaimMember(claim_id=claim.id, user_id=body.user_id, role_key=body.role_key, granted_by=user.id))
    audit.record(db, action="claim.member_add", entity_type="claim", entity_id=claim.id, claim_id=claim.id, actor_id=user.id,
                 after=body.model_dump())
    return envelope(body.model_dump())


# ---- document requests (PW-1.2 proactive document chasing) -------------------------------------------

class DocRequestIn(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    requested_from: str | None = None
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str | None = None


class DocRequestPatch(BaseModel):
    status: str = Field(pattern="^(open|sent|received|cancelled)$")
    requested_from: str | None = None
    due_date: str | None = None


@router.get("/claims/{claim_id}/document-requests")
def list_requests(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == claim.id).order_by(DocumentRequest.created_at)).scalars()
    return envelope([r.to_dict() for r in rows])


@router.post("/claims/{claim_id}/document-requests", status_code=201)
def create_request(body: DocRequestIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                   user: Principal = Depends(require_permission("care:coordinate", "document:upload"))):
    row = DocumentRequest(id=uuid7(), claim_id=claim.id, description=body.description, reason=body.reason or "Requested by user",
                          requested_from=body.requested_from, due_date=body.due_date, source="user", created_by=user.id)
    db.add(row)
    audit.record(db, action="document_request.create", entity_type="document_request", entity_id=row.id, claim_id=claim.id,
                 actor_id=user.id, after=body.model_dump())
    return envelope(row.to_dict())


@router.patch("/document-requests/{request_id}")
def patch_request(request_id: str, body: DocRequestPatch, db: Session = Depends(get_db),
                  user: Principal = Depends(require_permission("care:coordinate", "document:upload"))):
    row = db.get(DocumentRequest, request_id)
    if row is None:
        raise NotFound("Request not found")
    get_claim_for(db, user, row.claim_id)
    before = row.status
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    audit.record(db, action="document_request.update", entity_type="document_request", entity_id=row.id, claim_id=row.claim_id,
                 actor_id=user.id, before={"status": before}, after=body.model_dump(exclude_unset=True))
    return envelope(row.to_dict())


# ---- follow-ups (diary) -----------------------------------------------------------------------------

class FollowUpIn(BaseModel):
    action: str = Field(min_length=3)
    owner_id: str | None = None
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class FollowUpPatch(BaseModel):
    status: str = Field(pattern="^(open|done|cancelled)$")


@router.get("/claims/{claim_id}/follow-ups")
def list_follow_ups(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(FollowUp).where(FollowUp.claim_id == claim.id).order_by(FollowUp.due_date)).scalars()
    names = _names(db)
    return envelope([{**f.to_dict(), "owner_name": names.get(f.owner_id)} for f in rows])


@router.post("/claims/{claim_id}/follow-ups", status_code=201)
def create_follow_up(body: FollowUpIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                     user: Principal = Depends(require_permission("decision:make", "care:coordinate"))):
    return envelope(follow_up(db, claim, user, body.action, body.owner_id, body.due_date).to_dict())


@router.patch("/follow-ups/{fid}")
def patch_follow_up(fid: str, body: FollowUpPatch, db: Session = Depends(get_db),
                    user: Principal = Depends(require_permission("decision:make", "care:coordinate"))):
    row = db.get(FollowUp, fid)
    if row is None:
        raise NotFound("Follow-up not found")
    get_claim_for(db, user, row.claim_id)
    row.status = body.status
    audit.record(db, action="follow_up.update", entity_type="follow_up", entity_id=row.id, claim_id=row.claim_id, actor_id=user.id,
                 after=body.model_dump())
    return envelope(row.to_dict())


