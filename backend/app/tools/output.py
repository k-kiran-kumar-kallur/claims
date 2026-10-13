"""Output tools: report templating (HTML / PDF / DOCX / JSON), CMS connector, notifications (spec §8)."""
from __future__ import annotations

import io
import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from fpdf import FPDF
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.integrations.cms.base import get_cms_connector
from app.services.events import notify
from app.tools.registry import tool

log = get_logger(__name__)
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "reports"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html"]))

_REPL = {"—": "-", "–": "-", "→": "->", "≤": "<=", "≥": ">=", "‘": "'", "’": "'",
         "“": '"', "”": '"', "•": "-", " ": " ", "…": "...", "✓": "v", "✔": "v"}


def _latin1(text: str) -> str:
    for k, v in _REPL.items():
        text = text.replace(k, v)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def render_html(doc: dict) -> str:
    return _env.get_template("report.html.j2").render(doc=doc)


def render_pdf(doc: dict) -> tuple[bytes, int]:
    from fpdf.enums import XPos, YPos

    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_margins(40, 36, 40)
    pdf.set_auto_page_break(True, margin=40)
    pdf.add_page()
    width = pdf.w - 80
    nl = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT, "align": "L"}  # always return to the left margin

    def para(text: str, size: float, style: str = "", lh: float = 11.0, color=(0, 0, 0), fill: bool = False) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(width, lh, _latin1(text), fill=fill, **nl)
        pdf.set_text_color(0, 0, 0)

    para(doc["title"], 14, "B", 17)
    if doc.get("subtitle"):
        para(doc["subtitle"], 8.5, "", 11, (90, 90, 90))
    if doc.get("banner"):
        pdf.set_fill_color(255, 243, 205)
        pdf.ln(2)
        para(doc["banner"], 8, "B", 11, (122, 83, 0), fill=True)
    if doc.get("header"):
        pdf.ln(4)
        pairs = doc["header"]
        col, label_w = width / 2, 72
        for i in range(0, len(pairs), 2):
            y, x = pdf.get_y(), pdf.l_margin
            heights = []
            for k, v in pairs[i:i + 2]:
                pdf.set_xy(x, y)
                pdf.set_font("Helvetica", "B", 8)
                pdf.cell(label_w, 11, _latin1(f"{k}:"))
                pdf.set_font("Helvetica", "", 8)
                pdf.set_xy(x + label_w, y)
                pdf.multi_cell(col - label_w - 6, 11, _latin1(str(v or "-")), **nl)
                heights.append(pdf.get_y() - y)
                x += col
            pdf.set_xy(pdf.l_margin, y + max(heights))
        pdf.set_draw_color(220, 225, 232)
        pdf.line(pdf.l_margin, pdf.get_y() + 3, pdf.l_margin + width, pdf.get_y() + 3)
        pdf.ln(5)
    for sec in doc.get("sections", []):
        if pdf.get_y() > pdf.h - 90:
            pdf.add_page()
        pdf.ln(5)
        para(sec["heading"], 10, "B", 13, (25, 60, 120))
        for p in sec.get("paragraphs", []):
            para(p, 8.5, "", 11)
        for b in sec.get("bullets", []):
            pdf.set_font("Helvetica", "", 8.5)
            y = pdf.get_y()
            pdf.set_xy(pdf.l_margin, y)
            pdf.cell(10, 11, "-")
            pdf.set_xy(pdf.l_margin + 10, y)
            pdf.multi_cell(width - 10, 11, _latin1(b), **nl)
        table = sec.get("table")
        if table and table.get("rows"):
            cols = table["columns"]
            widths = table.get("widths") or [width / len(cols)] * len(cols)
            scale = width / sum(widths)
            widths = [w * scale for w in widths]

            def header_row() -> None:
                pdf.set_font("Helvetica", "B", 7.5)
                pdf.set_fill_color(235, 239, 245)
                pdf.set_x(pdf.l_margin)
                for c, w in zip(cols, widths, strict=False):
                    pdf.cell(w, 13, _latin1(c), border=1, fill=True)
                pdf.ln(13)

            pdf.ln(2)
            header_row()
            pdf.set_font("Helvetica", "", 7.5)
            for row in table["rows"]:
                cells = [_latin1(str(v if v is not None else "")) for v in row]
                lines = [max(1, len(pdf.multi_cell(w - 4, 9, t, dry_run=True, output="LINES"))) for t, w in zip(cells, widths, strict=False)]
                h = 9 * max(lines) + 4
                if pdf.get_y() + h > pdf.h - 40:
                    pdf.add_page()
                    header_row()
                    pdf.set_font("Helvetica", "", 7.5)
                y, x = pdf.get_y(), pdf.l_margin
                for t, w in zip(cells, widths, strict=False):
                    pdf.rect(x, y, w, h)
                    pdf.set_xy(x + 2, y + 2)
                    pdf.multi_cell(w - 4, 9, t, new_x=XPos.RIGHT, new_y=YPos.TOP, align="L")
                    x += w
                pdf.set_xy(pdf.l_margin, y + h)
    if doc.get("footer"):
        pdf.ln(8)
        para(doc["footer"], 7, "I", 9, (110, 110, 110))
    return bytes(pdf.output()), pdf.page_no()


