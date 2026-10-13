"""Workflow runs and the SSE event stream (spec §12.4, §18.5)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import envelope, get_db, require_permission
from app.api.v1.claims import clinical_access
from app.core.errors import Forbidden, NotFound
from app.db.session import SessionLocal
from app.models import AgentRun, AgentStep, Claim, LlmCall, Review, ToolCall
from app.services import runs as run_service
from app.services.actions import Principal
from app.services.claims import get_claim_for
from app.services.events import events_after

router = APIRouter(tags=["runs"])


class RunIn(BaseModel):
    mode: str = Field(default="full", pattern="^(full|incremental)$")
    options: dict = {}


class CancelIn(BaseModel):
    reason: str = Field(min_length=3)


def run_dict(db: Session, r: AgentRun) -> dict:
    review = db.get(Review, r.pending_review_id) if r.pending_review_id else None
    return {"id": r.id, "claim_id": r.claim_id, "parent_run_id": r.parent_run_id, "mode": r.mode, "status": r.status,
            "current_stage": r.current_stage, "current_node": r.current_node, "stage_status": r.stage_status,
            "graph_version": r.graph_version, "llm_mode": r.llm_mode, "started_by": r.started_by, "started_at": r.started_at,
            "completed_at": r.completed_at, "error": r.error, "total_tokens": r.total_tokens, "total_cost_usd": r.total_cost_usd,
            "created_at": r.created_at,
            "pending_review": {"id": review.id, "checkpoint": review.checkpoint, "title": review.title,
                               "assigned_role": review.assigned_role, "status": review.status} if review else None}


def _run_for(db: Session, user: Principal, run_id: str) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise NotFound("Run not found")
    get_claim_for(db, user, run.claim_id)
    return run


@router.post("/claims/{claim_id}/runs", status_code=202)
def start(body: RunIn, claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
          user: Principal = Depends(require_permission("run:start"))):
    run = run_service.start_run(db, claim.id, user.id, body.mode, body.options)
    return envelope({"run_id": run.id, "status": run.status})


@router.get("/claims/{claim_id}/runs")
def list_runs(claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    rows = db.execute(select(AgentRun).where(AgentRun.claim_id == claim.id).order_by(AgentRun.created_at.desc())).scalars()
    return envelope([run_dict(db, r) for r in rows])


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    run = _run_for(db, user, run_id)
    errors = db.execute(select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.status == "failed")).scalars().all()
    return envelope({**run_dict(db, run), "errors": [{"node": s.node_name, "type": s.error_type, "message": s.error_message,
                                                       "at": s.ended_at} for s in errors]})


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, user: Principal = Depends(require_permission("document:view_phi"))):
    db = SessionLocal()
    try:
        _run_for(db, user, run_id)
    finally:
        db.close()
    try:
        last_id = int(request.headers.get("last-event-id") or request.query_params.get("last_event_id") or 0)
    except ValueError:
        last_id = 0

    async def stream():
        nonlocal last_id
        idle = 0
        while not await request.is_disconnected():
            s = SessionLocal()
            try:
                evs = events_after(s, run_id, last_id)
                status = s.get(AgentRun, run_id).status
            finally:
                s.close()
            for ev in evs:
                last_id = ev.id
                yield {"id": str(ev.id), "event": ev.event_type, "data": json.dumps({**ev.data, "ts": ev.created_at})}
            idle = 0 if evs else idle + 1
            if status in ("completed", "failed", "cancelled") and not evs and idle > 2:
                yield {"event": "end", "data": "{}"}
                return
            await asyncio.sleep(1)
    return EventSourceResponse(stream(), ping=15)


@router.get("/runs/{run_id}/steps")
def steps(run_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("audit:view", "run:manage"))):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise NotFound("Run not found")
    rows = db.execute(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.started_at)).scalars().all()
    tools = {}
    for t in db.execute(select(ToolCall.step_id, func.count(), func.sum(ToolCall.duration_ms)).where(ToolCall.run_id == run_id)
                        .group_by(ToolCall.step_id)).all():
        tools[t[0]] = {"count": t[1], "duration_ms": t[2]}
    llm = {}
    for t in db.execute(select(LlmCall.step_id, func.count(), func.sum(LlmCall.input_tokens + LlmCall.output_tokens), func.sum(LlmCall.cost_usd))
                        .where(LlmCall.run_id == run_id).group_by(LlmCall.step_id)).all():
        llm[t[0]] = {"count": t[1], "tokens": t[2], "cost_usd": round(t[3] or 0, 5)}
    return envelope([{"id": s.id, "node": s.node_name, "stage": s.stage, "attempt": s.attempt, "status": s.status,
                      "started_at": s.started_at, "ended_at": s.ended_at, "duration_ms": s.duration_ms, "error_type": s.error_type,
                      "error_message": s.error_message, "output": s.output_ref, "tool_calls": tools.get(s.id),
                      "llm_calls": llm.get(s.id)} for s in rows])


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, body: CancelIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    run = _run_for(db, user, run_id)
    if run.started_by != user.id and "run:manage" not in user.permissions:
        raise Forbidden("Only the user who started the run or a supervisor can cancel it")
    return envelope(run_dict(db, run_service.cancel(db, run, user.id, body.reason)))


@router.post("/runs/{run_id}/retry", status_code=202)
def retry(run_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("run:manage"))):
    run = _run_for(db, user, run_id) if "document:view_phi" in user.permissions else db.get(AgentRun, run_id)
    if run is None:
        raise NotFound("Run not found")
    return envelope(run_dict(db, run_service.retry(db, run, user.id)))
