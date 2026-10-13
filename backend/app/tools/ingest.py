"""ingest_tool, email_parser_tool, pdf_render_tool, ocr_tool (spec §8)."""
from __future__ import annotations

import email
import email.policy
import io
import socket
import zipfile
from dataclasses import dataclass, field

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.config import settings
from app.core.errors import BadRequest, DocumentProcessingError, PayloadTooLarge
from app.core.security import sha256_hex
from app.tools.registry import tool

RENDER_SCALE = 150 / 72  # 150 DPI keeps 300-page packages manageable; configurable here
ALLOWED_MIME = {
    "application/pdf", "image/tiff", "image/png", "image/jpeg", "message/rfc822",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain",
}


def sniff_mime(data: bytes, filename: str) -> str:
    """Magic-byte MIME detection (never trust the client-supplied content type)."""
    head = data[:8]
    name = filename.lower()
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except zipfile.BadZipFile:
            pass
        return "application/zip"
    if name.endswith(".eml") or (b"\nSubject:" in data[:4096] and b"\nFrom:" in data[:4096]) or data[:5] in (b"From:", b"Recei", b"Retur", b"MIME-"):
        return "message/rfc822"
    if name.endswith(".msg"):
        return "application/vnd.ms-outlook"
    try:
        data[:4096].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def virus_scan(data: bytes) -> None:
    """Optional ClamAV scan via clamd INSTREAM when CLAMAV_HOST is configured."""
    import os

    host = os.environ.get("CLAMAV_HOST")
    if not host:
        return
    port = int(os.environ.get("CLAMAV_PORT", "3310"))
    with socket.create_connection((host, port), timeout=30) as s:
        s.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), 8192):
            chunk = data[i:i + 8192]
            s.sendall(len(chunk).to_bytes(4, "big") + chunk)
        s.sendall(b"\0\0\0\0")
        reply = s.recv(4096).decode(errors="ignore")
    if "FOUND" in reply:
        raise BadRequest(f"Upload rejected by antivirus scan: {reply.strip()}")


@tool("ingest_tool", description="Validate upload, detect MIME, virus-scan, compute SHA-256")
def ingest_tool(data: bytes, filename: str) -> dict:
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise PayloadTooLarge(f"{filename} exceeds {settings.MAX_UPLOAD_MB} MB")
    if not data:
        raise BadRequest(f"{filename} is empty")
    mime = sniff_mime(data, filename)
    if mime == "application/vnd.ms-outlook":
        try:
            import extract_msg  # noqa: F401
        except ImportError as exc:
            raise BadRequest(".msg files require the optional extract-msg package; upload .eml instead") from exc
    elif mime not in ALLOWED_MIME:
        raise BadRequest(f"Unsupported file type for {filename} ({mime})")
    virus_scan(data)
    return {"mime_type": mime, "sha256": sha256_hex(data), "size_bytes": len(data)}


@dataclass
class EmailPart:
    filename: str
    data: bytes
    mime_type: str


@dataclass
class ParsedEmail:
    subject: str
    sender: str
    to: str
    date: str
    body: str
    attachments: list[EmailPart] = field(default_factory=list)