def render_docx(doc: dict) -> bytes:
    import docx
    from docx.shared import Pt

    d = docx.Document()
    style = d.styles["Normal"]
    style.font.size = Pt(9.5)
    d.add_heading(doc["title"], level=1)
    if doc.get("subtitle"):
        d.add_paragraph(doc["subtitle"]).italic = True
    if doc.get("banner"):
        d.add_paragraph(doc["banner"]).runs[0].bold = True
    if doc.get("header"):
        t = d.add_table(rows=0, cols=2)
        t.style = "Light Grid Accent 1"
        for k, v in doc["header"]:
            row = t.add_row().cells
            row[0].text, row[1].text = str(k), str(v or "-")
    for sec in doc.get("sections", []):
        d.add_heading(sec["heading"], level=2)
        for p in sec.get("paragraphs", []):
            d.add_paragraph(p)
        for b in sec.get("bullets", []):
            d.add_paragraph(b, style="List Bullet")
        table = sec.get("table")
        if table and table.get("rows"):
            t = d.add_table(rows=1, cols=len(table["columns"]))
            t.style = "Light Grid Accent 1"
            for i, c in enumerate(table["columns"]):
                t.rows[0].cells[i].text = c
            for row in table["rows"]:
                cells = t.add_row().cells
                for i, v in enumerate(row):
                    cells[i].text = str(v if v is not None else "")
    if doc.get("footer"):
        d.add_paragraph(doc["footer"]).italic = True
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@tool("report_template_tool", description="Render standardised report templates to HTML, PDF, DOCX or JSON", timeout_s=120)
def report_template_tool(doc: dict, fmt: str) -> dict:
    if fmt == "pdf":
        data, pages = render_pdf(doc)
        return {"bytes": data, "pages": pages, "mime": "application/pdf"}
    if fmt == "docx":
        return {"bytes": render_docx(doc), "pages": None,
                "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    if fmt == "html":
        return {"bytes": render_html(doc).encode(), "pages": None, "mime": "text/html"}
    return {"bytes": json.dumps(doc, indent=2, default=str).encode(), "pages": None, "mime": "application/json"}


@tool("cms_connector_tool", description="Policy/coverage lookup and posting decision records to the CMS (mock in v1)")
def cms_connector_tool(db: Session, operation: str, claim_id: str, payload: dict | None = None,
                       claim_number: str | None = None) -> dict:
    connector = get_cms_connector()
    if operation == "lookup_policy":
        return connector.lookup_policy(claim_number or "")
    if operation == "post_record":
        return connector.post(db, claim_id, payload or {})
    raise ValueError(f"unknown CMS operation {operation}")


@tool("notification_tool", description="In-app notifications and optional email for assignments and SLA breaches")
def notification_tool(db: Session, user_ids: list[str], kind: str, title: str, body: str | None = None,
                      claim_id: str | None = None, link: str | None = None, emails: list[str] | None = None) -> int:
    for uid in user_ids:
        notify(db, uid, kind, title, body, claim_id, link)
    host = os.environ.get("SMTP_HOST")
    if host and emails:
        try:  # outbox-style best effort; failures never block the workflow
            msg = EmailMessage()
            msg["Subject"] = title
            msg["From"] = os.environ.get("SMTP_FROM", "claims-ai@localhost")
            msg["To"] = ", ".join(emails)
            msg.set_content(f"{body or title}\n\nOpen the Claims AI work queue for details. (No PHI is included in email.)")
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "25")), timeout=10) as s:
                s.send_message(msg)
        except Exception as exc:
            log.warning("notification_email_failed", error=str(exc))
    return len(user_ids)
