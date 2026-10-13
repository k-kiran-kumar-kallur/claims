"""Reference data: roles, permissions, demo users, sample guideline rules and code tables.

GUIDELINE CONTENT NOTICE: the rules below are a small, curated SAMPLE rule set written for the PoC.  They are NOT
licensed ODG (MCG Health) or ACOEM content and must be replaced by licensed guideline content before production use
(spec §19.2).  Code descriptions are short paraphrases; CPT is an AMA-licensed code set.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.ids import uuid7
from app.core.rbac import PERMISSIONS, ROLE_PERMISSIONS, ROLES
from app.core.security import hash_password
from app.models import (
    AppSetting,
    CodeEntry,
    GuidelineRule,
    GuidelineSource,
    Permission,
    PromptTemplate,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.tools.retrieval import to_blob

DEMO_USERS = [
    ("summ@claims.example", "Sam Rivera", ["summarization_team"]),
    ("examiner@claims.example", "Jennifer Hartwell", ["claims_examiner"]),
    ("ncm@claims.example", "Nora Castillo, RN", ["nurse_case_manager"]),
    ("reviewer@claims.example", "Dr. Lena Brooks", ["clinical_reviewer"]),
    ("supervisor@claims.example", "Marcus Bell", ["claims_supervisor"]),
    ("attorney@claims.example", "Alex Morgan, Esq.", ["attorney"]),
    ("admin@claims.example", "Platform Admin", ["admin"]),
]

ICD10 = [
    ("S39.012A", "Strain of muscle, fascia and tendon of lower back, initial encounter", "lumbar spine"),
    ("S39.012", "Strain of muscle, fascia and tendon of lower back", "lumbar spine"),
    ("M54.32", "Sciatica, left side", "lumbar spine"), ("M54.31", "Sciatica, right side", "lumbar spine"),
    ("M54.16", "Radiculopathy, lumbar region", "lumbar spine"), ("M54.17", "Radiculopathy, lumbosacral region", "lumbar spine"),
    ("M54.5", "Low back pain", "lumbar spine"), ("M54.50", "Low back pain, unspecified", "lumbar spine"),
    ("M51.16", "Intervertebral disc disorders with radiculopathy, lumbar region", "lumbar spine"),
    ("M51.26", "Other intervertebral disc displacement, lumbar region", "lumbar spine"),
    ("M51.27", "Other intervertebral disc displacement, lumbosacral region", "lumbar spine"),
    ("M96.1", "Postlaminectomy syndrome, not elsewhere classified", "lumbar spine"),
    ("Z98.890", "Other specified postprocedural states", None),
    ("M75.100", "Rotator cuff tear or rupture, unspecified shoulder, not traumatic", "shoulder"),
    ("S83.209A", "Tear of unspecified meniscus, current injury, unspecified knee, initial encounter", "knee"),
    ("S13.4XXA", "Sprain of ligaments of cervical spine, initial encounter", "cervical spine"),
    ("G56.00", "Carpal tunnel syndrome, unspecified upper limb", "wrist/hand"),
]
CPT = [  # short paraphrased descriptors (CPT is licensed by the AMA)
    ("99204", "New patient office visit, moderate complexity"), ("99214", "Established patient office visit, moderate complexity"),
    ("99283", "Emergency department visit, moderate"), ("72148", "MRI lumbar spine without contrast"),
    ("72100", "X-ray lumbar spine, 2-3 views"), ("63030", "Lumbar laminotomy with discectomy, single interspace"),
    ("63047", "Lumbar laminectomy/decompression, single segment"), ("22612", "Lumbar arthrodesis, posterior"),
    ("62323", "Lumbar epidural injection with imaging guidance"), ("97110", "Therapeutic exercise, each 15 minutes"),
    ("97140", "Manual therapy techniques, each 15 minutes"), ("97161", "PT evaluation, low complexity"),
    ("97162", "PT evaluation, moderate complexity"), ("97163", "PT evaluation, high complexity"),
    ("97750", "Physical performance test (e.g. FCE), each 15 minutes"), ("97545", "Work hardening/conditioning, initial 2 hours"),
    ("97546", "Work hardening/conditioning, each additional hour"),
]

SAMPLE_RULES = [
    # (rule_code, title, category, body_part, dx, px, keywords, criteria, max_visits, max_days, prerequisites, recommendation)
    ("SMP-LB-PT-POSTSURG", "Physical therapy after lumbar discectomy/laminectomy", "therapy", "lumbar spine",
     ["M51.16", "M51.26", "M54.16", "M96.1"], ["63030", "63047", "97110", "97140"],
     ["physical therapy", "pt", "post-surgical", "discectomy", "post-operative", "therapy visits"],
     "Post-surgical physical therapy after discectomy/laminectomy: up to 16 visits over 8 weeks. Continuation beyond the "
     "initial course requires documented objective functional improvement (e.g. ODI, ROM, lifting capacity). Transition to a "
     "home exercise program is expected.", 16, 56, ["documented objective functional improvement for continuation"], "recommended"),
    ("SMP-LB-PT-NONSURG", "Physical therapy for lumbar sprain/strain or radiculopathy (non-surgical)", "therapy", "lumbar spine",
     ["S39.012A", "M54.16", "M54.32", "M54.5"], ["97110", "97140"], ["physical therapy", "strain", "sprain", "radiculopathy"],
     "Non-surgical low back conditions: up to 10 visits over 8 weeks with fading frequency and active self-directed home therapy.",
     10, 56, ["functional improvement after 6 visits"], "recommended"),
    ("SMP-LB-OPIOID-ACUTE", "Opioids for acute low back or post-operative pain", "medication", None, [], [],
     ["opioid", "oxycodone", "hydrocodone", "tramadol", "narcotic", "post-operative pain"],
     "Short-acting opioids may be used for acute or post-operative pain for up to 14 days. Use beyond this period requires "
     "documented functional improvement, a treatment agreement, urine drug screening and a taper plan.", None, 14,
     ["functional improvement", "treatment agreement", "urine drug screening", "taper plan"], "conditional"),
    ("SMP-LB-MUSCLE-RELAX", "Muscle relaxants for acute low back pain", "medication", "lumbar spine", [], [],
     ["cyclobenzaprine", "muscle relaxant", "methocarbamol"],
     "Muscle relaxants: short course only, generally no more than 2-3 weeks for acute exacerbations.", None, 21, [], "conditional"),
    ("SMP-LB-GABAPENTIN", "Anti-epileptic drugs for neuropathic/radicular pain", "medication", "lumbar spine", ["M54.16", "M51.16"], [],
     ["gabapentin", "pregabalin", "neuropathic"], "Recommended as an option for radicular pain; continue only with documented benefit.",
     None, None, ["documented benefit"], "recommended"),
    ("SMP-LB-MRI", "MRI of the lumbar spine", "imaging", "lumbar spine", ["M54.16", "M54.32", "S39.012A"], ["72148"],
     ["mri", "imaging", "lumbar mri"],
     "Lumbar MRI is indicated after at least 4-6 weeks of conservative care with persistent radiculopathy, or earlier when "
     "red flags or a progressive neurological deficit are present.", None, None,
     ["red flags or progressive neurological deficit", "or 4-6 weeks of failed conservative care"], "conditional"),
    ("SMP-LB-DISCECTOMY", "Lumbar discectomy / microdiscectomy", "surgery", "lumbar spine", ["M51.16", "M51.26"], ["63030", "63047"],
     ["discectomy", "microdiscectomy", "laminotomy", "surgery"],
     "Discectomy is indicated for radiculopathy with concordant imaging after 6 weeks of failed conservative care, or earlier "
     "with a progressive motor deficit or cauda equina syndrome.", None, None,
     ["imaging concordant with radiculopathy", "6 weeks conservative care OR progressive motor deficit"], "conditional"),
    ("SMP-LB-WORK-HARDENING", "Work hardening / work conditioning", "therapy", "lumbar spine", [], ["97545", "97546"],
     ["work hardening", "work conditioning", "return to work", "fce"],
     "Work hardening is an option when an FCE documents capacity below job demands after a plateau in conventional therapy, "
     "with a defined return-to-work goal; up to 10 sessions over 4 weeks.", 10, 28,
     ["FCE showing deficit vs job demands", "plateau in conventional therapy", "defined RTW goal"], "conditional"),
    ("SMP-LB-ESI", "Epidural steroid injections (lumbar)", "injection", "lumbar spine", ["M54.16", "M51.16"], ["62323"],
     ["epidural", "esi", "injection"], "ESI is an option for radiculopathy confirmed by exam and imaging after failed conservative "
     "care; repeat injections require at least 50% pain relief for 6-8 weeks. Maximum 2 injections per region per year.",
     2, None, ["radiculopathy on exam and imaging", "failed conservative care"], "conditional"),
    ("SMP-LB-FUSION", "Lumbar fusion", "surgery", "lumbar spine", [], ["22612"], ["fusion", "arthrodesis"],
     "Fusion is not recommended for non-specific low back pain or for disc herniation without instability.", None, None,
     ["instability or spondylolisthesis"], "not_recommended"),
    ("SMP-DD-DISCECTOMY", "Expected disability duration after lumbar discectomy (medium/heavy work)", "disability_duration",
     "lumbar spine", ["M51.16", "M51.26"], ["63030"], ["disability duration", "return to work", "discectomy"],
     "Expected time off regular work after lumbar discectomy for medium or heavy work: up to 84 days; modified duty earlier.",
     None, 84, [], "recommended"),
    ("SMP-DD-STRAIN", "Expected disability duration for lumbar sprain/strain", "disability_duration", "lumbar spine",
     ["S39.012A", "M54.5"], [], ["disability duration", "strain"],
     "Expected disability for lumbar strain with medium work: up to 28 days.", None, 28, [], "recommended"),
]


def seed_reference(db: Session) -> None:
    for key, desc in PERMISSIONS.items():
        if db.get(Permission, key) is None:
            db.add(Permission(permission_key=key, description=desc))
    roles = {}
    for key, (name, desc) in ROLES.items():
        role = db.execute(select(Role).where(Role.key == key)).scalar_one_or_none()
        if role is None:
            role = Role(id=uuid7(), key=key, name=name, description=desc)
            db.add(role)
        roles[key] = role
    db.flush()
    for key, perms in ROLE_PERMISSIONS.items():
        existing = set(db.execute(select(RolePermission.permission_key).where(RolePermission.role_id == roles[key].id)).scalars())
        for p in perms - existing:
            db.add(RolePermission(role_id=roles[key].id, permission_key=p))
    for system, rows in (("icd10cm", ICD10), ("cpt", [(c, d, None) for c, d in CPT])):
        for code, desc, bp in rows:
            if db.get(CodeEntry, (system, code)) is None:
                db.add(CodeEntry(code_system=system, code=code, description=desc, body_part=bp))
    if db.get(AppSetting, "thresholds") is None:
        db.add(AppSetting(key="thresholds", value={
            "CONFIDENCE_THRESHOLD_BASELINE": settings.CONFIDENCE_THRESHOLD_BASELINE,
            "CONFIDENCE_THRESHOLD_CLASSIFICATION": settings.CONFIDENCE_THRESHOLD_CLASSIFICATION,
            "CONFIDENCE_THRESHOLD_FACT": settings.CONFIDENCE_THRESHOLD_FACT,
            "RISK_ESCALATION_THRESHOLD": settings.RISK_ESCALATION_THRESHOLD,
            "TREATMENT_GAP_DAYS": settings.TREATMENT_GAP_DAYS}))
    from app.agents.prompts.registry import DEFAULTS
    for p in DEFAULTS.values():
        if not db.execute(select(PromptTemplate.id).where(PromptTemplate.name == p.name)).first():
            db.add(PromptTemplate(id=uuid7(), name=p.name, version=p.version, template=p.template, system=p.system,
                                  model_tier=p.tier, temperature=p.temperature, is_active=True, created_by="seed"))
    db.flush()


def seed_users(db: Session) -> dict[str, str]:
    ids = {}
    roles = {r.key: r for r in db.execute(select(Role)).scalars()}
    for email, name, rkeys in DEMO_USERS:
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is None:
            u = User(id=uuid7(), email=email, full_name=name, password_hash=hash_password(settings.DEMO_PASSWORD))
            db.add(u)
            db.flush()
            for rk in rkeys:
                db.add(UserRole(user_id=u.id, role_id=roles[rk].id, granted_by="seed"))
        ids[rkeys[0]] = u.id
    db.flush()
    return ids


def seed_guidelines(db: Session) -> int:
    if db.execute(select(GuidelineSource.id)).first():
        return 0
    src = GuidelineSource(id=uuid7(), name="Sample low-back rule set (PoC)", edition="v1 - not licensed ODG/ACOEM content",
                          jurisdiction="ALL", license_ref="Curated sample for demonstration; replace with licensed content",
                          effective_from="2024-01-01")
    db.add(src)
    db.flush()
    return import_rules(db, src.id, [dict(zip(["rule_code", "title", "category", "body_part", "diagnosis_codes", "procedure_codes",
                                               "keywords", "criteria_text", "max_visits", "max_duration_days", "prerequisites",
                                               "recommendation"], r, strict=True)) for r in SAMPLE_RULES])


def import_rules(db: Session, source_id: str, rules: list[dict]) -> int:
    from app.agents.heuristics import local_embedding

    n = 0
    for r in rules:
        existing = db.execute(select(GuidelineRule).where(GuidelineRule.source_id == source_id, GuidelineRule.rule_code == r["rule_code"])).scalar_one_or_none()
        row = existing or GuidelineRule(id=uuid7(), source_id=source_id, rule_code=r["rule_code"])
        for k in ("title", "category", "body_part", "diagnosis_codes", "procedure_codes", "keywords", "criteria_text",
                  "max_visits", "max_duration_days", "prerequisites", "recommendation"):
            if k in r:
                setattr(row, k, r[k])
        row.embedding = to_blob(local_embedding(f"{row.title} {row.criteria_text}"))
        if existing is None:
            db.add(row)
        db.flush()
        db.execute(text("DELETE FROM guideline_rules_fts WHERE rule_id = :r"), {"r": row.id})
        db.execute(text("INSERT INTO guideline_rules_fts(text, rule_id) VALUES (:t, :r)"),
                   {"t": f"{row.title} {row.criteria_text} {' '.join(row.keywords or [])}", "r": row.id})
        n += 1
    return n
