"""Organization and clinical content tables (spec §11.2)."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, MutableMixin, TimestampMixin


class Provider(IdMixin, MutableMixin, Base):
    __tablename__ = "providers"
    name: Mapped[str] = mapped_column(String(255), index=True)
    specialty: Mapped[str | None] = mapped_column(String(128))
    facility: Mapped[str | None] = mapped_column(String(255))
    npi: Mapped[str | None] = mapped_column(String(16))
    phone: Mapped[str | None] = mapped_column(String(32))
    fax: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)


class ClaimProvider(Base):
    __tablename__ = "claim_providers"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str | None] = mapped_column(String(64))
    first_seen: Mapped[str | None] = mapped_column(String(10))
    last_seen: Mapped[str | None] = mapped_column(String(10))


class ProviderContact(IdMixin, TimestampMixin, Base):
    __tablename__ = "provider_contacts"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"))
    contact_type: Mapped[str] = mapped_column(String(16))  # call|fax|email|meeting
    purpose: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    contacted_by: Mapped[str] = mapped_column(String(36))
    contacted_at: Mapped[str] = mapped_column(String(30))
    follow_up_date: Mapped[str | None] = mapped_column(String(10))


class RtwStatus(IdMixin, TimestampMixin, Base):
    __tablename__ = "rtw_status_history"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    effective_date: Mapped[str | None] = mapped_column(String(10))
    work_status: Mapped[str] = mapped_column(String(16))  # full_duty|modified_duty|ttd|tpd|off_work
    restrictions: Mapped[list] = mapped_column(JSON, default=list)
    source_fact_id: Mapped[str | None] = mapped_column(String(36))
    expected_next_change: Mapped[str | None] = mapped_column(String(10))
    employer_accommodation: Mapped[str | None] = mapped_column(Text)


class Episode(IdMixin, TimestampMixin, Base):
    __tablename__ = "episodes"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    label: Mapped[str] = mapped_column(String(255))
    episode_type: Mapped[str | None] = mapped_column(String(64))
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    provider_ids: Mapped[list] = mapped_column(JSON, default=list)
    timeline_version: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    edited_by: Mapped[str | None] = mapped_column(String(36))


class DocumentIndex(TimestampMixin, Base):
    __tablename__ = "document_index"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    timeline_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    sort_order: Mapped[int] = mapped_column(Integer)


class TimelineGap(IdMixin, MutableMixin, Base):
    __tablename__ = "timeline_gaps"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    gap_type: Mapped[str] = mapped_column(String(32))
    # missing_referenced_record|treatment_interval|visit_count_mismatch|date_anomaly
    description: Mapped[str] = mapped_column(Text)
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|explained|requested|resolved
    resolution_note: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # citation dicts
    timeline_version: Mapped[int] = mapped_column(Integer, default=1)
    dedup_key: Mapped[str | None] = mapped_column(String(255))


class ExtractedFact(IdMixin, TimestampMixin, Base):
    __tablename__ = "extracted_facts"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    episode_id: Mapped[str | None] = mapped_column(String(36))
    fact_type: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str | None] = mapped_column(String(255))
    value: Mapped[dict] = mapped_column(JSON)
    normalized_value: Mapped[dict | None] = mapped_column(JSON)
    effective_date: Mapped[str | None] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    extractor: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(16))
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|auto_verified|needs_review|validated|edited|rejected
    validation_notes: Mapped[list] = mapped_column(JSON, default=list)
    validated_by: Mapped[str | None] = mapped_column(String(36))
    validated_at: Mapped[str | None] = mapped_column(String(30))
    supersedes_fact_id: Mapped[str | None] = mapped_column(String(36))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    item_key: Mapped[str | None] = mapped_column(String(255), index=True)  # idempotency key


class Citation(IdMixin, TimestampMixin, Base):
    __tablename__ = "citations"
    owner_type: Mapped[str] = mapped_column(String(32), default="fact")
    # fact|summary|finding|chronology|issue|assessment|baseline|milestone|flag
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    fact_id: Mapped[str | None] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"))
    page_number: Mapped[int] = mapped_column(Integer)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    match_score: Mapped[float | None] = mapped_column(Float)


class Discrepancy(IdMixin, MutableMixin, Base):
    __tablename__ = "discrepancies"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    fact_ids: Mapped[list] = mapped_column(JSON, default=list)
    discrepancy_type: Mapped[str] = mapped_column(String(32), default="consistency")
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|resolved
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(36))


class Milestone(IdMixin, MutableMixin, Base):
    __tablename__ = "milestones"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    milestone_type: Mapped[str] = mapped_column(String(32))
    milestone_date: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    impact: Mapped[list] = mapped_column(JSON, default=list)  # diagnosis|treatment|prognosis|function|work_status
    impact_narrative: Mapped[str | None] = mapped_column(Text)  # cause -> effect (PW-5.2)
    work_capacity_link: Mapped[str | None] = mapped_column(Text)
    is_turning_point: Mapped[bool] = mapped_column(Boolean, default=False)
    fact_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|confirmed|dismissed
    item_key: Mapped[str | None] = mapped_column(String(255))


class ClinicalIssue(IdMixin, MutableMixin, Base):
    __tablename__ = "clinical_issues"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    issue_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    suggested_action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|in_progress|resolved|dismissed
    owner_id: Mapped[str | None] = mapped_column(String(36))


class UtilizationAssessment(IdMixin, MutableMixin, Base):
    __tablename__ = "utilization_assessments"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    request_description: Mapped[str] = mapped_column(Text)
    request_type: Mapped[str] = mapped_column(String(16))  # mri|esi|pt_extension|surgery|medication|other
    requesting_provider: Mapped[str | None] = mapped_column(String(255))
    request_date: Mapped[str | None] = mapped_column(String(10))
    necessity_indicators: Mapped[list] = mapped_column(JSON, default=list)
    appropriateness: Mapped[str | None] = mapped_column(Text)
    progression: Mapped[str | None] = mapped_column(Text)
    barriers: Mapped[list] = mapped_column(JSON, default=list)
    unresolved_questions: Mapped[list] = mapped_column(JSON, default=list)
    guideline_rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    ai_recommendation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="ai_draft")  # ai_draft|determined
