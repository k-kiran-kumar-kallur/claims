"""Report export (spec §12.7): build -> render (PDF/DOCX/JSON) -> encrypted store -> `reports` row."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import sha256_hex
from app.models import Claim, Report
from app.services import file_store
from app.services.report_builder import build_report
from app.tools.output import report_template_tool

REPORT_TYPES = ["one_page_summary", "mmi_status", "medical_chronology", "case_progress", "narrative", "clinical",
                "decision_provenance"]
FORMATS = ["pdf", "docx", "json", "html"]


def render(db: Session, report: Report) -> Report:
    claim = db.get(Claim, report.claim_id)
    try:
        doc = build_report(db, claim, report.report_type, approved_only=report.is_approved_content)
        out = report_template_tool(doc, report.format)
        report.file_path = file_store.put(file_store.report_path(claim.id, report.id, report.format), out["bytes"])
        report.sha256 = sha256_hex(out["bytes"])
        report.status = "approved" if report.is_approved_content else "ready"
        report.error = None
    except LookupError as exc:
        report.status, report.error = "failed", str(exc)
    return report
