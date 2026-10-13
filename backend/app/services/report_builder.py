"""Builds standardized report documents (spec §7.9 templates) from persisted, validated data.

The same structures feed the in-app views and the PDF / DOCX / JSON exports (report_template_tool)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_str
from app.models import (
    AuditLog,
    ChronologyEvent,
    Citation,
    Claim,
    Claimant,
    Decision,
    Document,
    ExtractedFact,
    Flag,
    GuidelineFinding,
    LlmCall,
    Milestone,
    Review,
    Summary,
    URDetermination,
)

AI_BANNER = "AI-assisted draft prepared for human review - not a claim, utilization or legal determination."


def _fmt(iso: str | None) -> str:
    if not iso:
        return "-"
    y, m, d = iso[:10].split("-")
    return f"{m}/{d}/{y}"


def claim_header(db: Session, claim: Claim) -> list[tuple[str, str]]:
    cl = db.get(Claimant, claim.claimant_id)
    return [("Claim #", claim.claim_number), ("Claimant", decrypt_str(cl.full_name_enc) if cl else "-"),
            ("Date of injury", _fmt(claim.date_of_injury)), ("Employer", claim.employer_name or "-"),
            ("Insurer / TPA", f"{claim.insurer or '-'} / {claim.tpa or '-'}"), ("Adjuster", claim.adjuster_name or "-"),
            ("Jurisdiction", claim.jurisdiction_state or "-"), ("Body part(s)", ", ".join(claim.body_parts or []) or "-")]


def evidence_index(db: Session, citation_ids: list[str]) -> tuple[dict[str, int], dict]:
    """Numbered evidence index: citation id -> [n]; table of document/page/lines."""
    numbering: dict[str, int] = {}
    rows = []
    if citation_ids:
        cites = {c.id: c for c in db.execute(select(Citation).where(Citation.id.in_(citation_ids))).scalars()}
        keyed: dict[tuple, int] = {}
        for cid in citation_ids:
            c = cites.get(cid)
            if c is None:
                continue
            key = (c.document_id, c.page_number, c.line_start, c.line_end)
            if key not in keyed:
                doc = db.get(Document, c.document_id)
                keyed[key] = len(keyed) + 1
                rows.append([keyed[key], (doc.title or doc.original_filename)[:70] if doc else c.document_id, c.page_number,
                             f"{c.line_start}-{c.line_end}", (c.quote or "")[:90]])
            numbering[cid] = keyed[key]
    return numbering, {"columns": ["#", "Document", "Page", "Lines", "Quote"], "rows": rows, "widths": [22, 170, 34, 44, 262]}


def cited_sections(db: Session, summary: Summary) -> tuple[list[dict], dict]:
    sections = summary.content_json.get("sections", [])
    all_ids = [cid for s in sections for sent in s.get("sentences", []) for cid in sent.get("citation_ids", [])]
    numbering, table = evidence_index(db, all_ids)
    out = []
    for s in sections:
        bullets = []
        for sent in s.get("sentences", []):
            refs = sorted({numbering[c] for c in sent.get("citation_ids", []) if c in numbering})
            bullets.append(sent["text"] + (" [" + ", ".join(map(str, refs)) + "]" if refs else ""))
        out.append({"heading": s["heading"], "bullets": bullets})
    return out, table


def latest_summary(db: Session, claim_id: str, summary_type: str, approved_only: bool = False) -> Summary | None:
    q = select(Summary).where(Summary.claim_id == claim_id, Summary.summary_type == summary_type, Summary.status != "superseded")
    if approved_only:
        q = q.where(Summary.status == "approved")
    return db.execute(q.order_by(Summary.created_at.desc()).limit(1)).scalar_one_or_none()


TITLES = {"one_page_summary": ("one_page", "One-Page Actionable Summary"), "mmi_status": ("mmi_status", "MMI Status Report"),
          "case_progress": ("case_progress", "Case-Progress Summary"), "narrative": ("narrative", "Clinical Narrative"),
          "clinical": ("clinical", "Clinical Summary")}


def build_report(db: Session, claim: Claim, report_type: str, approved_only: bool = False) -> dict:
    header = claim_header(db, claim)
    if report_type == "medical_chronology":
        events = db.execute(select(ChronologyEvent).where(ChronologyEvent.claim_id == claim.id, ChronologyEvent.is_current.is_(True))
                            .order_by(ChronologyEvent.sort_order)).scalars().all()
        rows = [[_fmt(e.event_date), e.provider or "-", e.event_type, e.description + (" (TURNING POINT)" if e.is_turning_point else ""),
                 e.key_findings or "", e.work_status or "",
                 "; ".join(dict.fromkeys(f"p{c['page_number']} L{c['line_start']}" for c in (e.citations or [])))] for e in events]
        return {"title": "Structured Medical Chronology", "subtitle": f"{len(rows)} events - page-level citations"
                + (" - APPROVED" if approved_only else ""),
                "banner": None if approved_only else AI_BANNER, "header": header,
                "sections": [{"heading": "Chronology", "table": {"columns": ["Date", "Provider", "Type", "Description", "Key findings", "Work status", "Source"],
                                                                "rows": rows, "widths": [50, 80, 70, 140, 100, 52, 40]}}],
                "footer": "Generated by Claims AI from validated facts. Source references are page/line citations into the claim file."}
    if report_type == "decision_provenance":
        return decision_provenance(db, claim)
    stype, title = TITLES[report_type]
    summary = latest_summary(db, claim.id, stype, approved_only)
    if summary is None:
        raise LookupError(f"no {'approved ' if approved_only else ''}{stype} summary for this claim")
    sections, table = cited_sections(db, summary)
    status = "APPROVED" if summary.status == "approved" else summary.status.upper()
    return {"title": title, "subtitle": f"Version {summary.version} - {status}", "banner": None if summary.status == "approved" else AI_BANNER,
            "header": header, "sections": sections + ([{"heading": "Evidence index", "table": table}] if table["rows"] else []),
            "footer": f"Summary id {summary.id}. Every statement is linked to page/line citations in the evidence index."}


def decision_provenance(db: Session, claim: Claim) -> dict:
    """Decision -> reviewer & rationale -> flags -> AI drafts (model/prompt) -> validated facts -> citations -> pages (§16.4)."""
    decisions = db.execute(select(Decision).where(Decision.claim_id == claim.id).order_by(Decision.created_at)).scalars().all()
    flags = db.execute(select(Flag).where(Flag.claim_id == claim.id, Flag.human_action.is_not(None))).scalars().all()
    findings = db.execute(select(GuidelineFinding).where(GuidelineFinding.claim_id == claim.id)).scalars().all()
    facts = db.execute(select(ExtractedFact).where(ExtractedFact.claim_id == claim.id, ExtractedFact.is_current.is_(True),
                                                   ExtractedFact.validation_status.in_(["validated", "edited", "auto_verified"]))).scalars().all()
    reviews = db.execute(select(Review).where(Review.claim_id == claim.id).order_by(Review.created_at)).scalars().all()
    urs = db.execute(select(URDetermination).where(URDetermination.claim_id == claim.id)).scalars().all()
    llm = db.execute(select(LlmCall.model, LlmCall.prompt_template, LlmCall.prompt_version).where(
        LlmCall.run_id.in_([r.run_id for r in reviews] or [""])).distinct()).all()
    audit = db.execute(select(AuditLog).where(AuditLog.claim_id == claim.id, AuditLog.actor_type == "user").order_by(AuditLog.id)).scalars().all()
    from app.models import User
    names = {u.id: u.full_name for u in db.execute(select(User)).scalars()}
    milestones = db.execute(select(Milestone).where(Milestone.claim_id == claim.id, Milestone.status != "superseded")).scalars().all()
    sections = [
        {"heading": "Decisions", "table": {"columns": ["Type", "Outcome", "Rationale", "Decided by", "Signed off", "Status / hash"],
                                           "rows": [[d.decision_type, d.outcome, d.rationale[:220], f"{names.get(d.decided_by, '-')} {_fmt(d.decided_at)}",
                                                     f"{names.get(d.signed_off_by, '-')} {_fmt(d.signed_off_at)}" if d.signed_off_by else "-",
                                                     f"{d.status} {(d.record_hash or '')[:12]}"] for d in decisions],
                                           "widths": [70, 80, 180, 70, 70, 62]}},
        {"heading": "UR determinations", "bullets": [f"{u.determination}: {u.clinical_rationale[:300]} ({names.get(u.reviewer_id, '-')}, {_fmt(u.determined_at)})" for u in urs] or ["None"]},
        {"heading": "Human review checkpoints", "table": {"columns": ["Checkpoint", "Title", "Submitted by", "When", "Status"],
                                                          "rows": [[r.checkpoint, r.title, names.get(r.submitted_by, "-"), _fmt(r.submitted_at), r.status] for r in reviews],
                                                          "widths": [60, 220, 90, 70, 92]}},
        {"heading": "AI flags acted on", "table": {"columns": ["Flag", "AI recommendation", "Human action", "Reason", "By"],
                                                   "rows": [[f.title[:80], (f.ai_recommendation or "")[:90], f.human_action + (" (override)" if f.is_override else ""),
                                                             f.reason or "", names.get(f.acted_by, "-")] for f in flags],
                                                   "widths": [130, 130, 70, 120, 82]}},
        {"heading": "Guideline findings", "bullets": [f"{g.finding_type} ({g.status}): {g.title} - rule {(g.rule_excerpt or 'none')[:80]}" for g in findings]},
        {"heading": "Turning points", "bullets": [f"{_fmt(m.milestone_date)} {m.description}: {m.impact_narrative or ''}" for m in milestones]},
        {"heading": "Validated facts relied upon", "bullets": [f"{_fmt(f.effective_date)} {f.label} [{f.validation_status}]" for f in facts[:60]]},
        {"heading": "AI models and prompt versions", "bullets": [f"{m} - {t} v{v}" for m, t, v in llm] or ["Rule-based processing (no LLM calls)"]},
        {"heading": "Human activity timeline", "bullets": [f"{a.ts[:16].replace('T', ' ')} {names.get(a.actor_id, a.actor_id)}: {a.action} {a.entity_type}" for a in audit[-80:]]},
    ]
    return {"title": "Decision Provenance Report", "subtitle": "How the decision was reached - traceable to source pages",
            "header": claim_header(db, claim), "sections": sections,
            "footer": "Facts are linked to page/line citations; see the medical chronology and evidence indexes. Audit log entries are hash-chained."}
