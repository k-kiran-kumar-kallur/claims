"""Claims, documents, pages and classification tables (spec §11.2 'Claims and documents')."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, MutableMixin, TimestampMixin


class Claimant(IdMixin, MutableMixin, Base):
    __tablename__ = "claimants"
    full_name_enc: Mapped[str | None] = mapped_column(Text)
    dob_enc: Mapped[str | None] = mapped_column(Text)
    ssn_last4_enc: Mapped[str | None] = mapped_column(Text)
    contact_enc: Mapped[str | None] = mapped_column(Text)


class Claim(IdMixin, MutableMixin, Base):
    __tablename__ = "claims"
    claim_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    claimant_id: Mapped[str] = mapped_column(ForeignKey("claimants.id"))
    employer_name: Mapped[str | None] = mapped_column(String(255))
    employer_contact: Mapped[str | None] = mapped_column(String(255))
    insurer: Mapped[str | None] = mapped_column(String(255))
    tpa: Mapped[str | None] = mapped_column(String(255))
    date_of_injury: Mapped[str | None] = mapped_column(String(10))
    jurisdiction_state: Mapped[str | None] = mapped_column(String(2))
    body_parts: Mapped[list] = mapped_column(JSON, default=list)
    mechanism_of_injury: Mapped[str | None] = mapped_column(Text)
    assigned_adjuster_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    assigned_ncm_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    assigned_reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    assigned_supervisor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    adjuster_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|in_review|decided|closed
    baseline_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)  # extracted fields w/ confidence+citations
    time_window_start: Mapped[str | None] = mapped_column(String(10))
    time_window_end: Mapped[str | None] = mapped_column(String(10))
    risk_score: Mapped[float | None] = mapped_column(Float)
    complexity: Mapped[str | None] = mapped_column(String(20))
    litigated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    team: Mapped[str] = mapped_column(String(64), default="default")
    current_stage: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(36))


class ClaimMember(TimestampMixin, Base):
    """Claim-level access scope (spec §15.2: assignment or team membership)."""
    __tablename__ = "claim_members"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_key: Mapped[str] = mapped_column(String(64))
    granted_by: Mapped[str | None] = mapped_column(String(36))


class ReviewContext(IdMixin, MutableMixin, Base):
    __tablename__ = "review_contexts"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    review_goals: Mapped[list] = mapped_column(JSON, default=list)
    clinical_question: Mapped[str | None] = mapped_column(Text)
    required_evidence: Mapped[list] = mapped_column(JSON, default=list)
    applicable_guidelines: Mapped[list] = mapped_column(JSON, default=list)
    state_rules: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(16), default="agent")  # agent|user
    created_by: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class Document(IdMixin, MutableMixin, Base):
    __tablename__ = "documents"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    source_channel: Mapped[str] = mapped_column(String(16), default="upload")  # fax|mail|email|upload|cms
    original_filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    stream: Mapped[str | None] = mapped_column(String(32))
    parent_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    is_container: Mapped[bool] = mapped_column(Boolean, default=False)  # packet / email that was split
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="received")
    # received|processed|split|duplicate|noise|failed
    status_reason: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(512))
    received_at: Mapped[str | None] = mapped_column(String(30))
    uploaded_by: Mapped[str | None] = mapped_column(String(36))
    ingest_run_id: Mapped[str | None] = mapped_column(String(36))
    duplicate_of_id: Mapped[str | None] = mapped_column(String(36))


class Page(IdMixin, TimestampMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_pages_doc_page"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    file_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))  # physical file owner
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    source_page_number: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str | None] = mapped_column(String(1024))
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text, default="")
    text_source: Mapped[str] = mapped_column(String(8), default="native")  # native|ocr|none
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    text_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    simhash: Mapped[str | None] = mapped_column(String(20))
    is_blank: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate_of: Mapped[str | None] = mapped_column(String(36))


class PageLine(IdMixin, Base):
    __tablename__ = "page_lines"
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    bbox: Mapped[list | None] = mapped_column(JSON)  # [x0, y0, x1, y1] normalised 0..1


class PageChunk(IdMixin, TimestampMixin, Base):
    __tablename__ = "page_chunks"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"))
    page_number: Mapped[int] = mapped_column(Integer)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(128))


class DocumentClassification(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_classifications"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    provider_name: Mapped[str | None] = mapped_column(String(255))
    provider_specialty: Mapped[str | None] = mapped_column(String(128))
    facility: Mapped[str | None] = mapped_column(String(255))
    npi: Mapped[str | None] = mapped_column(String(16))
    service_date_start: Mapped[str | None] = mapped_column(String(10))
    service_date_end: Mapped[str | None] = mapped_column(String(10))
    encounter_type: Mapped[str | None] = mapped_column(String(64))
    body_parts: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    icd10_codes: Mapped[list] = mapped_column(JSON, default=list)
    cpt_codes: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text)
    classified_by: Mapped[str] = mapped_column(String(36), default="agent")
    reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False)


class DocumentRequest(IdMixin, MutableMixin, Base):
    __tablename__ = "document_requests"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    requested_from: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|sent|received|cancelled
    due_date: Mapped[str | None] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(16), default="agent")
    created_by: Mapped[str | None] = mapped_column(String(36))
    dedup_key: Mapped[str | None] = mapped_column(String(255))


class DedupGroup(IdMixin, TimestampMixin, Base):
    __tablename__ = "dedup_groups"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    canonical_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    member_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    method: Mapped[str] = mapped_column(String(8))  # exact|near
    similarity: Mapped[float] = mapped_column(Float, default=1.0)
