"""Claims and document intake services (spec §12.2-§12.3) with claim-level access scoping (§15.2)."""
from __future__ import annotations

import re

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.ids import now_iso, uuid7
from app.core.logging import register_phi_terms
from app.core.security import decrypt_str, encrypt_str
from app.models import Claim, Claimant, ClaimMember, Document, Report
from app.services import audit, file_store
from app.services.actions import Principal
from app.tools.ingest import ingest_tool

CLAIM_NUMBER_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,40}$")


def scoped_claims(db: Session, user: Principal) -> Select:
    """Deny by default: claims visible to the user (assignment, membership or team; supervisors see their team)."""
    q = select(Claim)
    roles = set(user.roles)
    if roles <= {"admin"}:
        return q.where(Claim.id == "__none__")  # admin: no PHI access
    member_ids = select(ClaimMember.claim_id).where(ClaimMember.user_id == user.id)
    if roles == {"attorney"}:
        approved = select(Report.claim_id).where(Report.is_approved_content.is_(True), Report.status == "approved")
        return q.where(Claim.id.in_(member_ids), Claim.id.in_(approved))
    if "claims_supervisor" in roles:
        return q.where(or_(Claim.team == user.team, Claim.id.in_(member_ids)))
    return q.where(or_(Claim.team == user.team, Claim.id.in_(member_ids), Claim.assigned_adjuster_id == user.id,
                       Claim.assigned_ncm_id == user.id, Claim.assigned_reviewer_id == user.id))


def get_claim_for(db: Session, user: Principal, claim_id: str) -> Claim:
    claim = db.execute(scoped_claims(db, user).where(Claim.id == claim_id)).scalar_one_or_none()
    if claim is None:
        if db.get(Claim, claim_id) is None:
            raise NotFound("Claim not found")
        raise Forbidden("You do not have access to this claim")
    return claim


def claimant_view(db: Session, claim: Claim) -> dict:
    cl = db.get(Claimant, claim.claimant_id)
    name = decrypt_str(cl.full_name_enc) if cl else None
    register_phi_terms(name)
    dob = decrypt_str(cl.dob_enc) if cl else None
    return {"full_name": name, "dob": dob, "ssn_last4": "***" + (decrypt_str(cl.ssn_last4_enc) or "")[-1:] if cl and cl.ssn_last4_enc else None,
            "contact": decrypt_str(cl.contact_enc) if cl else None}


def create_claim(db: Session, user: Principal, data: dict) -> Claim:
    number = (data.get("claim_number") or "").strip().upper()
    if not CLAIM_NUMBER_RE.match(number):
        raise BadRequest("claim_number must be 4-41 characters of A-Z, 0-9 and '-'")
    if db.execute(select(Claim.id).where(Claim.claim_number == number)).first():
        raise Conflict(f"Claim {number} already exists")
    c = data.get("claimant") or {}
    if not c.get("full_name"):
        raise BadRequest("claimant.full_name is required")
    claimant = Claimant(id=uuid7(), full_name_enc=encrypt_str(c["full_name"]), dob_enc=encrypt_str(c.get("dob")),
                        ssn_last4_enc=encrypt_str(c.get("ssn_last4")), contact_enc=encrypt_str(c.get("contact")))
    db.add(claimant)
    register_phi_terms(c["full_name"])
    claim = Claim(id=uuid7(), claim_number=number, claimant_id=claimant.id, employer_name=data.get("employer_name"),
                  employer_contact=data.get("employer_contact"), insurer=data.get("insurer"), tpa=data.get("tpa"),
                  date_of_injury=data.get("date_of_injury"), jurisdiction_state=(data.get("jurisdiction_state") or "").upper() or None,
                  body_parts=data.get("body_parts") or [], mechanism_of_injury=data.get("mechanism_of_injury"),
                  assigned_adjuster_id=data.get("assigned_adjuster_id"), assigned_ncm_id=data.get("assigned_ncm_id"),
                  assigned_reviewer_id=data.get("assigned_reviewer_id"), assigned_supervisor_id=data.get("assigned_supervisor_id"),
                  adjuster_name=data.get("adjuster_name"), litigated=bool(data.get("litigated")),
                  is_synthetic=bool(data.get("is_synthetic")), team=user.team, created_by=user.id, status="open", baseline={})
    db.add(claim)
    db.flush()
    db.add(ClaimMember(claim_id=claim.id, user_id=user.id, role_key=user.roles[0] if user.roles else "user", granted_by=user.id))
    audit.record(db, action="claim.create", entity_type="claim", entity_id=claim.id, claim_id=claim.id, actor_id=user.id,
                 after={"claim_number": number, "date_of_injury": claim.date_of_injury}, ip=user.ip, user_agent=user.user_agent)
    return claim


def upload_documents(db: Session, user: Principal, claim: Claim, files: list[tuple[str, bytes]],
                     channels: dict[str, str] | str = "upload") -> list[Document]:
    if not files:
        raise BadRequest("No files uploaded")
    out = []
    for name, data in files:
        safe_name = re.sub(r"[^\w .()\[\]-]", "_", name)[:255] or "upload.bin"
        meta = ingest_tool(data, safe_name)
        dup = db.execute(select(Document).where(Document.claim_id == claim.id, Document.sha256 == meta["sha256"],
                                                Document.parent_document_id.is_(None))).scalars().first()
        channel = channels.get(name, "upload") if isinstance(channels, dict) else channels
        if channel not in ("fax", "mail", "email", "upload", "cms"):
            raise BadRequest("source_channel must be fax, mail, email, upload or cms")
        doc = Document(id=uuid7(), claim_id=claim.id, source_channel=channel, original_filename=safe_name,
                       mime_type=meta["mime_type"], sha256=meta["sha256"], size_bytes=meta["size_bytes"],
                       status="duplicate" if dup else "received", duplicate_of_id=dup.id if dup else None,
                       status_reason="identical file already uploaded" if dup else None, received_at=now_iso(),
                       uploaded_by=user.id)
        doc.storage_path = file_store.put(file_store.original_path(claim.id, doc.id), data)
        db.add(doc)
        audit.record(db, action="document.upload", entity_type="document", entity_id=doc.id, claim_id=claim.id,
                     actor_id=user.id, after={"filename": safe_name, "mime": meta["mime_type"], "sha256": meta["sha256"],
                                              "duplicate_of": dup.id if dup else None}, ip=user.ip, user_agent=user.user_agent)
        out.append(doc)
    return out
