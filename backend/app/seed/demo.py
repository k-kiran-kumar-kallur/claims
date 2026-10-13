"""Demo bootstrap: reference data, demo users and the synthetic sample claim (spec PW-PURPOSE, Appendix A)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Claim
from app.seed.reference import seed_guidelines, seed_reference, seed_users
from app.seed.sample_package import CLAIM, build_files

log = get_logger(__name__)


def seed_all(db: Session, with_sample_claim: bool = True) -> dict:
    seed_reference(db)
    users = seed_users(db)
    rules = seed_guidelines(db)
    claim_id = None
    if with_sample_claim and not db.execute(select(Claim.id).where(Claim.claim_number == CLAIM["claim_number"])).first():
        from app.core.rbac import permissions_for
        from app.services.actions import Principal
        from app.services.claims import create_claim, upload_documents

        actor = Principal(id=users["summarization_team"], email="summ@claims.example", full_name="Sam Rivera",
                          roles=["summarization_team"], permissions=permissions_for(["summarization_team"]))
        claim = create_claim(db, actor, {**CLAIM, "assigned_adjuster_id": users["claims_examiner"],
                                         "assigned_ncm_id": users["nurse_case_manager"],
                                         "assigned_reviewer_id": users["clinical_reviewer"],
                                         "assigned_supervisor_id": users["claims_supervisor"], "is_synthetic": True})
        files = build_files()
        upload_documents(db, actor, claim, [(n, d) for n, d, _ in files], {n: ch for n, _, ch in files})
        from app.models import ClaimMember
        db.add(ClaimMember(claim_id=claim.id, user_id=users["attorney"], role_key="attorney", granted_by="seed"))
        claim_id = claim.id
        log.info("sample_claim_seeded", claim_id=claim_id)
    return {"users": users, "rules": rules, "claim_id": claim_id}
