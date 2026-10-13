"""Guideline store and code tables (spec §11.2 'Guidelines', §8 code_lookup_tool)."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, MutableMixin, TimestampMixin


class GuidelineSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "guideline_sources"
    name: Mapped[str] = mapped_column(String(128))
    edition: Mapped[str | None] = mapped_column(String(64))
    jurisdiction: Mapped[str | None] = mapped_column(String(8))
    license_ref: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[str | None] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GuidelineRule(IdMixin, MutableMixin, Base):
    __tablename__ = "guideline_rules"
    source_id: Mapped[str] = mapped_column(ForeignKey("guideline_sources.id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32), default="treatment")
    # treatment|therapy|medication|imaging|surgery|injection|disability_duration
    body_part: Mapped[str | None] = mapped_column(String(64))
    diagnosis_codes: Mapped[list] = mapped_column(JSON, default=list)
    procedure_codes: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    criteria_text: Mapped[str] = mapped_column(Text)
    max_visits: Mapped[int | None] = mapped_column(Integer)
    max_duration_days: Mapped[int | None] = mapped_column(Integer)
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(String(16))  # recommended|not_recommended|conditional
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GuidelineFinding(IdMixin, MutableMixin, Base):
    __tablename__ = "guideline_findings"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    finding_type: Mapped[str] = mapped_column(String(32))
    # off_guideline_request|excessive_duration|stalled_recovery|unusual_escalation|compliant|no_applicable_guideline
    severity: Mapped[str] = mapped_column(String(8), default="medium")
    title: Mapped[str] = mapped_column(String(255))
    treatment_ref: Mapped[str | None] = mapped_column(String(36))
    guideline_rule_id: Mapped[str | None] = mapped_column(ForeignKey("guideline_rules.id"))
    rule_excerpt: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # actual vs guideline values
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|accepted|dismissed
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_reason: Mapped[str | None] = mapped_column(Text)
    item_key: Mapped[str | None] = mapped_column(String(255))


class CodeEntry(Base):
    __tablename__ = "code_entries"
    code_system: Mapped[str] = mapped_column(String(16), primary_key=True)  # icd10cm|cpt|hcpcs
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    body_part: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(64))
