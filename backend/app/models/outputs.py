"""Outputs, HITL reviews, flags and decisions (spec §11.2 'Outputs and decisions')."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, MutableMixin, TimestampMixin


class ChronologyEvent(IdMixin, MutableMixin, Base):
    __tablename__ = "chronology_events"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    event_date: Mapped[str | None] = mapped_column(String(10))
    provider: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    key_findings: Mapped[str | None] = mapped_column(Text)
    work_status: Mapped[str | None] = mapped_column(String(128))
    episode_id: Mapped[str | None] = mapped_column(String(36))
    document_id: Mapped[str | None] = mapped_column(String(36))
    fact_ids: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_turning_point: Mapped[bool] = mapped_column(Boolean, default=False)
    chronology_version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    edited_by: Mapped[str | None] = mapped_column(String(36))
    supersedes_id: Mapped[str | None] = mapped_column(String(36))


class Summary(IdMixin, MutableMixin, Base):
    __tablename__ = "summaries"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    summary_type: Mapped[str] = mapped_column(String(32))
    # clinical|executive|narrative|one_page|case_facts|mmi_status|case_progress
    content_md: Mapped[str] = mapped_column(Text)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|in_review|approved|superseded
    generated_by_run_id: Mapped[str | None] = mapped_column(String(36))
    author_type: Mapped[str] = mapped_column(String(8), default="agent")  # agent|user
    edited_by: Mapped[str | None] = mapped_column(String(36))
    edit_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[str | None] = mapped_column(String(30))
    supersedes_id: Mapped[str | None] = mapped_column(String(36))
    word_count: Mapped[int | None] = mapped_column(Integer)


class Report(IdMixin, MutableMixin, Base):
    __tablename__ = "reports"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(32))
    # one_page_summary|mmi_status|medical_chronology|case_progress|decision_provenance
    format: Mapped[str] = mapped_column(String(8))  # pdf|docx|json
    file_path: Mapped[str | None] = mapped_column(String(1024))
    summary_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|ready|failed|approved
    is_approved_content: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    sha256: Mapped[str | None] = mapped_column(String(64))


class Review(IdMixin, MutableMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("review_key", name="uq_reviews_review_key"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    checkpoint: Mapped[str] = mapped_column(String(16), index=True)  # HITL-0..HITL-5, HITL-4-UR, AWAIT-DOCS
    review_key: Mapped[str] = mapped_column(String(128))  # run:checkpoint:iteration (idempotency)
    title: Mapped[str] = mapped_column(String(255))
    assigned_role: Mapped[str] = mapped_column(String(64))
    assigned_user_id: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|in_progress|submitted|expired|reassigned|cancelled
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 urgent .. 5 low
    due_at: Mapped[str | None] = mapped_column(String(30))
    claimed_by: Mapped[str | None] = mapped_column(String(36))
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    submitted_at: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    blocks_run: Mapped[bool] = mapped_column(Boolean, default=True)


class Flag(IdMixin, MutableMixin, Base):
    __tablename__ = "flags"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    flag_type: Mapped[str] = mapped_column(String(32))
    # mmi_status|rtw_limit|guideline_deviation|urgent|gap|clinical_issue|baseline_conflict
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[str | None] = mapped_column(String(36))
    ai_recommendation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    human_action: Mapped[str | None] = mapped_column(String(16))  # approved|rejected|modified
    modified_value: Mapped[str | None] = mapped_column(Text)
    acted_by: Mapped[str | None] = mapped_column(String(36))
    acted_at: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    item_key: Mapped[str | None] = mapped_column(String(255))


class Decision(IdMixin, MutableMixin, Base):
    __tablename__ = "decisions"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    review_id: Mapped[str | None] = mapped_column(String(36))
    decision_type: Mapped[str] = mapped_column(String(32))
    # treatment_authorization|disability_status|claim_trajectory|reserve_change|referral|escalation
    outcome: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    outstanding_questions: Mapped[list] = mapped_column(JSON, default=list)
    next_steps: Mapped[list] = mapped_column(JSON, default=list)
    ai_draft: Mapped[dict | None] = mapped_column(JSON)
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[str | None] = mapped_column(String(30))
    signed_off_by: Mapped[str | None] = mapped_column(String(36))
    signed_off_at: Mapped[str | None] = mapped_column(String(30))
    signoff_comments: Mapped[str | None] = mapped_column(Text)
    requires_signoff: Mapped[bool] = mapped_column(Boolean, default=False)
    record: Mapped[dict | None] = mapped_column(JSON)
    record_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|final|returned|sealed


class URDetermination(IdMixin, TimestampMixin, Base):
    __tablename__ = "ur_determinations"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    utilization_assessment_id: Mapped[str] = mapped_column(ForeignKey("utilization_assessments.id"))
    determination: Mapped[str] = mapped_column(String(16))  # certified|modified|non_certified|pended
    clinical_rationale: Mapped[str] = mapped_column(Text)
    criteria_refs: Mapped[list] = mapped_column(JSON, default=list)
    reviewer_id: Mapped[str] = mapped_column(String(36))
    determined_at: Mapped[str] = mapped_column(String(30))


class FollowUp(IdMixin, MutableMixin, Base):
    __tablename__ = "follow_ups"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    decision_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(String(36))
    due_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|done|cancelled
    created_by: Mapped[str | None] = mapped_column(String(36))


class Assignment(IdMixin, MutableMixin, Base):
    __tablename__ = "assignments"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    role_key: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(36))
    task: Mapped[str] = mapped_column(String(255))
    due_at: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(16), default="open")


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    read_at: Mapped[str | None] = mapped_column(String(30))


class CmsSyncLog(IdMixin, MutableMixin, Base):
    __tablename__ = "cms_sync_log"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    direction: Mapped[str] = mapped_column(String(8))  # outbound|inbound
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|sent|failed
    external_ref: Mapped[str | None] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
