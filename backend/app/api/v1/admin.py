"""Audit, monitoring, health and admin configuration (spec §12.9, §16)."""
from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import Paging, envelope, get_db, require_permission
from app.api.v1.claims import clinical_access
from app.config import settings
from app.core.errors import BadRequest, NotFound
from app.core.ids import parse_iso, to_iso, utcnow, uuid7
from app.models import (
    AgentRun,
    AgentStep,
    AppSetting,
    AuditLog,
    Claim,
    ExtractedFact,
    Flag,
    GuidelineRule,
    GuidelineSource,
    Job,
    LlmCall,
    Page,
    PromptTemplate,
    Review,
    User,
    WorkerHeartbeat,
)
from app.services import audit, file_store
from app.services.actions import Principal

router = APIRouter(tags=["admin"])


def _audit_row(a: AuditLog, names: dict, metadata_only: bool) -> dict:
    out = {"id": a.id, "ts": a.ts, "actor_type": a.actor_type, "actor_id": a.actor_id, "actor_name": names.get(a.actor_id, a.actor_id),
           "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "claim_id": a.claim_id,
           "correlation_id": a.correlation_id, "ip": a.ip, "hash": a.hash[:16]}
    if not metadata_only:
        out.update({"before": a.before, "after": a.after})
    return out


@router.get("/claims/{claim_id}/audit")
def claim_audit(paging: Paging = Depends(), claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
                user: Principal = Depends(require_permission("audit:view"))):
    q = select(AuditLog).where(AuditLog.claim_id == claim.id)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(q.order_by(AuditLog.id.desc()).offset(paging.offset).limit(paging.page_size)).scalars().all()
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    return envelope([_audit_row(a, names, False) for a in rows], page=paging.page, page_size=paging.page_size, total=total)


@router.get("/audit")
def audit_log(paging: Paging = Depends(), action: str | None = None, actor_id: str | None = None, entity_type: str | None = None,
              claim_id: str | None = None, date_from: str | None = None, db: Session = Depends(get_db),
              user: Principal = Depends(require_permission("audit:view"))):
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if claim_id:
        q = q.where(AuditLog.claim_id == claim_id)
    if date_from:
        q = q.where(AuditLog.ts >= date_from)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(q.order_by(AuditLog.id.desc()).offset(paging.offset).limit(paging.page_size)).scalars().all()
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    metadata_only = "claims_supervisor" not in user.roles  # admin: metadata only (no PHI)
    return envelope([_audit_row(a, names, metadata_only) for a in rows], page=paging.page, page_size=paging.page_size, total=total)


@router.get("/audit/verify")
def verify(db: Session = Depends(get_db), _: Principal = Depends(require_permission("audit:view"))):
    return envelope(audit.verify_chain(db))


# ---- metrics ------------------------------------------------------------------------------------------

@router.get("/metrics/summary")
def metrics_summary(db: Session = Depends(get_db), _: Principal = Depends(require_permission("audit:view", "run:manage"))):
    runs_by_status = dict(db.execute(select(AgentRun.status, func.count()).group_by(AgentRun.status)).all())
    stage = db.execute(select(AgentStep.stage, func.avg(AgentStep.duration_ms), func.count()).where(AgentStep.status == "completed")
                       .group_by(AgentStep.stage)).all()
    reviews = db.execute(select(Review).where(Review.status == "submitted")).scalars().all()
    turnaround: dict[str, list[float]] = {}
    for r in reviews:
        if r.submitted_at:
            turnaround.setdefault(r.checkpoint, []).append((parse_iso(r.submitted_at) - parse_iso(r.created_at)).total_seconds() / 3600)
    llm = db.execute(select(LlmCall.model, LlmCall.status, func.count(), func.sum(LlmCall.input_tokens + LlmCall.output_tokens),
                            func.sum(LlmCall.cost_usd), func.avg(LlmCall.latency_ms)).group_by(LlmCall.model, LlmCall.status)).all()
    facts_total = db.execute(select(func.count(ExtractedFact.id))).scalar() or 0
    rejected = db.execute(select(func.count(ExtractedFact.id)).where(ExtractedFact.validation_status == "rejected")).scalar() or 0
    edited = db.execute(select(func.count(ExtractedFact.id)).where(ExtractedFact.validation_status == "edited")).scalar() or 0
    flags_acted = db.execute(select(Flag.flag_type, func.count(), func.sum(Flag.is_override)).where(Flag.human_action.is_not(None))
                             .group_by(Flag.flag_type)).all()
    pages = db.execute(select(func.count(Page.id))).scalar() or 0
    claims_by_stage = dict(db.execute(select(Claim.current_stage, func.count()).group_by(Claim.current_stage)).all())
    sla_breaches = db.execute(select(func.count(Review.id)).where(Review.escalated.is_(True))).scalar() or 0
    pending = db.execute(select(Review.checkpoint, func.count()).where(Review.status.in_(["pending", "in_progress"])).group_by(Review.checkpoint)).all()
    return envelope({
        "runs_by_status": runs_by_status,
        "stage_duration_ms": {s or "unknown": {"avg_ms": round(a or 0), "steps": n} for s, a, n in stage},
        "hitl_turnaround_hours": {k: round(sum(v) / len(v), 2) for k, v in turnaround.items()},
        "pending_reviews": dict(pending), "sla_breaches": sla_breaches,
        "llm": [{"model": m, "status": s, "calls": c, "tokens": t or 0, "cost_usd": round(cost or 0, 4), "avg_latency_ms": round(lat or 0)}
                for m, s, c, t, cost, lat in llm],
        "quality": {"facts": facts_total, "validation_rejection_ratio": round(rejected / facts_total, 3) if facts_total else 0,
                    "human_edit_ratio": round(edited / facts_total, 3) if facts_total else 0,
                    "human_override_ratio": {ft: round((ov or 0) / n, 3) for ft, n, ov in flags_acted}},
        "business": {"pages_processed": pages, "claims_by_stage": claims_by_stage,
                     "estimated_hours_saved": round(pages * 2.5 / 60, 1)},  # ~2.5 min manual review per page (PoC assumption)
    })


