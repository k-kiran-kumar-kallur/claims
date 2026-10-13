"""HITL checkpoint helper (spec §6.5): idempotent review creation + LangGraph interrupt()."""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from langgraph.types import interrupt
from sqlalchemy import select

from app.config import settings
from app.core.ids import to_iso, utcnow, uuid7
from app.core.rbac import CHECKPOINT_PRIMARY_ROLE
from app.models import Claim, Review, Role, User, UserRole
from app.orchestration.context import AgentContext
from app.services.events import notify


def checkpoint_assignee(ctx: AgentContext, checkpoint: str) -> str | None:
    claim: Claim = ctx.claim
    role = CHECKPOINT_PRIMARY_ROLE[checkpoint]
    by_role = {"claims_examiner": claim.assigned_adjuster_id, "nurse_case_manager": claim.assigned_ncm_id,
               "clinical_reviewer": claim.assigned_reviewer_id, "claims_supervisor": claim.assigned_supervisor_id}
    return by_role.get(role)


def users_with_role(ctx: AgentContext, role_key: str) -> list[str]:
    return list(ctx.db.execute(select(User.id).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
                               .where(Role.key == role_key, User.is_active.is_(True))).scalars())


def ensure_review(ctx: AgentContext, checkpoint: str, iteration: int, title: str, payload_fn: Callable[[], dict],
                  priority: int = 3, blocks_run: bool = True) -> Review:
    key = f"{ctx.run_id}:{checkpoint}:{iteration}"
    review = ctx.db.execute(select(Review).where(Review.review_key == key)).scalar_one_or_none()
    if review is not None:
        return review
    role = CHECKPOINT_PRIMARY_ROLE[checkpoint]
    assignee = checkpoint_assignee(ctx, checkpoint)
    review = Review(id=uuid7(), run_id=ctx.run_id, claim_id=ctx.claim_id, checkpoint=checkpoint, review_key=key,
                    title=title, assigned_role=role, assigned_user_id=assignee, payload=payload_fn(), priority=priority,
                    blocks_run=blocks_run,
                    due_at=to_iso(utcnow() + timedelta(hours=settings.HITL_SLA_HOURS.get(checkpoint, 48))))
    ctx.db.add(review)
    ctx.audit("review.create", "review", review.id, after={"checkpoint": checkpoint, "title": title, "role": role})
    targets = [assignee] if assignee else users_with_role(ctx, role)
    for uid in targets:
        notify(ctx.db, uid, "review_assigned", f"{checkpoint}: {title}", f"Claim {ctx.claim.claim_number}",
               claim_id=ctx.claim_id, link=f"/reviews/{review.id}")
    return review


def await_human(ctx: AgentContext, checkpoint: str, iteration: int, title: str, payload_fn: Callable[[], dict],
                priority: int = 3) -> tuple[Review, dict]:
    """Create the review (once) and pause the graph; returns the submitted response after resume."""
    review = ensure_review(ctx, checkpoint, iteration, title, payload_fn, priority)
    review_id = review.id
    ctx.db.commit()
    response = interrupt({"review_id": review_id, "checkpoint": checkpoint, "title": title})
    review = ctx.db.get(Review, review_id)
    if not isinstance(response, dict):
        response = review.response or {}
    return review, response
