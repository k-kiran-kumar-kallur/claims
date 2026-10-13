"""Background worker (spec §5.4, ADR-003): polls the SQLite `jobs` table, runs LangGraph, handles HITL interrupts,
retries, cancellation, SLA timers and heartbeats.

Run standalone with `python -m app.worker`, or in-process (dev) when RUN_WORKER_IN_PROCESS=true.
"""
from __future__ import annotations

import os
import signal
import socket
import threading
import time
import traceback
from datetime import timedelta

from langgraph.types import Command
from sqlalchemy import text

from app.config import settings
from app.core.correlation import correlation_id_var
from app.core.errors import QuotaExhaustedError, RunCancelled, TransientExternalError
from app.core.ids import now_iso, to_iso, utcnow
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.models import AgentRun, Claim, Job, Report, Review, WorkerHeartbeat
from app.services import audit
from app.services.events import emit, notify

log = get_logger("worker")


class Worker:
    def __init__(self, worker_id: str | None = None):
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident() % 10000}"
        self._graph = None
        self._last_sla = 0.0
        self.stop_event = threading.Event()

    @property
    def graph(self):
        if self._graph is None:
            from app.orchestration.graph import get_graph
            self._graph = get_graph()
        return self._graph

    # ---- queue ---------------------------------------------------------------------------------------
    def claim_job(self) -> Job | None:
        with session_scope() as db:
            row = db.execute(text(
                "UPDATE jobs SET status='claimed', claimed_by=:w, claimed_at=:now, attempts=attempts+1, updated_at=:now "
                "WHERE id = (SELECT id FROM jobs WHERE status='queued' AND available_at <= :now ORDER BY created_at LIMIT 1) "
                "RETURNING id"), {"w": self.worker_id, "now": now_iso()}).first()
            if row is None:
                return None
            job = db.get(Job, row[0])
            db.expunge(job)
            return job

    def heartbeat(self, job_id: str | None = None) -> None:
        with session_scope() as db:
            hb = db.get(WorkerHeartbeat, self.worker_id) or WorkerHeartbeat(worker_id=self.worker_id)
            hb.beat_at, hb.current_job_id, hb.pid = now_iso(), job_id, os.getpid()
            db.merge(hb)

    def run_once(self) -> bool:
        self.heartbeat()
        self._sla_tick()
        job = self.claim_job()
        if job is None:
            return False
        correlation_id_var.set(job.correlation_id)
        self.heartbeat(job.id)
        try:
            self.handle(job)
            with session_scope() as db:
                j = db.get(Job, job.id)
                j.status, j.finished_at = "done", now_iso()
        except Exception as exc:
            log.error("job_failed", job_id=job.id, error=str(exc), trace=traceback.format_exc()[-1500:])
            with session_scope() as db:
                j = db.get(Job, job.id)
                j.last_error = str(exc)[:2000]
                if j.attempts < j.max_attempts and not isinstance(exc, RunCancelled):
                    j.status, j.available_at = "queued", to_iso(utcnow() + timedelta(seconds=10 * j.attempts))
                else:
                    j.status = "failed"
        return True

    def loop(self) -> None:
        log.info("worker_started", worker_id=self.worker_id, llm_mode=settings.llm_mode)
        while not self.stop_event.is_set():
            try:
                busy = self.run_once()
            except Exception as exc:
                log.error("worker_loop_error", error=str(exc))
                busy = False
            if not busy:
                self.stop_event.wait(settings.WORKER_POLL_SECONDS)

    def drain(self, max_jobs: int = 500) -> int:
        """Process jobs until the queue is empty (tests / CLI)."""
        n = 0
        while n < max_jobs and self.run_once():
            n += 1
        return n

    # ---- job handlers ------------------------------------------------------------------------------------
    def handle(self, job: Job) -> None:
        if job.job_type in ("start_run", "resume_run", "retry_run"):
            self._run_graph(job)
        elif job.job_type == "export_report":
            from app.services.report_service import render
            with session_scope() as db:
                rep = db.get(Report, job.payload["report_id"])
                render(db, rep)
        else:
            raise ValueError(f"unknown job type {job.job_type}")

    def _run_graph(self, job: Job) -> None:
        from app.orchestration.state import initial_state

        run_id = job.payload["run_id"]
        with session_scope() as db:
            run = db.get(AgentRun, run_id)
            if run is None or run.status == "cancelled":
                return
            run.status = "running"
            run.started_at = run.started_at or now_iso()
            claim_id, user_id, mode = run.claim_id, run.started_by, run.mode
        config = {"configurable": {"thread_id": run_id}, "max_concurrency": 4, "recursion_limit": 250}
        if job.job_type == "start_run":
            emit(run_id, "run_started", {"mode": mode}, claim_id=claim_id)
            payload = initial_state(run_id, claim_id, user_id, mode)
        elif job.job_type == "resume_run":
            payload = Command(resume=job.payload.get("resume") or {})
        else:
            payload = None
        try:
            self.graph.invoke(payload, config)
        except RunCancelled as exc:
            self._finish(run_id, "cancelled", str(exc))
            return
        except QuotaExhaustedError as exc:
            self._defer(run_id, exc.retry_after or 3600, f"quota exhausted: {exc}", notify_supervisors=True)
            return
        except TransientExternalError as exc:
            self._defer(run_id, exc.retry_after or 60, str(exc))
            return
        except Exception as exc:
            self._finish(run_id, "failed", f"{type(exc).__name__}: {exc}")
            return
        self._after_invoke(run_id, config)

    def _after_invoke(self, run_id: str, config: dict) -> None:
        snapshot = self.graph.get_state(config)
        interrupts = [i for t in snapshot.tasks for i in (t.interrupts or [])]
        with session_scope() as db:
            run = db.get(AgentRun, run_id)
            if interrupts:
                value = interrupts[0].value or {}
                review = db.get(Review, value.get("review_id")) if value.get("review_id") else None
                awaiting_docs = value.get("checkpoint") == "AWAIT-DOCS"
                run.status = "awaiting_documents" if awaiting_docs else "awaiting_human"
                run.pending_review_id = review.id if review else None
                status = dict(run.stage_status or {})
                if run.current_stage:
                    status[run.current_stage] = "awaiting_review"
                run.stage_status = status
                emit(run_id, "awaiting_documents" if awaiting_docs else "awaiting_review",
                     {"review_id": review.id if review else None, "checkpoint": value.get("checkpoint"), "title": value.get("title")},
                     claim_id=run.claim_id, db=db)
            elif not snapshot.next:
                run.status, run.completed_at, run.current_node, run.pending_review_id = "completed", now_iso(), None, None
                run.stage_status = {k: "completed" for k in (run.stage_status or {})} or run.stage_status
                claim = db.get(Claim, run.claim_id)
                if claim:
                    claim.current_stage = "done"
                emit(run_id, "run_completed", {"total_tokens": run.total_tokens, "cost_usd": run.total_cost_usd}, claim_id=run.claim_id, db=db)
                audit.record(db, action="run.complete", entity_type="agent_run", entity_id=run_id, claim_id=run.claim_id,
                             actor_type="system", actor_id=self.worker_id)

    def _defer(self, run_id: str, seconds: float, reason: str, notify_supervisors: bool = False) -> None:
        from app.services.runs import enqueue

        with session_scope() as db:
            run = db.get(AgentRun, run_id)
            run.status, run.error = "retrying", reason[:2000]
            enqueue(db, "retry_run", {"run_id": run_id}, available_at=to_iso(utcnow() + timedelta(seconds=seconds)))
            emit(run_id, "retrying", {"reason": reason[:300], "retry_in_s": int(seconds)}, claim_id=run.claim_id, db=db)
            if notify_supervisors:
                self._alert(db, run, f"Run paused: {reason[:120]}")

    def _finish(self, run_id: str, status: str, error: str) -> None:
        with session_scope() as db:
            run = db.get(AgentRun, run_id)
            run.status, run.error, run.completed_at = status, error[:4000], now_iso()
            emit(run_id, "run_failed" if status == "failed" else "run_cancelled", {"error": error[:500]}, claim_id=run.claim_id, db=db)
            audit.record(db, action=f"run.{status}", entity_type="agent_run", entity_id=run_id, claim_id=run.claim_id,
                         actor_type="system", actor_id=self.worker_id, after={"error": error[:500]})
            if status == "failed":
                self._alert(db, run, f"Workflow run failed: {error[:150]}")

    @staticmethod
    def _alert(db, run: AgentRun, title: str) -> None:
        from sqlalchemy import select

        from app.models import Role, User, UserRole
        for uid in db.execute(select(User.id).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
                              .where(Role.key == "claims_supervisor")).scalars():
            notify(db, uid, "run_alert", title, None, run.claim_id, f"/claims/{run.claim_id}")

    def _sla_tick(self) -> None:
        if time.monotonic() - self._last_sla < 60:
            return
        self._last_sla = time.monotonic()
        from app.api.v1.admin import purge_llm_bodies
        from app.services.reviews import escalate_overdue
        try:
            with session_scope() as db:
                n = escalate_overdue(db)
                if n:
                    log.info("sla_escalations", count=n)
                purged = purge_llm_bodies(db)
                if purged:
                    log.info("llm_bodies_purged", count=purged)
        except Exception as exc:
            log.warning("sla_tick_failed", error=str(exc))


_thread: threading.Thread | None = None
_worker: Worker | None = None


def start_in_process() -> Worker:
    global _thread, _worker
    if _thread and _thread.is_alive():
        return _worker  # type: ignore[return-value]
    _worker = Worker()
    _thread = threading.Thread(target=_worker.loop, name="claims-worker", daemon=True)
    _thread.start()
    return _worker


def stop_in_process() -> None:
    if _worker:
        _worker.stop_event.set()


def main() -> None:
    configure_logging(settings.LOG_LEVEL, service="worker")
    from app.db.init_db import init_db
    init_db()
    w = Worker()

    def _stop(*_):
        w.stop_event.set()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    w.loop()


if __name__ == "__main__":
    main()