@router.get("/metrics", include_in_schema=False)
def prometheus(db: Session = Depends(get_db)):
    """Prometheus exposition (gauges computed from the shared SQLite state on scrape)."""
    from prometheus_client import CollectorRegistry, Gauge, generate_latest

    reg = CollectorRegistry()
    g_runs = Gauge("claims_runs", "Runs by status", ["status"], registry=reg)
    for s, n in db.execute(select(AgentRun.status, func.count()).group_by(AgentRun.status)).all():
        g_runs.labels(s).set(n)
    Gauge("claims_jobs_queue_depth", "Queued jobs", registry=reg).set(db.execute(select(func.count(Job.id)).where(Job.status == "queued")).scalar() or 0)
    hb = db.execute(select(func.max(WorkerHeartbeat.beat_at))).scalar()
    Gauge("claims_worker_heartbeat_age_seconds", "Worker heartbeat age", registry=reg).set(
        (utcnow() - parse_iso(hb)).total_seconds() if hb else -1)
    g_llm = Gauge("claims_llm_requests", "LLM calls", ["model", "status"], registry=reg)
    g_tok = Gauge("claims_llm_tokens", "LLM tokens", ["model"], registry=reg)
    g_cost = Gauge("claims_llm_cost_usd", "LLM cost", ["model"], registry=reg)
    for m, s, c, t, cost in db.execute(select(LlmCall.model, LlmCall.status, func.count(), func.sum(LlmCall.input_tokens + LlmCall.output_tokens),
                                              func.sum(LlmCall.cost_usd)).group_by(LlmCall.model, LlmCall.status)).all():
        g_llm.labels(m, s).set(c)
        g_tok.labels(m).inc(t or 0)
        g_cost.labels(m).inc(cost or 0)
    g_hitl = Gauge("claims_hitl_pending", "Pending HITL reviews", ["checkpoint"], registry=reg)
    for cp, n in db.execute(select(Review.checkpoint, func.count()).where(Review.status.in_(["pending", "in_progress"])).group_by(Review.checkpoint)).all():
        g_hitl.labels(cp).set(n)
    total = db.execute(select(func.count(ExtractedFact.id))).scalar() or 0
    rej = db.execute(select(func.count(ExtractedFact.id)).where(ExtractedFact.validation_status == "rejected")).scalar() or 0
    Gauge("claims_validation_rejection_ratio", "Rejected / extracted facts", registry=reg).set(rej / total if total else 0)
    return Response(generate_latest(reg), media_type="text/plain; version=0.0.4")


# ---- health ---------------------------------------------------------------------------------------

@router.get("/health/live")
def live():
    return {"status": "ok"}


_gemini_cache: dict = {"at": None, "ok": None}