@tool("email_parser_tool", description="Extract body and attachments from .eml/.msg")
def email_parser_tool(data: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    atts = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        name = part.get_filename() or "attachment.bin"
        atts.append(EmailPart(name, payload, sniff_mime(payload, name)))
    return ParsedEmail(str(msg.get("Subject", "")), str(msg.get("From", "")), str(msg.get("To", "")),
                       str(msg.get("Date", "")), body, atts)


@dataclass
class RenderedPage:
    number: int
    png: bytes | None
    width: float
    height: float
    lines: list[dict]  # {"text", "bbox": [x0,y0,x1,y1] normalised}
    needs_ocr: bool


def _text_pages(text: str, lines_per_page: int = 48) -> list[RenderedPage]:
    """Render plain text (email bodies, DOCX) as simple page images so every page has an image + lines."""
    raw = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    wrapped: list[str] = []
    for ln in raw:
        while len(ln) > 100:
            cut = ln.rfind(" ", 0, 100)
            cut = cut if cut > 20 else 100
            wrapped.append(ln[:cut])
            ln = ln[cut:].lstrip()
        wrapped.append(ln)
    pages, font = [], ImageFont.load_default()
    for pi in range(0, max(len(wrapped), 1), lines_per_page):
        chunk = wrapped[pi:pi + lines_per_page]
        w, h = 1275, 1650
        img = Image.new("RGB", (w, h), "white")
        draw = ImageDraw.Draw(img)
        lines, y = [], 80
        for t in chunk:
            if t.strip():
                draw.text((90, y), t, fill="black", font=font)
                lines.append({"text": t.strip(), "bbox": [90 / w, y / h, min(1.0, (90 + 9 * len(t)) / w), (y + 22) / h]})
            y += 30
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        pages.append(RenderedPage(len(pages) + 1, buf.getvalue(), 612, 792, lines, False))
    return pages


@tool("pdf_render_tool", description="Split PDF/TIFF/images into pages, render PNG, extract native text lines",
      timeout_s=600)
def pdf_render_tool(data: bytes, mime_type: str) -> list[RenderedPage]:
    if mime_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentProcessingError("password-protected PDF")
        except DocumentProcessingError:
            raise
        except Exception as exc:
            raise DocumentProcessingError(f"corrupt PDF: {exc}") from exc
        if len(reader.pages) > settings.MAX_PAGES_PER_RUN:
            raise DocumentProcessingError(f"PDF has {len(reader.pages)} pages (limit {settings.MAX_PAGES_PER_RUN})")
        pages: list[RenderedPage] = []
        pdf = pdfium.PdfDocument(data)
        try:
            with pdfplumber.open(io.BytesIO(data)) as plumber:
                for i, ppage in enumerate(plumber.pages):
                    w, h = float(ppage.width), float(ppage.height)
                    lines = []
                    for ln in ppage.extract_text_lines(keep_blank_chars=False):
                        t = ln["text"].strip()
                        if t:
                            lines.append({"text": t, "bbox": [round(ln["x0"] / w, 4), round(ln["top"] / h, 4),
                                                              round(ln["x1"] / w, 4), round(ln["bottom"] / h, 4)]})
                    bitmap = pdf[i].render(scale=RENDER_SCALE).to_pil()
                    buf = io.BytesIO()
                    bitmap.convert("L").save(buf, format="PNG", optimize=True)
                    has_images = bool(ppage.images)
                    pages.append(RenderedPage(i + 1, buf.getvalue(), w, h, lines, needs_ocr=(not lines and has_images)))
        finally:
            pdf.close()
        return pages
    if mime_type in ("image/tiff", "image/png", "image/jpeg"):
        try:
            img = Image.open(io.BytesIO(data))
        except Exception as exc:
            raise DocumentProcessingError(f"unreadable image: {exc}") from exc
        pages = []
        for i in range(getattr(img, "n_frames", 1)):
            img.seek(i)
            frame = img.convert("L")
            buf = io.BytesIO()
            frame.save(buf, format="PNG", optimize=True)
            pages.append(RenderedPage(i + 1, buf.getvalue(), frame.width, frame.height, [], needs_ocr=True))
        return pages
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        import docx

        d = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in d.paragraphs)
        for table in d.tables:
            for row in table.rows:
                text += "\n" + " | ".join(c.text for c in row.cells)
        return _text_pages(text)
    if mime_type == "text/plain":
        return _text_pages(data.decode("utf-8", errors="replace"))
    raise DocumentProcessingError(f"cannot render {mime_type}")


class OcrLine(BaseModel):
    text: str
    bbox: list[float] = Field(default_factory=list, description="[x0,y0,x1,y1] normalised 0..1")


class OcrResult(BaseModel):
    lines: list[OcrLine]
    confidence: float = Field(ge=0, le=1)
    handwriting_present: bool = False


@tool("ocr_tool", description="Gemini vision OCR for scanned pages (lines + bounding boxes)", timeout_s=120,
      deterministic=False)
def ocr_tool(png: bytes, llm, call_ctx) -> OcrResult:
    """`llm` is the gateway; in rules mode there is no OCR engine and the page is routed to humans."""
    from app.core.errors import LLMUnavailableError

    try:
        res = llm.generate_json(
            template="ocr_page", version="1",
            prompt="Transcribe every line of text on this scanned medical-record page in reading order. Return each "
                   "line with a normalised bounding box [x0,y0,x1,y1] (0..1, origin top-left) and an overall "
                   "confidence 0..1. Do not summarise or correct the text.",
            schema=OcrResult, tier="fast", images=[png], ctx=call_ctx)
        return res.data
    except LLMUnavailableError:
        return OcrResult(lines=[], confidence=0.0)
