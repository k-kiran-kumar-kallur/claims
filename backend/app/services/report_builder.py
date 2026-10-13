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


def _fmt_dt(iso: str | None, utc: bool = True) -> str:
    """ISO timestamp -> 'MM/DD/YYYY HH:MM UTC' (date only when no time is present)."""
    if not iso:
        return "-"
    if len(iso) < 16:
        return _fmt(iso)
    return f"{_fmt(iso)} {iso[11:16]}" + (" UTC" if utc else "")


_ACRONYMS = {"ur": "UR", "mmi": "MMI", "rtw": "RTW", "fce": "FCE", "ime": "IME", "ttd": "TTD", "cms": "CMS", "phi": "PHI", "pt": "PT"}


def _label(value: str | None) -> str:
    """Stored code -> reader-facing label: non_certified -> 'Non-certified', treatment_authorization -> 'Treatment authorization'."""
    if not value:
        return "-"
    special = {"non_certified": "Non-certified", "auto_verified": "Auto-verified", "hitl": "HITL"}
    if value in special:
        return special[value]
    words = [_ACRONYMS.get(w, w) for w in value.replace(".", " ").split("_")]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _clip(text: str | None, limit: int) -> str:
    """Shorten on a word boundary with an ellipsis instead of cutting mid-word."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:-")
    return cut + "..."


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
                rows.append([keyed[key], _clip(doc.title or doc.original_filename, 80) if doc else c.document_id, c.page_number,
                             f"{c.line_start}-{c.line_end}", _clip(c.quote, 160)])
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
                 "; ".join(dict.fromkeys(f"p{c['page_number']}:L{c['line_start']}" for c in (e.citations or [])))] for e in events]
        return {"title": "Structured Medical Chronology", "landscape": True, "subtitle": f"{len(rows)} events - page-level citations"
                + (" - APPROVED" if approved_only else ""),
                "banner": None if approved_only else AI_BANNER, "header": header,
                "sections": [{"heading": "Chronology", "table": {"columns": ["Date", "Provider", "Type", "Description", "Key findings", "Work status", "Source"],
                                                                "rows": rows, "widths": [58, 90, 104, 150, 166, 70, 58], "bold_first": True}}],
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


# audit actions that record people looking at or exporting the file, not steps toward the decision
_NOT_DECISION_STEPS = {"phi.view", "search.execute", "report.export", "auth.login", "auth.logout", "auth.failed"}
_ACTION_LABELS = {
    "claim.create": "Created the claim", "document.upload": "Uploaded documents", "run.start": "Started AI processing",
    "baseline.lock": "Confirmed and locked the claim baseline", "discrepancy.resolve": "Resolved a baseline discrepancy",
    "timeline.approve": "Approved the medical timeline", "fact.accept": "Accepted an extracted fact", "fact.edit": "Corrected an extracted fact",
    "fact.reject": "Rejected an extracted fact", "summary.approve": "Approved a summary", "summary.edit": "Edited a summary",
    "review.submit": "Submitted a review checkpoint", "flag.approve": "Approved an AI flag", "flag.reject": "Rejected an AI flag",
    "flag.modify": "Modified an AI flag", "ur.determination": "Recorded the UR determination", "decision.create": "Recorded the claim decision",
    "decision.signoff": "Signed off and sealed the decision", "claim.member_add": "Granted claim access",
}


def _as_items(value) -> list[str]:
    """Normalise stored list-ish values (lists, dicts, '<br>'/newline-joined strings) into clean bullet items."""
    import re

    items = value if isinstance(value, list) else [value] if value else []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = item.get("text") or item.get("action") or item.get("step") or item.get("question") or ", ".join(f"{k}: {v}" for k, v in item.items())
        out += [p.strip(" -*\u2022") for p in re.split(r"<br\s*/?>|\n", str(item)) if p.strip(" -*\u2022")]
    return out


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
    milestones = db.execute(select(Milestone).where(Milestone.claim_id == claim.id, Milestone.status != "superseded")
                            .order_by(Milestone.milestone_date)).scalars().all()
    who = lambda uid: names.get(uid, "-") if uid else "-"  # noqa: E731

    # ---- 1. decision summary (the final / latest decision) ----
    final = decisions[-1] if decisions else None
    submitted = sum(1 for r in reviews if r.status == "submitted")
    summary_pairs: list[tuple[str, str]] = []
    fields: list[tuple[str, str]] = []
    follow_up: list[str] = []
    if final:
        summary_pairs = [
            ("Decision", _label(final.decision_type)), ("Record status", _label(final.status)),
            ("Outcome", final.outcome), ("Decided by", f"{who(final.decided_by)}, {_fmt_dt(final.decided_at)}"),
            ("Supervisor sign-off", f"{who(final.signed_off_by)}, {_fmt_dt(final.signed_off_at)}" if final.signed_off_by
             else ("Required - pending" if final.requires_signoff else "Not required")),
            ("UR determination", "; ".join(f"{_label(u.determination)} ({who(u.reviewer_id)})" for u in urs) or "None"),
            ("Human checkpoints completed", f"{submitted} of {len(reviews)}"), ("AI flags reviewed", str(len(flags))),
        ]
        fields.append(("Rationale", final.rationale))
        if final.signoff_comments:
            fields.append(("Supervisor comments", final.signoff_comments))
        if final.record_hash:
            fields.append(("Sealed record hash (SHA-256)", final.record_hash))
        follow_up = [f"Next step: {x}" for x in _as_items(final.next_steps)] + [f"Open question: {x}" for x in _as_items(final.outstanding_questions)]
    else:
        fields.append(("Status", "No claim decision has been recorded for this claim yet."))

    # ---- human activity: decision-relevant steps only ----
    steps = [a for a in audit if a.action not in _NOT_DECISION_STEPS]
    omitted = len(audit) - len(steps)
    # consecutive repeats of the same action by the same person collapse into one row with a count and time range
    groups: list[list] = []
    for a in steps:
        if groups and groups[-1][0].actor_id == a.actor_id and groups[-1][0].action == a.action:
            groups[-1].append(a)
        else:
            groups.append([a])
    activity_rows = []
    for g in groups:
        first, last = _fmt_dt(g[0].ts, False), _fmt_dt(g[-1].ts, False)
        when = first if first == last else f"{first} -\n{last[-5:] if first[:10] == last[:10] else last}"
        action = _ACTION_LABELS.get(g[0].action, _label(g[0].action.replace(".", "_")))
        activity_rows.append([when, who(g[0].actor_id) if g[0].actor_id in names else g[0].actor_id,
                              action + (f" (x{len(g)})" if len(g) > 1 else "")])

    def fact_sort(f):
        return (f.effective_date or "9999", f.label or "")

    sections = [
        {"heading": "Decision summary", "summary": summary_pairs, "fields": fields},
        *([{"heading": "Next steps and open questions", "bullets": follow_up}] if follow_up else []),
        {"heading": "Decision record", "table": {
            "columns": ["Decision", "Outcome", "Rationale", "Decided by", "Sign-off", "Status"],
            "rows": [[_label(d.decision_type), d.outcome, d.rationale, f"{who(d.decided_by)}\n{_fmt_dt(d.decided_at, False)}",
                      f"{who(d.signed_off_by)}\n{_fmt_dt(d.signed_off_at, False)}" if d.signed_off_by else "-", _label(d.status)] for d in decisions],
            "widths": [70, 90, 190, 80, 80, 50], "bold_first": True, "empty": "No decisions recorded."}},
        {"heading": "Utilization review determinations", "table": {
            "columns": ["Determination", "Clinical rationale", "Reviewer", "Date"],
            "rows": [[_label(u.determination), u.clinical_rationale, who(u.reviewer_id), _fmt_dt(u.determined_at, False)] for u in urs],
            "widths": [80, 260, 90, 80], "bold_first": True, "empty": "No utilization review was required."}},
        {"heading": "Human review checkpoints", "note": "Each AI stage paused for the responsible role to review before the workflow continued.",
         "table": {"columns": ["Checkpoint", "Task", "Completed by", "Completed", "Status"],
                   "rows": [[r.checkpoint, r.title, who(r.submitted_by), _fmt_dt(r.submitted_at, False), _label(r.status)] for r in reviews],
                   "widths": [62, 210, 90, 90, 58], "bold_first": True}},
        {"heading": "AI flags and human actions", "table": {
            "columns": ["Flag", "Severity", "AI recommendation", "Human action", "Reviewer"],
            "rows": [[f.title, _label(f.severity), f.ai_recommendation or "-",
                      _label(f.human_action) + (" (override)" if f.is_override else "") + (f" - {f.reason}" if f.reason else ""),
                      f"{who(f.acted_by)}\n{_fmt_dt(f.acted_at, False)}"] for f in flags],
            "widths": [140, 50, 150, 90, 80], "empty": "No AI flags were acted on."}},
        {"heading": "Guideline findings", "table": {
            "columns": ["Finding", "Type", "Status", "Guideline rule"],
            "rows": [[g.title, _label(g.finding_type), _label(g.status), _clip(g.rule_excerpt, 260) or "-"] for g in findings],
            "widths": [170, 80, 55, 205], "empty": "No guideline findings."}},
        {"heading": "Turning points", "table": {
            "columns": ["Date", "Turning point", "Impact on the claim"],
            "rows": [[_fmt(m.milestone_date), m.description,
                      m.impact_narrative if m.impact_narrative and m.impact_narrative.strip(" .") != m.description.strip(" .") else "-"]
                     for m in milestones],
            "widths": [60, 200, 250], "empty": "No turning points were identified."}},
        {"heading": "Validated facts relied upon", "table": {
            "columns": ["Date", "Fact", "Type", "Validation"],
            "rows": [[_fmt(f.effective_date), f.label, _label(f.fact_type), _label(f.validation_status)] for f in sorted(facts, key=fact_sort)[:150]],
            "widths": [60, 270, 100, 80], "empty": "No validated facts.",
            "caption": f"Showing 150 of {len(facts)} facts. The full list is in the medical chronology." if len(facts) > 150 else
            "Every fact links to page/line citations in the source documents."}},
        {"heading": "AI models and prompt versions", "table": {
            "columns": ["Model", "Prompt template", "Version"],
            "rows": [[m, t or "-", f"v{v}" if v else "-"] for m, t, v in llm],
            "widths": [180, 260, 70], "empty": "Rule-based processing (no LLM calls)."}},
        {"heading": "Human activity timeline", "table": {
            "columns": ["When", "Who", "Action"],
            "rows": activity_rows,
            "widths": [110, 110, 290], "empty": "No decision steps recorded.",
            "caption": f"{omitted} record views, searches, sign-ins and exports are omitted here; they remain in the hash-chained audit log."
            if omitted else None}},
    ]
    return {"title": "Decision Provenance Report", "subtitle": "How the decision was reached - traceable to source pages",
            "header": claim_header(db, claim), "sections": sections,
            "footer": "All times are UTC. Facts are linked to page/line citations; see the medical chronology and evidence indexes. "
                      "Audit log entries are hash-chained and can be independently verified."}