@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)):
    checks: dict[str, dict] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": str(exc)[:200]}
    checks["file_store"] = {"ok": file_store.healthy()}
    hb = db.execute(select(func.max(WorkerHeartbeat.beat_at))).scalar()
    age = (utcnow() - parse_iso(hb)).total_seconds() if hb else None
    checks["worker"] = {"ok": age is not None and age < 60, "heartbeat_age_s": round(age, 1) if age is not None else None}
    from app.llm.gateway import get_gateway
    gw = get_gateway()
    if gw.enabled:
        if _gemini_cache["at"] is None or utcnow() - _gemini_cache["at"] > timedelta(minutes=5):
            _gemini_cache.update(at=utcnow(), ok=gw.ping())
        checks["gemini"] = {"ok": bool(_gemini_cache["ok"]), "circuit": gw.breaker.state, "mode": "gemini"}
    else:
        checks["gemini"] = {"ok": True, "mode": "rules (offline deterministic fallback)"}
    ok = all(c["ok"] for k, c in checks.items() if k in ("database", "file_store"))
    response.status_code = 200 if ok else 503
    return {"status": "ready" if ok else "degraded", "checks": checks}


# ---- admin config ----------------------------------------------------------------------------------

@router.get("/admin/system")
def system(db: Session = Depends(get_db), _: Principal = Depends(require_permission("config:manage"))):
    from app.llm.gateway import get_gateway
    from app.orchestration.graph import GRAPH_VERSION
    from app.tools.registry import list_tools

    gw = get_gateway()
    hbs = db.execute(select(WorkerHeartbeat)).scalars().all()
    return envelope({"app_env": settings.APP_ENV, "llm_mode": settings.llm_mode, "models": {"fast": gw.model_for("fast"),
                     "reasoning": gw.model_for("reasoning"), "embedding": settings.GEMINI_EMBED_MODEL},
                     "allow_phi_to_llm": settings.ALLOW_PHI_TO_LLM, "circuit": gw.breaker.state, "graph_version": GRAPH_VERSION,
                     "queue": dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all()),
                     "workers": [{"worker_id": h.worker_id, "beat_at": h.beat_at, "current_job_id": h.current_job_id} for h in hbs],
                     "tools": list_tools()})


@router.get("/admin/graph")
def graph(_: Principal = Depends(require_permission("config:manage", "audit:view"))):
    from app.orchestration.graph import mermaid
    return envelope({"mermaid": mermaid()})


@router.get("/admin/prompts")
def prompts(db: Session = Depends(get_db), _: Principal = Depends(require_permission("config:manage"))):
    rows = db.execute(select(PromptTemplate).order_by(PromptTemplate.name, PromptTemplate.created_at.desc())).scalars().all()
    return envelope([p.to_dict() for p in rows])


class PromptIn(BaseModel):
    name: str
    version: str = Field(min_length=1, max_length=16)
    template: str = Field(min_length=10)
    system: str | None = None
    model_tier: str = Field(default="fast", pattern="^(fast|reasoning)$")
    temperature: float = Field(default=0.0, ge=0, le=1)


@router.put("/admin/prompts")
def publish_prompt(body: PromptIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("config:manage"))):
    from app.agents.prompts.registry import DEFAULTS, Prompt
    if body.name not in DEFAULTS:
        raise BadRequest(f"Unknown prompt {body.name}")
    try:  # template must render with the variables the agent supplies
        import jinja2
        jinja2.Environment().parse(body.template)
    except jinja2.TemplateSyntaxError as exc:
        raise BadRequest(f"Template syntax error: {exc}") from exc
    _ = Prompt
    for p in db.execute(select(PromptTemplate).where(PromptTemplate.name == body.name, PromptTemplate.is_active.is_(True))).scalars():
        p.is_active = False
    row = PromptTemplate(id=uuid7(), created_by=user.id, is_active=True, **body.model_dump())
    db.add(row)
    audit.record(db, action="prompt.publish", entity_type="prompt_template", entity_id=row.id, actor_id=user.id,
                 after={"name": body.name, "version": body.version})
    return envelope(row.to_dict())


@router.get("/admin/settings")
def get_settings(db: Session = Depends(get_db), _: Principal = Depends(require_permission("config:manage"))):
    return envelope({s.key: s.value for s in db.execute(select(AppSetting)).scalars()})


class SettingsIn(BaseModel):
    thresholds: dict[str, float] | None = None
    models: dict[str, str] | None = None


ALLOWED_THRESHOLDS = {"CONFIDENCE_THRESHOLD_BASELINE", "CONFIDENCE_THRESHOLD_CLASSIFICATION", "CONFIDENCE_THRESHOLD_FACT",
                      "RISK_ESCALATION_THRESHOLD", "TREATMENT_GAP_DAYS", "QUOTE_MATCH_THRESHOLD", "ONE_PAGE_WORD_LIMIT"}


