"""HITL review service (spec §6.5, §12.8): claim, submit (checkpoint-specific schema), reassign, SLA escalation."""
from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Conflict, Forbidden
from app.core.ids import now_iso, uuid7
from app.core.rbac import CHECKPOINT_ROLES
from app.core.security import encrypt_str
from app.models import (
    AgentRun,
    Claim,
    Claimant,
    Decision,
    Discrepancy,
    Document,
    DocumentRequest,
    ExtractedFact,
    Flag,
    FollowUp,
    Review,
    ReviewContext,
    Summary,
    URDetermination,
    User,
    UtilizationAssessment,
)
from app.services import runs
from app.services.actions import Principal, _audit, act_on_flag

# ---- checkpoint-specific request schemas -----------------------------------------------------------


class DocRequestIn(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    requested_from: str | None = None
    due_date: str | None = None
    reason: str | None = None


class ReviewContextIn(BaseModel):
    review_goals: list[str] = Field(min_length=1)
    clinical_question: str = Field(min_length=10)
    required_evidence: list[str] = []
    applicable_guidelines: list[str] = []
    state_rules: list[str] = []


class Hitl0(BaseModel):
    fields: dict[str, str | list[str] | None] = {}
    time_window_start: str | None = None
    time_window_end: str | None = None
    review_context: ReviewContextIn | None = None
    document_requests: list[DocRequestIn] = []


class Hitl1(BaseModel):
    decision: str = Field(pattern="^(approve|corrections|await_documents)$")
    reclassify_document_ids: list[str] = []
    document_requests: list[DocRequestIn] = []
    notes: str | None = None


class Hitl2(BaseModel):
    notes: str | None = None


class Hitl3(BaseModel):
    action: str = Field(pattern="^(approve|revise)$")
    regenerate_instructions: str | None = None


class FlagActionIn(BaseModel):
    flag_id: str
    action: str = Field(pattern="^(approve|reject|modify)$")
    reason: str | None = None
    value: str | None = None


class DecisionIn(BaseModel):
    decision_type: str = Field(pattern="^(treatment_authorization|disability_status|claim_trajectory|reserve_change|referral|escalation)$")
    outcome: str = Field(min_length=2, max_length=500)
    rationale: str = Field(min_length=10)
    evidence_refs: list[dict] = []
    outstanding_questions: list[str] = []
    next_steps: list[str | dict] = []


class Hitl4(BaseModel):
    flag_actions: list[FlagActionIn] = []
    decisions: list[DecisionIn] = Field(min_length=1)
    escalate: bool = False
    escalation_reason: str | None = None


class URIn(BaseModel):
    utilization_assessment_id: str
    determination: str = Field(pattern="^(certified|modified|non_certified|pended)$")
    clinical_rationale: str = Field(min_length=20)
    criteria_refs: list[str] = []


class Hitl4UR(BaseModel):
    determinations: list[URIn] = Field(min_length=1)


class Hitl5(BaseModel):
    action: str = Field(pattern="^(signoff|return)$")
    comments: str = Field(min_length=3)


class AwaitDocs(BaseModel):
    resume: bool = True
    notes: str | None = None


SCHEMAS = {"HITL-0": Hitl0, "HITL-1": Hitl1, "HITL-2": Hitl2, "HITL-3": Hitl3, "HITL-4": Hitl4, "HITL-4-UR": Hitl4UR,
           "HITL-5": Hitl5, "AWAIT-DOCS": AwaitDocs}
DECISION_FLAG_TYPES = ("mmi_status", "rtw_limit", "guideline_deviation")


def can_act(review: Review, user: Principal) -> bool:
    return bool(set(user.roles) & CHECKPOINT_ROLES.get(review.checkpoint, set()))


def claim_review(db: Session, review: Review, user: Principal) -> Review:
    if not can_act(review, user):
        raise Forbidden("Your role cannot act on this checkpoint")
    if review.status not in ("pending", "in_progress"):
        raise Conflict(f"Review is {review.status}")
    if review.claimed_by and review.claimed_by != user.id:
        raise Conflict("Review is locked by another user")
    review.claimed_by, review.status = user.id, "in_progress"
    review.assigned_user_id = review.assigned_user_id or user.id
    _audit(db, user, "review.claim", "review", review.id, review.claim_id)
    return review


def reassign(db: Session, review: Review, user: Principal, user_id: str, reason: str) -> Review:
    if review.status not in ("pending", "in_progress"):
        raise Conflict(f"Review is {review.status}")
    target = db.get(User, user_id)
    if target is None or not target.is_active:
        raise BadRequest("Target user not found")
    if not set(target.role_keys) & CHECKPOINT_ROLES.get(review.checkpoint, set()):
        raise BadRequest("Target user's role cannot act on this checkpoint")
    before = review.assigned_user_id
    review.assigned_user_id, review.claimed_by, review.status, review.reason = user_id, None, "pending", reason
    _audit(db, user, "review.reassign", "review", review.id, review.claim_id, before={"user": before}, after={"user": user_id, "reason": reason})
    from app.services.events import notify
    notify(db, user_id, "review_assigned", f"{review.checkpoint}: {review.title}", f"Reassigned: {reason}", review.claim_id, f"/reviews/{review.id}")
    return review


def _doc_requests(db: Session, claim_id: str, user: Principal, reqs: list[DocRequestIn]) -> None:
    for r in reqs:
        row = DocumentRequest(id=uuid7(), claim_id=claim_id, description=r.description, reason=r.reason or "Requested by reviewer",
                              requested_from=r.requested_from, due_date=r.due_date or (date.today() + timedelta(days=14)).isoformat(),
                              source="user", created_by=user.id, status="open")
        db.add(row)
        _audit(db, user, "document_request.create", "document_request", row.id, claim_id, after=r.model_dump())


def submit(db: Session, review: Review, user: Principal, body: dict) -> Review:
    if not can_act(review, user):
        raise Forbidden("Your role cannot act on this checkpoint")
    if review.status not in ("pending", "in_progress"):
        raise Conflict(f"Review is {review.status}")
    if review.claimed_by and review.claimed_by != user.id:
        raise Conflict("Review is locked by another user")
    try:
        data = SCHEMAS[review.checkpoint].model_validate(body)
    except ValidationError as exc:
        raise BadRequest(f"Invalid submission for {review.checkpoint}: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}") from exc
    claim = db.get(Claim, review.claim_id)
    handler = {"HITL-0": _hitl0, "HITL-1": _hitl1, "HITL-2": _hitl2, "HITL-3": _hitl3, "HITL-4": _hitl4,
               "HITL-4-UR": _hitl4ur, "HITL-5": _hitl5, "AWAIT-DOCS": _await}[review.checkpoint]
    handler(db, review, claim, user, data)
    review.response = data.model_dump()
    review.status, review.submitted_by, review.submitted_at = "submitted", user.id, now_iso()
    _audit(db, user, "review.submit", "review", review.id, review.claim_id, after={"checkpoint": review.checkpoint, "response": review.response})
    run = db.get(AgentRun, review.run_id)
    if review.blocks_run and run and run.status in ("awaiting_human", "awaiting_documents") and run.pending_review_id == review.id:
        runs.resume(db, run, review.response)
    return review


# ---- handlers ----------------------------------------------------------------------------------------

def _hitl0(db, review, claim: Claim, user, data: Hitl0):
    before = {"employer_name": claim.employer_name, "date_of_injury": claim.date_of_injury}
    mapping = {"employer_name": "employer_name", "insurer": "insurer", "tpa": "tpa", "date_of_injury": "date_of_injury",
               "mechanism_of_injury": "mechanism_of_injury", "jurisdiction_state": "jurisdiction_state",
               "assigned_adjuster": "adjuster_name", "employer_contact": "employer_contact"}
    fields = dict(claim.baseline.get("fields", {}))
    if data.fields.get("date_of_injury"):
        from app.agents.heuristics import normalize_date
        iso = normalize_date(str(data.fields["date_of_injury"]))
        if not iso:
            raise BadRequest("date_of_injury must be a valid date")
        data.fields["date_of_injury"] = iso
    if data.fields.get("jurisdiction_state"):
        data.fields["jurisdiction_state"] = str(data.fields["jurisdiction_state"]).strip().upper()[:2]
    for k, v in data.fields.items():
        if k in mapping and v is not None:
            setattr(claim, mapping[k], v)
        elif k == "body_parts" and v:
            claim.body_parts = v if isinstance(v, list) else [p.strip() for p in str(v).split(",") if p.strip()]
        elif k == "claimant_name" and v:
            cl = db.get(Claimant, claim.claimant_id)
            cl.full_name_enc = encrypt_str(str(v))
        elif k == "claim_number" and v and v != claim.claim_number:
            raise BadRequest("The claim number cannot be changed at HITL-0")
        if k in fields:
            fields[k] = {**fields[k], "value": v, "confidence": 1.0, "confirmed_by": user.id, "conflict": False}
    for k, f in fields.items():  # everything shown is confirmed when the baseline is locked
        if k not in data.fields and f.get("value") and k in mapping:
            setattr(claim, mapping[k], f["value"])  # confirmed AI-extracted value becomes the claim baseline
        if k not in data.fields:
            fields[k] = {**f, "confirmed_by": user.id, "confidence": 1.0 if f.get("value") else f.get("confidence", 0), "conflict": False}
    claim.baseline = {**claim.baseline, "fields": fields, "confirmed_at": now_iso(), "confirmed_by": user.id}
    if data.time_window_start:
        claim.time_window_start = data.time_window_start
    if data.time_window_end:
        claim.time_window_end = data.time_window_end
    claim.baseline_locked = True
    for f in db.execute(select(Flag).where(Flag.claim_id == claim.id, Flag.flag_type == "baseline_conflict", Flag.human_action.is_(None))).scalars():
        f.human_action, f.acted_by, f.acted_at, f.reason = "approved", user.id, now_iso(), "Resolved at HITL-0"
    if data.review_context:
        for rc in db.execute(select(ReviewContext).where(ReviewContext.claim_id == claim.id, ReviewContext.is_current.is_(True))).scalars():
            rc.is_current = False
        db.add(ReviewContext(id=uuid7(), claim_id=claim.id, source="user", created_by=user.id, approved_by=user.id,
                             is_current=True, **data.review_context.model_dump()))
    else:
        rc = db.execute(select(ReviewContext).where(ReviewContext.claim_id == claim.id, ReviewContext.is_current.is_(True))).scalar_one_or_none()
        if rc:
            rc.approved_by = user.id
    _doc_requests(db, claim.id, user, data.document_requests)
    _audit(db, user, "baseline.lock", "claim", claim.id, claim.id, before=before,
           after={"employer_name": claim.employer_name, "date_of_injury": claim.date_of_injury, "fields_changed": list(data.fields)})


def _hitl1(db, review, claim, user, data: Hitl1):
    if data.decision == "corrections" and not data.reclassify_document_ids:
        raise BadRequest("Corrections require at least one document to reclassify (edit episodes/gaps directly, then approve)")
    for doc_id in data.reclassify_document_ids:
        d = db.get(Document, doc_id)
        if d is None or d.claim_id != claim.id:
            raise BadRequest(f"Unknown document {doc_id}")
    if data.decision == "await_documents" and not data.document_requests and not db.execute(
            select(DocumentRequest.id).where(DocumentRequest.claim_id == claim.id, DocumentRequest.status == "open")).first():
        raise BadRequest("Waiting for documents requires at least one open document request")
    _doc_requests(db, claim.id, user, data.document_requests)
    if data.decision == "approve":
        _audit(db, user, "timeline.approve", "claim", claim.id, claim.id, after={"version": review.payload.get("timeline_version")})


def _hitl2(db, review, claim, user, data: Hitl2):
    ids = review.payload.get("fact_ids", [])
    pending = []
    for fid in ids:
        f = db.get(ExtractedFact, fid)
        if f is not None and f.is_current and f.validation_status in ("pending", "needs_review", "auto_verified"):
            pending.append(f.label)
    if pending:
        raise BadRequest(f"{len(pending)} fact(s) still need an explicit accept/edit/reject (milestone facts always require review)")
    open_d = db.execute(select(Discrepancy).where(Discrepancy.claim_id == claim.id, Discrepancy.status == "open")).scalars().all()
    if open_d:
        raise BadRequest(f"{len(open_d)} discrepancy(ies) must be resolved before submitting")


def _hitl3(db, review, claim, user, data: Hitl3):
    if data.action == "revise":
        if not (data.regenerate_instructions or "").strip():
            raise BadRequest("Regeneration instructions are required")
        return
    for t in ("narrative", "one_page", "mmi_status", "case_progress", "clinical", "case_facts"):
        s = db.execute(select(Summary).where(Summary.claim_id == claim.id, Summary.summary_type == t,
                                             Summary.status.in_(["draft", "in_review"])).order_by(Summary.created_at.desc()).limit(1)).scalar_one_or_none()
        if s:
            s.status, s.approved_by, s.approved_at = "approved", user.id, now_iso()
            for old in db.execute(select(Summary).where(Summary.claim_id == claim.id, Summary.summary_type == t,
                                                        Summary.status == "approved", Summary.id != s.id)).scalars():
                old.status = "superseded"
            _audit(db, user, "summary.approve", "summary", s.id, claim.id, after={"type": t, "version": s.version})


def _hitl4(db, review, claim, user, data: Hitl4):
    for fa in data.flag_actions:
        flag = db.get(Flag, fa.flag_id)
        if flag is None or flag.claim_id != claim.id:
            raise BadRequest(f"Unknown flag {fa.flag_id}")
        act_on_flag(db, flag, user, fa.action, fa.reason, fa.value)
    db.flush()
    unacted = db.execute(select(Flag).where(Flag.claim_id == claim.id, Flag.flag_type.in_(DECISION_FLAG_TYPES),
                                            Flag.human_action.is_(None))).scalars().all()
    if unacted:
        raise BadRequest(f"{len(unacted)} AI-highlighted flag(s) (MMI, RTW, guideline) still need approve/reject/modify")
    if data.escalate and not data.escalation_reason:
        raise BadRequest("An escalation reason is required")
    draft = db.execute(select(Decision).where(Decision.claim_id == claim.id, Decision.status == "draft")).scalars().first()
    for i, d in enumerate(data.decisions):
        row = draft if (i == 0 and draft is not None) else Decision(id=uuid7(), claim_id=claim.id, ai_draft=draft.ai_draft if draft else None)
        row.run_id, row.review_id, row.decision_type, row.outcome, row.rationale = review.run_id, review.id, d.decision_type, d.outcome, d.rationale
        row.evidence_refs, row.outstanding_questions, row.next_steps = d.evidence_refs, d.outstanding_questions, d.next_steps
        row.decided_by, row.decided_at, row.status = user.id, now_iso(), "final"
        if row is not draft:
            db.add(row)
        _audit(db, user, "decision.create", "decision", row.id, claim.id, after={"type": d.decision_type, "outcome": d.outcome})
    if data.escalate:
        _audit(db, user, "decision.escalate", "claim", claim.id, claim.id, after={"reason": data.escalation_reason})


def _hitl4ur(db, review, claim, user, data: Hitl4UR):
    if "clinical_reviewer" not in user.roles:
        raise Forbidden("UR determinations can only be recorded by a clinical reviewer")
    for d in data.determinations:
        record_ur(db, claim, user, d)
    pending = db.execute(select(UtilizationAssessment).where(UtilizationAssessment.claim_id == claim.id,
                                                             UtilizationAssessment.status == "ai_draft")).scalars().all()
    if pending:
        raise BadRequest(f"{len(pending)} utilization request(s) still need a determination")


def record_ur(db: Session, claim: Claim, user: Principal, d: URIn) -> URDetermination:
    if "clinical_reviewer" not in user.roles:
        raise Forbidden("UR determinations can only be recorded by a clinical reviewer")
    ua = db.get(UtilizationAssessment, d.utilization_assessment_id)
    if ua is None or ua.claim_id != claim.id:
        raise BadRequest("Unknown utilization assessment")
    if ua.status == "determined":
        raise Conflict("This request already has a determination")
    row = URDetermination(id=uuid7(), claim_id=claim.id, utilization_assessment_id=ua.id, determination=d.determination,
                          clinical_rationale=d.clinical_rationale, criteria_refs=d.criteria_refs, reviewer_id=user.id,
                          determined_at=now_iso())
    db.add(row)
    ua.status = "determined"
    _audit(db, user, "ur.determination", "ur_determination", row.id, claim.id, after=d.model_dump())
    return row


def _hitl5(db, review, claim, user, data: Hitl5):
    decisions = db.execute(select(Decision).where(Decision.claim_id == claim.id, Decision.status == "final")).scalars().all()
    if any(d.decided_by == user.id for d in decisions):  # separation of duties (spec §3.3 rule 1)
        raise Forbidden("The user who made the HITL-4 decision cannot sign off HITL-5 on the same claim")
    for d in decisions:
        if data.action == "signoff":
            d.signed_off_by, d.signed_off_at, d.signoff_comments = user.id, now_iso(), data.comments
        _audit(db, user, "decision.signoff" if data.action == "signoff" else "decision.return", "decision", d.id, claim.id,
               after={"comments": data.comments})


def _await(db, review, claim, user, data: AwaitDocs):
    new_docs = db.execute(select(Document.id).where(Document.claim_id == claim.id, Document.status == "received")).first()
    if not new_docs:
        raise BadRequest("Upload the requested documents before resuming the run")


# ---- SLA timers (spec §14.2 'HITL SLA timers') -----------------------------------------------------------

def escalate_overdue(db: Session) -> int:
    from app.models import Role, UserRole
    from app.services.events import notify

    overdue = db.execute(select(Review).where(Review.status.in_(["pending", "in_progress"]), Review.escalated.is_(False),
                                              Review.due_at < now_iso())).scalars().all()
    if not overdue:
        return 0
    supervisors = db.execute(select(User.id).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
                             .where(Role.key == "claims_supervisor")).scalars().all()
    for r in overdue:
        r.escalated, r.priority = True, 1
        for uid in supervisors:
            notify(db, uid, "sla_breach", f"SLA breach: {r.checkpoint} {r.title}", f"Due {r.due_at}", r.claim_id, f"/reviews/{r.id}")
        from app.services import audit
        audit.record(db, action="review.sla_breach", entity_type="review", entity_id=r.id, claim_id=r.claim_id,
                     actor_type="system", actor_id="scheduler", after={"due_at": r.due_at})
    return len(overdue)


def follow_up(db: Session, claim: Claim, user: Principal, action: str, owner_id: str | None, due_date: str | None) -> FollowUp:
    row = FollowUp(id=uuid7(), claim_id=claim.id, action=action, owner_id=owner_id or user.id, due_date=due_date, created_by=user.id)
    db.add(row)
    _audit(db, user, "follow_up.create", "follow_up", row.id, claim.id, after={"action": action, "due_date": due_date})
    return row
