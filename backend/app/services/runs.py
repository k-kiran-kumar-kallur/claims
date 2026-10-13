"""Workflow run service (spec §5.4, §6.7, §12.4)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.correlation import get_correlation_id
from app.core.errors import BadRequest, Conflict
from app.core.ids import now_iso, uuid7
from app.models import AgentRun, Document, Job, Review
from app.services import audit
from app.services.events import emit

ACTIVE = ("queued", "running", "awaiting_human", "awaiting_documents", "retrying")


def active_run(db: Session, claim_id: str) -> AgentRun | None:
    return db.execute(select(AgentRun).where(AgentRun.claim_id == claim_id, AgentRun.status.in_(ACTIVE))
                      .order_by(AgentRun.created_at.desc()).limit(1)).scalar_one_or_none()


def enqueue(db: Session, job_type: str, payload: dict, available_at: str | None = None) -> Job:
    job = Job(id=uuid7(), job_type=job_type, payload=payload, max_attempts=settings.JOB_MAX_ATTEMPTS,
              correlation_id=get_correlation_id(), available_at=available_at or now_iso())
    db.add(job)
    return job


def start_run(db: Session, claim_id: str, user_id: str, mode: str = "full", options: dict | None = None) -> AgentRun:
    if mode not in ("full", "incremental"):
        raise BadRequest("mode must be 'full' or 'incremental'")
    if active_run(db, claim_id):
        raise Conflict("A workflow run is already active for this claim")
    if not db.execute(select(Document.id).where(Document.claim_id == claim_id)).first():
        raise BadRequest("Upload at least one document before starting a run")
    parent = db.execute(select(AgentRun).where(AgentRun.claim_id == claim_id).order_by(AgentRun.created_at.desc()).limit(1)).scalar_one_or_none()
    if mode == "incremental" and parent is None:
        mode = "full"
    from app.orchestration.graph import GRAPH_VERSION

    run = AgentRun(id=uuid7(), claim_id=claim_id, parent_run_id=parent.id if parent else None, mode=mode,
                   graph_version=GRAPH_VERSION, status="queued", started_by=user_id, options=options or {},
                   llm_mode=settings.llm_mode, correlation_id=get_correlation_id(), stage_status={})
    db.add(run)
    enqueue(db, "start_run", {"run_id": run.id})
    audit.record(db, action="run.start", entity_type="agent_run", entity_id=run.id, claim_id=claim_id, actor_id=user_id,
                 after={"mode": mode})
    db.flush()
    emit(run.id, "run_queued", {"mode": mode}, claim_id=claim_id, db=db)
    return run


def resume(db: Session, run: AgentRun, payload: dict) -> None:
    run.status, run.pending_review_id = "queued", None
    enqueue(db, "resume_run", {"run_id": run.id, "resume": payload})
    emit(run.id, "run_resumed", {}, claim_id=run.claim_id, db=db)


def cancel(db: Session, run: AgentRun, user_id: str, reason: str) -> AgentRun:
    if run.status not in ACTIVE:
        raise Conflict(f"Run is {run.status}")
    run.cancel_requested, run.cancel_reason = True, reason
    if run.status in ("awaiting_human", "awaiting_documents", "queued", "retrying"):
        run.status, run.completed_at = "cancelled", now_iso()
        for r in db.execute(select(Review).where(Review.run_id == run.id, Review.status.in_(["pending", "in_progress"]))).scalars():
            r.status = "cancelled"
        for j in db.execute(select(Job).where(Job.status == "queued")).scalars():
            if (j.payload or {}).get("run_id") == run.id:
                j.status, j.last_error = "failed", "run cancelled"
        emit(run.id, "run_cancelled", {"reason": reason}, claim_id=run.claim_id, db=db)
    audit.record(db, action="run.cancel", entity_type="agent_run", entity_id=run.id, claim_id=run.claim_id, actor_id=user_id,
                 after={"reason": reason})
    return run


def retry(db: Session, run: AgentRun, user_id: str) -> AgentRun:
    if run.status not in ("failed", "retrying"):
        raise Conflict("Only failed runs can be retried from their checkpoint")
    run.status, run.error = "queued", None
    enqueue(db, "retry_run", {"run_id": run.id})
    audit.record(db, action="run.retry", entity_type="agent_run", entity_id=run.id, claim_id=run.claim_id, actor_id=user_id)
    emit(run.id, "run_queued", {"retry": True}, claim_id=run.claim_id, db=db)
    return run
