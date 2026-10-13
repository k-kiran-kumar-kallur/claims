"""@agent_node decorator (spec §6.4): step rows, context injection, run events, retries, cancel checks."""
from __future__ import annotations

import functools
import random
import time
import traceback
from collections.abc import Callable

from langgraph.errors import GraphInterrupt

from app.config import settings
from app.core.correlation import claim_id_var, correlation_id_var, node_var, run_id_var
from app.core.errors import RunCancelled, TransientExternalError
from app.core.ids import now_iso, uuid7
from app.core.logging import get_logger
from app.db.session import SessionLocal, session_scope
from app.models import AgentRun, AgentStep, ToolCall
from app.orchestration.context import AgentContext
from app.orchestration.state import STAGES
from app.services.events import emit

log = get_logger(__name__)


def _flush_telemetry(telemetry: list[dict]) -> None:
    if not telemetry:
        return
    with session_scope() as db:
        for t in telemetry:
            if t.get("kind") == "tool":
                db.add(ToolCall(step_id=t["step_id"], run_id=t["run_id"], tool_name=t["tool_name"],
                                tool_version=t["tool_version"], args_redacted=t["args_redacted"], result_ref=t["result_ref"],
                                status=t["status"], attempts=t["attempts"], duration_ms=t["duration_ms"], error=t["error"]))
    telemetry.clear()


def _start_step(run_id: str, claim_id: str, name: str, stage: str, attempt: int, step_id: str, cid: str) -> None:
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        if run is None:
            raise RunCancelled("run not found")
        if run.cancel_requested:
            raise RunCancelled(run.cancel_reason or "cancel requested")
        status = dict(run.stage_status or {})
        idx = STAGES.index(stage)
        for s in STAGES[:idx]:
            if status.get(s) != "completed":
                status[s] = "completed"
        status[stage] = "in_progress"
        run.stage_status, run.current_stage, run.current_node, run.status = status, stage, name, "running"
        db.add(AgentStep(id=step_id, run_id=run_id, node_name=name, stage=stage, attempt=attempt, status="started",
                         correlation_id=cid))
        emit(run_id, "node_started", {"node": name, "stage": stage, "attempt": attempt, "stage_status": status},
             claim_id=claim_id, db=db)


def _end_step(step_id: str, status: str, started: float, output_ref: dict | None = None, error: Exception | None = None) -> None:
    with session_scope() as db:
        step = db.get(AgentStep, step_id)
        if step:
            step.status, step.ended_at = status, now_iso()
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.output_ref = output_ref
            if error is not None:
                step.error_type, step.error_message = type(error).__name__, str(error)[:2000]


def agent_node(name: str, stage: str, max_retries: int | None = None) -> Callable:
    retries = settings.NODE_MAX_RETRIES if max_retries is None else max_retries

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            run_id, claim_id = state["run_id"], state["claim_id"]
            cid = correlation_id_var.get() or uuid7()
            run_id_var.set(run_id)
            claim_id_var.set(claim_id)
            node_var.set(name)
            attempt = 0
            while True:
                attempt += 1
                step_id = uuid7()
                started = time.monotonic()
                _start_step(run_id, claim_id, name, stage, attempt, step_id, cid)
                db = SessionLocal()
                ctx = AgentContext(db=db, run_id=run_id, claim_id=claim_id, node=name, stage=stage, step_id=step_id,
                                   correlation_id=cid)
                try:
                    update = fn(state, ctx) or {}
                    db.commit()
                    _flush_telemetry(ctx.telemetry)
                    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in update.items()
                               if k not in ("stage_status", "human_feedback", "pending_review")}
                    _end_step(step_id, "completed", started, output_ref=summary)
                    emit(run_id, "node_completed", {"node": name, "stage": stage, "output": summary}, claim_id=claim_id)
                    log.info("node_completed", node=name, duration_ms=int((time.monotonic() - started) * 1000))
                    update.setdefault("current_stage", stage)
                    return update
                except GraphInterrupt:
                    db.commit()
                    _flush_telemetry(ctx.telemetry)
                    _end_step(step_id, "interrupted", started)
                    raise
                except TransientExternalError as exc:
                    db.rollback()
                    _flush_telemetry(ctx.telemetry)
                    _end_step(step_id, "failed", started, error=exc)
                    if attempt > retries:
                        raise
                    delay = exc.retry_after or min(2 ** attempt, 30) + random.uniform(0, 1)
                    emit(run_id, "retrying", {"node": name, "attempt": attempt, "delay_s": round(delay, 1),
                                              "error": str(exc)[:300]}, claim_id=claim_id)
                    log.warning("node_retrying", node=name, attempt=attempt, error=str(exc))
                    time.sleep(0 if settings.APP_ENV == "test" else min(delay, 60))
                except Exception as exc:
                    db.rollback()
                    _flush_telemetry(ctx.telemetry)
                    _end_step(step_id, "failed", started, error=exc)
                    log.error("node_failed", node=name, error=str(exc), trace=traceback.format_exc()[-2000:])
                    raise
                finally:
                    db.close()
        wrapper.node_name = name  # type: ignore[attr-defined]
        wrapper.stage = stage  # type: ignore[attr-defined]
        return wrapper
    return deco
