"""HITL reviews, flags, decisions, UR determinations, notifications (spec §12.8)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, envelope, get_db, require_permission
from app.api.v1.claims import clinical_access
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.ids import now_iso
from app.core.rbac import CHECKPOINT_ROLES
from app.models import Claim, Decision, Flag, Notification, Review, URDetermination, User
from app.services import audit
from app.services.actions import Principal, act_on_flag
from app.services.claims import get_claim_for, scoped_claims
from app.services.reviews import URIn, can_act, claim_review, reassign, record_ur, submit

router = APIRouter(tags=["reviews"])


def review_dict(r: Review, claim: Claim | None, names: dict, include_payload: bool = False) -> dict:
    out = {"id": r.id, "run_id": r.run_id, "claim_id": r.claim_id, "claim_number": claim.claim_number if claim else None,
           "checkpoint": r.checkpoint, "title": r.title, "assigned_role": r.assigned_role, "assigned_user_id": r.assigned_user_id,
           "assigned_user_name": names.get(r.assigned_user_id), "status": r.status, "priority": r.priority, "due_at": r.due_at,
           "claimed_by": r.claimed_by, "claimed_by_name": names.get(r.claimed_by), "submitted_by_name": names.get(r.submitted_by),
           "submitted_at": r.submitted_at, "escalated": r.escalated, "blocks_run": r.blocks_run, "created_at": r.created_at,
           "risk_score": claim.risk_score if claim else None, "complexity": claim.complexity if claim else None}
    if include_payload:
        out["payload"], out["response"] = r.payload, r.response
    return out


@router.get("/reviews")
def queue(status: str | None = "open", checkpoint: str | None = None, assigned_to: str | None = None, claim_id: str | None = None,
          db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    """Work queue: reviews the user's roles can act on, urgent / SLA-due first (spec §13.3 'urgency surfaces first')."""
    checkpoints = [cp for cp, roles in CHECKPOINT_ROLES.items() if roles & set(user.roles)]
    if "claims_supervisor" in user.roles:
        checkpoints = list(CHECKPOINT_ROLES)
    claims = {c.id: c for c in db.execute(scoped_claims(db, user)).scalars()}
    q = select(Review).where(Review.checkpoint.in_(checkpoints), Review.claim_id.in_(list(claims)))
    if status == "open":
        q = q.where(Review.status.in_(["pending", "in_progress"]))
    elif status:
        q = q.where(Review.status == status)
    if checkpoint:
        q = q.where(Review.checkpoint == checkpoint)
    if claim_id:
        q = q.where(Review.claim_id == claim_id)
    if assigned_to == "me":
        q = q.where(or_(Review.assigned_user_id == user.id, Review.assigned_user_id.is_(None)))
    rows = db.execute(q.order_by(Review.priority, Review.due_at)).scalars().all()
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    return envelope([review_dict(r, claims.get(r.claim_id), names) for r in rows])


def _review_for(db: Session, user: Principal, review_id: str) -> Review:
    r = db.get(Review, review_id)
    if r is None:
        raise NotFound("Review not found")
    get_claim_for(db, user, r.claim_id)
    return r


