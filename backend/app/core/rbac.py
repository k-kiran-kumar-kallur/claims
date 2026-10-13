"""Role model and permission matrix (spec §3.1-§3.2)."""
from __future__ import annotations

ROLES: dict[str, tuple[str, str]] = {
    "summarization_team": ("Medical Records / Summarization Team", "Collects, organizes, deduplicates and summarizes records"),
    "claims_examiner": ("Claims Examiner / Adjuster", "Reviews summarized history; makes claim decisions (HITL-4)"),
    "nurse_case_manager": ("Nurse Case Manager", "Timeline check (HITL-1), summary review (HITL-3), RTW and care coordination"),
    "clinical_reviewer": ("Medical / Utilization / Clinical Reviewer", "Fact validation (HITL-2) and UR determinations"),
    "claims_supervisor": ("Claims Supervisor / Claims Manager", "Escalations, sign-off (HITL-5), oversight and audit"),
    "attorney": ("WC Attorney / Defence Counsel", "Read-only access to approved reports and chronology"),
    "admin": ("Platform Administrator", "Users, guidelines, prompts and models; no PHI access"),
}

PERMISSIONS: dict[str, str] = {
    "claim:create": "Create claims",
    "document:upload": "Upload documents",
    "document:view_phi": "View PHI (documents, facts, summaries)",
    "classification:edit": "Edit document classification, split documents",
    "timeline:approve": "Approve timeline (HITL-1)",
    "fact:validate": "Validate facts (HITL-2)",
    "summary:edit": "Edit summaries",
    "summary:approve": "Approve summaries (HITL-3)",
    "decision:make": "Make claim decisions (HITL-4)",
    "ur:determine": "Record UR determinations (HITL-4 UR)",
    "decision:signoff": "Supervisor sign-off (HITL-5)",
    "report:export": "Export reports",
    "audit:view": "View audit trail",
    "config:manage": "Manage users, guidelines, prompts, models, settings",
    "run:start": "Start / resume workflow runs",
    "run:manage": "Retry runs, reassign reviews",
    "baseline:confirm": "Confirm claim baseline (HITL-0)",
    "chronology:edit": "Edit chronology rows",
    "care:coordinate": "Provider contacts, gap resolution, document requests",
    "flag:act": "Act on AI flags",
}

_ALL_PHI = ["summarization_team", "claims_examiner", "nurse_case_manager", "clinical_reviewer", "claims_supervisor", "attorney"]

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "summarization_team": {"claim:create", "document:upload", "document:view_phi", "classification:edit", "summary:edit",
                           "report:export", "run:start", "baseline:confirm", "chronology:edit"},
    "claims_examiner": {"claim:create", "document:upload", "document:view_phi", "decision:make", "report:export",
                        "run:start", "baseline:confirm", "care:coordinate", "flag:act"},
    "nurse_case_manager": {"document:upload", "document:view_phi", "classification:edit", "timeline:approve",
                           "summary:edit", "summary:approve", "report:export", "care:coordinate"},
    "clinical_reviewer": {"document:view_phi", "fact:validate", "ur:determine", "report:export", "flag:act"},
    "claims_supervisor": {"claim:create", "document:upload", "document:view_phi", "classification:edit",
                          "timeline:approve", "fact:validate", "summary:edit", "summary:approve", "decision:make",
                          "decision:signoff", "report:export", "audit:view", "run:start", "run:manage",
                          "baseline:confirm", "chronology:edit", "care:coordinate", "flag:act"},
    "attorney": {"document:view_phi", "report:export"},  # approved content only (enforced in services)
    "admin": {"audit:view", "config:manage", "run:manage"},  # metadata only, no PHI
}

# HITL checkpoint -> roles allowed to act on it (spec §6.5)
CHECKPOINT_ROLES: dict[str, set[str]] = {
    "HITL-0": {"claims_examiner", "summarization_team", "claims_supervisor"},
    "HITL-1": {"nurse_case_manager", "claims_supervisor"},
    "HITL-2": {"clinical_reviewer", "claims_supervisor"},
    "HITL-3": {"nurse_case_manager", "claims_supervisor"},
    "HITL-4": {"claims_examiner", "claims_supervisor"},
    "HITL-4-UR": {"clinical_reviewer"},  # SoD rule 2: only clinical reviewers record UR determinations
    "HITL-5": {"claims_supervisor"},
    "AWAIT-DOCS": {"claims_examiner", "nurse_case_manager", "summarization_team", "claims_supervisor"},
}

CHECKPOINT_PRIMARY_ROLE: dict[str, str] = {
    "HITL-0": "claims_examiner", "HITL-1": "nurse_case_manager", "HITL-2": "clinical_reviewer",
    "HITL-3": "nurse_case_manager", "HITL-4": "claims_examiner", "HITL-4-UR": "clinical_reviewer",
    "HITL-5": "claims_supervisor", "AWAIT-DOCS": "claims_examiner",
}


def permissions_for(roles: list[str] | set[str]) -> set[str]:
    perms: set[str] = set()
    for r in roles:
        perms |= ROLE_PERMISSIONS.get(r, set())
    return perms


def has_phi_access(roles: list[str] | set[str]) -> bool:
    return any(r in _ALL_PHI for r in roles)