@router.put("/admin/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("config:manage"))):
    for key, value, allowed in (("thresholds", body.thresholds, ALLOWED_THRESHOLDS), ("models", body.models, {"fast", "reasoning"})):
        if value is None:
            continue
        bad = set(value) - allowed
        if bad:
            raise BadRequest(f"Unknown {key}: {sorted(bad)}")
        row = db.get(AppSetting, key) or AppSetting(key=key, value={})
        before = dict(row.value or {})
        row.value, row.updated_by = {**before, **value}, user.id
        db.merge(row)
        audit.record(db, action="config.change", entity_type="app_setting", entity_id=key, actor_id=user.id, before=before, after=row.value)
    return envelope({s.key: s.value for s in db.execute(select(AppSetting)).scalars()})


# ---- guideline store (licensed content import, spec §10.4 / §19.2) -------------------------------------------

@router.get("/admin/guidelines/sources")
def sources(db: Session = Depends(get_db), _: Principal = Depends(require_permission("config:manage"))):
    out = []
    for s in db.execute(select(GuidelineSource)).scalars():
        n = db.execute(select(func.count(GuidelineRule.id)).where(GuidelineRule.source_id == s.id)).scalar()
        out.append({**s.to_dict(), "rule_count": n})
    return envelope(out)


class SourceIn(BaseModel):
    name: str = Field(min_length=2)
    edition: str | None = None
    jurisdiction: str | None = None
    license_ref: str | None = None
    effective_from: str | None = None


@router.post("/admin/guidelines/sources", status_code=201)
def add_source(body: SourceIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("config:manage"))):
    row = GuidelineSource(id=uuid7(), **body.model_dump())
    db.add(row)
    audit.record(db, action="guideline_source.create", entity_type="guideline_source", entity_id=row.id, actor_id=user.id, after=body.model_dump())
    return envelope(row.to_dict())


@router.get("/admin/guidelines/rules")
def rules(source_id: str | None = None, db: Session = Depends(get_db), _: Principal = Depends(require_permission("config:manage", "audit:view"))):
    q = select(GuidelineRule)
    if source_id:
        q = q.where(GuidelineRule.source_id == source_id)
    return envelope([r.to_dict(exclude={"embedding"}) for r in db.execute(q.order_by(GuidelineRule.rule_code)).scalars()])


@router.post("/admin/guidelines/rules/import")
async def import_rules_endpoint(source_id: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                                user: Principal = Depends(require_permission("config:manage"))):
    """CSV or JSON import.  Columns: rule_code,title,category,body_part,diagnosis_codes,procedure_codes,keywords,
    criteria_text,max_visits,max_duration_days,prerequisites,recommendation (list columns are ';'-separated in CSV)."""
    from app.seed.reference import import_rules

    if db.get(GuidelineSource, source_id) is None:
        raise NotFound("Guideline source not found")
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    errors, rows = [], []
    try:
        records = json.loads(raw) if (file.filename or "").lower().endswith(".json") else list(csv.DictReader(io.StringIO(raw)))
    except (json.JSONDecodeError, csv.Error) as exc:
        raise BadRequest(f"Could not parse file: {exc}") from exc
    for i, r in enumerate(records, 1):
        try:
            rec = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
            for k in ("diagnosis_codes", "procedure_codes", "keywords", "prerequisites"):
                if isinstance(rec.get(k), str):
                    rec[k] = [x.strip() for x in rec[k].split(";") if x.strip()]
            for k in ("max_visits", "max_duration_days"):
                rec[k] = int(rec[k]) if rec.get(k) not in (None, "") else None
            if not rec.get("rule_code") or not rec.get("title") or not rec.get("criteria_text"):
                raise ValueError("rule_code, title and criteria_text are required")
            if rec.get("recommendation") not in ("recommended", "not_recommended", "conditional"):
                raise ValueError("recommendation must be recommended|not_recommended|conditional")
            rec.setdefault("category", "treatment")
            rows.append(rec)
        except (ValueError, TypeError) as exc:
            errors.append({"row": i, "error": str(exc)})
    n = import_rules(db, source_id, rows) if rows else 0
    audit.record(db, action="guideline.import", entity_type="guideline_source", entity_id=source_id, actor_id=user.id,
                 after={"imported": n, "errors": len(errors)})
    return envelope({"imported": n, "errors": errors})


def purge_llm_bodies(db: Session) -> int:
    """Retention: LLM request/response bodies are purged after LLM_BODY_RETENTION_DAYS (spec §15.2)."""
    cutoff = to_iso(utcnow() - timedelta(days=settings.LLM_BODY_RETENTION_DAYS))
    n = 0
    for row in db.execute(select(LlmCall).where(LlmCall.created_at < cutoff, LlmCall.request_enc.is_not(None))).scalars():
        row.request_enc = row.response_enc = None
        n += 1
    return n