@router.get("/reviews/{review_id}")
def get_review(review_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    r = _review_for(db, user, review_id)
    if not can_act(r, user) and "claims_supervisor" not in user.roles:
        raise Forbidden("Your role cannot open this checkpoint")
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    audit.record(db, action="phi.view", entity_type="review", entity_id=r.id, claim_id=r.claim_id, actor_id=user.id)
    return envelope({**review_dict(r, db.get(Claim, r.claim_id), names, include_payload=True), "can_act": can_act(r, user)})


@router.post("/reviews/{review_id}/claim")
def claim_it(review_id: str, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    r = _review_for(db, user, review_id)
    claim_review(db, r, user)
    return envelope({"id": r.id, "status": r.status, "claimed_by": r.claimed_by})


@router.post("/reviews/{review_id}/release")
def release(review_id: str, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    r = _review_for(db, user, review_id)
    if r.claimed_by != user.id and "claims_supervisor" not in user.roles:
        raise Forbidden("Only the user holding the review can release it")
    r.claimed_by, r.status = None, "pending"
    audit.record(db, action="review.release", entity_type="review", entity_id=r.id, claim_id=r.claim_id, actor_id=user.id)
    return envelope({"id": r.id, "status": r.status})


@router.post("/reviews/{review_id}/submit", status_code=202)
def submit_review(review_id: str, body: dict, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    r = _review_for(db, user, review_id)
    submit(db, r, user, body)
    return envelope({"id": r.id, "status": r.status, "resumed": r.blocks_run})


class ReassignIn(BaseModel):
    user_id: str
    reason: str = Field(min_length=3)


@router.post("/reviews/{review_id}/reassign")
def reassign_review(review_id: str, body: ReassignIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("run:manage"))):
    r = db.get(Review, review_id)
    if r is None:
        raise NotFound("Review not found")
    reassign(db, r, user, body.user_id, body.reason)
    return envelope({"id": r.id, "assigned_user_id": r.assigned_user_id})


# ---- flags (one-click approvals) ---------------------------------------------------------------------

@router.get("/claims/{claim_id}/flags")
def flags(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    order = {"high": 0, "medium": 1, "low": 2}
    rows = db.execute(select(Flag).where(Flag.claim_id == claim.id)).scalars().all()
    return envelope(sorted([{**f.to_dict(exclude={"item_key"}), "acted_by_name": names.get(f.acted_by)} for f in rows],
                           key=lambda f: (f["human_action"] is not None, order.get(f["severity"], 3))))


class FlagActionIn(BaseModel):
    action: str = Field(pattern="^(approve|reject|modify)$")
    value: str | None = None
    reason: str | None = None


@router.post("/flags/{flag_id}/action")
def flag_action(flag_id: str, body: FlagActionIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("flag:act"))):
    f = db.get(Flag, flag_id)
    if f is None:
        raise NotFound("Flag not found")
    get_claim_for(db, user, f.claim_id)
    return envelope(act_on_flag(db, f, user, body.action, body.reason, body.value).to_dict())


class BulkFlagIn(BaseModel):
    flag_ids: list[str] = Field(min_length=1)
    action: str = Field(pattern="^(approve|reject)$")
    reason: str | None = None


@router.post("/flags/bulk-action")
def bulk(body: BulkFlagIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("decision:make"))):
    out = []
    for fid in body.flag_ids:
        f = db.get(Flag, fid)
        if f is None:
            raise NotFound(f"Flag {fid} not found")
        get_claim_for(db, user, f.claim_id)
        out.append({"id": fid, "human_action": act_on_flag(db, f, user, body.action, body.reason).human_action})
    return envelope(out)


# ---- decisions & UR -------------------------------------------------------------------------------------

@router.get("/claims/{claim_id}/decisions")
def decisions(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    rows = db.execute(select(Decision).where(Decision.claim_id == claim.id).order_by(Decision.created_at)).scalars().all()
    urs = db.execute(select(URDetermination).where(URDetermination.claim_id == claim.id)).scalars().all()
    return envelope({"decisions": [{**d.to_dict(), "decided_by_name": names.get(d.decided_by), "signed_off_by_name": names.get(d.signed_off_by)}
                                   for d in rows],
                     "ur_determinations": [{**u.to_dict(), "reviewer_name": names.get(u.reviewer_id)} for u in urs]})


@router.post("/claims/{claim_id}/ur-determinations", status_code=201)
def ur(body: URIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db), user: Principal = Depends(require_permission("ur:determine"))):
    row = record_ur(db, claim, user, body)
    # if every request is now determined, complete the pending UR review (resumes the run if it is waiting on it)
    from app.models import UtilizationAssessment
    pending = db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == claim.id,
                                                             UtilizationAssessment.status == "ai_draft")).first()
    if not pending:
        review = db.execute(select(Review).where(Review.claim_id == claim.id, Review.checkpoint == "HITL-4-UR",
                                                 Review.status.in_(["pending", "in_progress"]))).scalars().first()
        if review:
            review.status, review.submitted_by, review.submitted_at = "submitted", user.id, now_iso()
            review.response = {"determinations": [row.id], "via": "ur-determinations endpoint"}
            from app.models import AgentRun
            from app.services import runs
            run = db.get(AgentRun, review.run_id)
            if review.blocks_run and run and run.pending_review_id == review.id and run.status == "awaiting_human":
                runs.resume(db, run, review.response)
    return envelope(row.to_dict())


class SignoffIn(BaseModel):
    approved: bool
    comments: str = Field(min_length=3)


@router.post("/decisions/{decision_id}/signoff")
def signoff(decision_id: str, body: SignoffIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("decision:signoff"))):
    d = db.get(Decision, decision_id)
    if d is None:
        raise NotFound("Decision not found")
    get_claim_for(db, user, d.claim_id)
    review = db.execute(select(Review).where(Review.claim_id == d.claim_id, Review.checkpoint == "HITL-5",
                                             Review.status.in_(["pending", "in_progress"]))).scalars().first()
    if review is None:
        raise Conflict("No pending supervisor sign-off for this claim")
    submit(db, review, user, {"action": "signoff" if body.approved else "return", "comments": body.comments})
    return envelope({"review_id": review.id, "status": review.status})


# ---- notifications -------------------------------------------------------------------------------------

@router.get("/notifications")
def notifications(unread_only: bool = False, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(Notification.created_at.desc()).limit(100)).scalars().all()
    unread = sum(1 for n in rows if n.read_at is None)
    return envelope([n.to_dict() for n in rows], unread=unread)


@router.post("/notifications/read")
def mark_read(ids: list[str] | None = None, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    q = select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        q = q.where(Notification.id.in_(ids))
    n = 0
    for row in db.execute(q).scalars():
        row.read_at = now_iso()
        n += 1
    return envelope({"marked": n})


