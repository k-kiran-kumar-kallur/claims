"""Orchestration, telemetry and audit tables (spec §11.2)."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import now_iso
from app.db.base import Base, IdMixin, MutableMixin, TimestampMixin


class Job(IdMixin, MutableMixin, Base):
    __tablename__ = "jobs"
    job_type: Mapped[str] = mapped_column(String(32))  # start_run|resume_run|retry_run|export_report|reindex
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|claimed|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[str] = mapped_column(String(30), default=now_iso)
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[str | None] = mapped_column(String(30))
    finished_at: Mapped[str | None] = mapped_column(String(30))
    last_error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class AgentRun(IdMixin, MutableMixin, Base):
    __tablename__ = "agent_runs"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(36))
    mode: Mapped[str] = mapped_column(String(16), default="full")  # full|incremental
    graph_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    # queued|running|awaiting_human|awaiting_documents|retrying|failed|completed|cancelled
    current_stage: Mapped[str | None] = mapped_column(String(32))
    current_node: Mapped[str | None] = mapped_column(String(64))
    stage_status: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    llm_mode: Mapped[str | None] = mapped_column(String(16))
    started_by: Mapped[str | None] = mapped_column(String(36))
    started_at: Mapped[str | None] = mapped_column(String(30))
    completed_at: Mapped[str | None] = mapped_column(String(30))
    pending_review_id: Mapped[str | None] = mapped_column(String(36))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class AgentStep(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_steps"
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    node_name: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))  # started|completed|failed|interrupted|retrying
    input_ref: Mapped[dict | None] = mapped_column(JSON)
    output_ref: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[str] = mapped_column(String(30), default=now_iso)
    ended_at: Mapped[str | None] = mapped_column(String(30))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class ToolCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "tool_calls"
    step_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str] = mapped_column(String(16))
    args_redacted: Mapped[dict | None] = mapped_column(JSON)
    result_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class LlmCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_calls"
    step_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(16), default="gemini")
    model: Mapped[str] = mapped_column(String(128))
    prompt_template: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    safety_ratings: Mapped[dict | None] = mapped_column(JSON)
    request_enc: Mapped[str | None] = mapped_column(Text)
    response_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # ok|error|repaired|blocked
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(30), default=now_iso)


class PromptTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(16))
    template: Mapped[str] = mapped_column(Text)
    system: Mapped[str | None] = mapped_column(Text)
    output_schema: Mapped[dict | None] = mapped_column(JSON)
    model_tier: Mapped[str] = mapped_column(String(16), default="fast")
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36))


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(36))


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    beat_at: Mapped[str] = mapped_column(String(30), default=now_iso)
    current_job_id: Mapped[str | None] = mapped_column(String(36))
    pid: Mapped[int | None] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(30), default=now_iso, index=True)
    actor_type: Mapped[str] = mapped_column(String(8))  # user|agent|system
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    claim_id: Mapped[str | None] = mapped_column(String(36), index=True)
    before: Mapped[dict | list | None] = mapped_column(JSON)
    after: Mapped[dict | list | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
