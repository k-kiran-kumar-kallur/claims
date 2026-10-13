"""Intake Agent - Stage 1 (POC-1, PW-1.1, PW-1.2, PW-1.3) and HITL-0 / await-documents nodes."""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select, text

from app.agents import heuristics as H
from app.agents.common import fmt_date, run_llm, upsert_document_request, upsert_flag
from app.agents.taxonomy import DOC_TYPE_STREAM, EXPECTED_DOC_RULES
from app.core.errors import DocumentProcessingError
from app.core.ids import now_iso, uuid7
from app.core.security import decrypt_str, sha256_hex
from app.models import (
    Claimant,
    DedupGroup,
    Document,
    DocumentRequest,
    Flag,
    Page,
    PageChunk,
    PageLine,
    ReviewContext,
    URDetermination,
)
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node
from app.orchestration.hitl import await_human
from app.repositories.docs import active_documents, alias_map, load_doc_view
from app.schemas.llm import BaselineOut, ReviewContextOut
from app.services import file_store
from app.tools.retrieval import chunk_page_lines, to_blob

BASELINE_FIELDS = ["claim_number", "claimant_name", "employer_name", "insurer", "tpa", "date_of_injury", "body_parts",
                   "mechanism_of_injury", "assigned_adjuster", "jurisdiction_state"]
STATES = {"PENNSYLVANIA": "PA", "NEW JERSEY": "NJ", "NEW YORK": "NY", "CALIFORNIA": "CA", "TEXAS": "TX", "OHIO": "OH",
          "FLORIDA": "FL", "ILLINOIS": "IL", "MARYLAND": "MD", "DELAWARE": "DE"}


# =============================================================================================
# Step 1-2: ingest, OCR, packet splitting and stream routing (POC-1)
# =============================================================================================

def _ingest_email(ctx: AgentContext, doc: Document, data: bytes) -> list[Document]:
    parsed = ctx.tools.call("email_parser_tool", data=data)
    children: list[Document] = []
    body = f"From: {parsed.sender}\nTo: {parsed.to}\nDate: {parsed.date}\nSubject: {parsed.subject}\n\n{parsed.body}"
    parts = [(f"{doc.original_filename} (email body).txt", body.encode(), "text/plain")]
    parts += [(a.filename, a.data, a.mime_type) for a in parsed.attachments]
    for name, payload, mime in parts:
        child = Document(id=uuid7(), claim_id=doc.claim_id, source_channel="email", original_filename=name,
                         mime_type=mime, sha256=sha256_hex(payload), size_bytes=len(payload), parent_document_id=doc.id,
                         status="received", received_at=doc.received_at, uploaded_by=doc.uploaded_by,
                         ingest_run_id=ctx.run_id)
        child.storage_path = file_store.put(file_store.original_path(doc.claim_id, child.id), payload)
        ctx.db.add(child)
        children.append(child)
    doc.status, doc.is_container, doc.status_reason = "split", True, f"email with {len(parsed.attachments)} attachment(s)"
    ctx.audit("document.split", "document", doc.id, after={"children": [c.id for c in children], "kind": "email"})
    ctx.commit()
    return children


def _ingest_file(ctx: AgentContext, doc: Document) -> dict:
    """Render, OCR, split and persist one physical file.  Returns stats.  Commits on success."""
    data = file_store.get(doc.storage_path)
    if doc.mime_type == "message/rfc822":
        stats = {"documents": 0, "pages": 0}
        for child in _ingest_email(ctx, doc, data):
            s = _ingest_file(ctx, child)
            stats["documents"] += s["documents"]
            stats["pages"] += s["pages"]
        return stats
    try:
        pages = ctx.tools.call("pdf_render_tool", data=data, mime_type=doc.mime_type)
    except DocumentProcessingError as exc:
        doc.status, doc.status_reason = "failed", str(exc)
        upsert_document_request(ctx, f"refax:{doc.id}", f"Legible copy of {doc.original_filename}",
                                f"Document could not be processed: {exc}")
        ctx.audit("document.failed", "document", doc.id, after={"reason": str(exc)})
        ctx.commit()
        return {"documents": 0, "pages": 0, "failed": True}

    ocr_conf: dict[int, float] = {}
    for p in pages:  # scanned pages -> Gemini vision OCR
        if p.needs_ocr and p.png:
            res = ctx.tools.call("ocr_tool", png=p.png, llm=ctx.llm, call_ctx=ctx.call_ctx)
            p.lines = [{"text": ln.text, "bbox": ln.bbox[:4] if len(ln.bbox) >= 4 else None} for ln in res.lines if ln.text.strip()]
            ocr_conf[p.number] = res.confidence

    unreadable = [p.number for p in pages if p.needs_ocr and not p.lines]
    for p in pages:  # scanned pages with no OCR text are not blank: keep them visible for human review
        if p.number in unreadable:
            p.lines = [{"text": f"[Scanned page {p.number} of {doc.original_filename} - text not available, OCR required]", "bbox": None}]
    if unreadable:
        upsert_flag(ctx, f"ocr:{doc.id}", flag_type="gap", severity="medium",
                    title=f"{len(unreadable)} scanned page(s) in {doc.original_filename} could not be read",
                    detail="No OCR text is available (Gemini vision disabled or failed). Review the page images manually or re-run with Gemini.",
                    ai_recommendation="Review scanned pages manually")
    page_texts = [[ln["text"] for ln in p.lines] for p in pages]
    segments = ctx.tools.call("packet_splitter_tool", pages=page_texts, llm=ctx.llm if len(pages) > 2 else None,
                              call_ctx=ctx.call_ctx)

    # embeddings for semantic search (network call happens before any write)
    chunk_specs = []
    for p in pages:
        fake_lines = [PageLine(line_number=i + 1, text=ln["text"]) for i, ln in enumerate(p.lines)]
        for ls, le, txt in chunk_page_lines(fake_lines):
            chunk_specs.append((p.number, ls, le, txt))
    vectors, embed_model = ([], None)
    if chunk_specs:
        vectors, embed_model = ctx.tools.call("embedding_tool", texts=[c[3] for c in chunk_specs], llm=ctx.llm,
                                              call_ctx=ctx.call_ctx)

    # ---- persist ----------------------------------------------------------------------------------
    logical: list[tuple[Document, object]] = []
    if len(segments) == 1:
        logical.append((doc, segments[0]))
        doc.title = segments[0].title
    else:
        for seg in segments:
            child = Document(id=uuid7(), claim_id=doc.claim_id, source_channel=doc.source_channel,
                             original_filename=f"{doc.original_filename} [pp. {seg.start}-{seg.end}]",
                             mime_type=doc.mime_type, storage_path=doc.storage_path, parent_document_id=doc.id,
                             page_start=seg.start, page_end=seg.end, page_count=seg.end - seg.start + 1,
                             status="processed", title=seg.title, received_at=doc.received_at,
                             uploaded_by=doc.uploaded_by, ingest_run_id=ctx.run_id)
            ctx.db.add(child)
            logical.append((child, seg))
        doc.is_container, doc.status_reason = True, f"packet split into {len(segments)} documents"

    page_owner: dict[int, tuple[Document, int]] = {}
    for ldoc, seg in logical:
        for i, phys in enumerate(range(seg.start, seg.end + 1), 1):
            page_owner[phys] = (ldoc, i)
    page_ids: dict[int, str] = {}
    for p in pages:
        ldoc, rel = page_owner[p.number]
        text_ = "\n".join(ln["text"] for ln in p.lines)
        image_rel = file_store.put(file_store.page_image_path(doc.claim_id, doc.id, p.number), p.png) if p.png else None
        page = Page(id=uuid7(), document_id=ldoc.id, file_document_id=doc.id, claim_id=doc.claim_id, page_number=rel,
                    source_page_number=p.number, image_path=image_rel, width=p.width, height=p.height, text=text_,
                    text_source="ocr" if p.number in ocr_conf else ("native" if p.lines else "none"),
                    ocr_confidence=ocr_conf.get(p.number), text_hash=sha256_hex(H.normalize_text(text_)) if text_ else None,
                    simhash=format(H.simhash(text_), "x") if text_ else None, is_blank=not text_.strip())
        ctx.db.add(page)
        page_ids[p.number] = page.id
        for i, ln in enumerate(p.lines, 1):
            ctx.db.add(PageLine(id=uuid7(), page_id=page.id, line_number=i, text=ln["text"], bbox=ln.get("bbox")))
        ctx.db.flush()
        ctx.db.execute(text("INSERT INTO pages_fts(text, page_id, claim_id, document_id, page_number) VALUES (:t,:p,:c,:d,:n)"),
                       {"t": text_, "p": page.id, "c": doc.claim_id, "d": ldoc.id, "n": rel})
    for (phys, ls, le, txt), vec in zip(chunk_specs, vectors, strict=False):
        ldoc, rel = page_owner[phys]
        ctx.db.add(PageChunk(id=uuid7(), claim_id=doc.claim_id, document_id=ldoc.id, page_id=page_ids[phys],
                             page_number=rel, line_start=ls, line_end=le, text=txt, embedding=to_blob(vec),
                             embedding_model=embed_model))

    # stream routing by document-type metadata tag (quick rule pass; refined by the Classification Agent)
    for ldoc, seg in logical:
        if seg.is_blank:
            ldoc.status, ldoc.status_reason, ldoc.stream = "noise", "blank page", "legal_admin"
            continue
        seg_lines = [H.Line(1, i + 1, t) for phys in range(seg.start, seg.end + 1) for i, t in enumerate(page_texts[phys - 1])]
        dt, _, _ = H.classify(H.DocView(ldoc.id, "", seg.title, None, seg_lines))
        ldoc.stream = DOC_TYPE_STREAM.get(dt, "legal_admin")
        ldoc.page_count = seg.end - seg.start + 1
        if ldoc is doc:
            doc.status = "processed"
    doc.page_count = len(pages)
    if doc.is_container:
        doc.status = "split"
    low_ocr = [n for n, c in ocr_conf.items() if c < 0.7]
    ctx.audit("document.ingest", "document", doc.id,
              after={"pages": len(pages), "documents": len(logical), "ocr_pages": len(ocr_conf), "low_ocr_pages": low_ocr})
    ctx.commit()
    ctx.emit("tool_called", {"tool": "ingest", "document": doc.original_filename, "pages": len(pages),
                             "documents": len(logical)})
    return {"documents": len(logical), "pages": len(pages), "low_ocr": low_ocr}


def _dedup(ctx: AgentContext) -> int:
    docs = active_documents(ctx.db, ctx.claim_id)
    items = []
    for d in docs:
        txt = "\n".join(ctx.db.execute(select(Page.text).where(Page.document_id == d.id).order_by(Page.page_number)).scalars())
        items.append({"id": d.id, "text": txt, "received_at": d.created_at})
    groups = ctx.tools.call("dedup_tool", items=items)
    removed = 0
    for g in groups:
        for member in g["members"]:
            doc = ctx.db.get(Document, member)
            doc.status, doc.duplicate_of_id = "duplicate", g["canonical"]
            doc.status_reason = f"{g['method']} duplicate of {g['canonical']} (similarity {g['similarity']})"
            for page in ctx.db.execute(select(Page).where(Page.document_id == member)).scalars():
                page.is_duplicate_of = g["canonical"]
            removed += 1
        ctx.db.add(DedupGroup(id=uuid7(), claim_id=ctx.claim_id, canonical_document_id=g["canonical"],
                              member_document_ids=g["members"], method=g["method"], similarity=g["similarity"]))
        ctx.audit("document.dedup", "document", g["canonical"], after=g)
    ctx.commit()
    return removed


# =============================================================================================
# Step 3: baseline extraction and reconciliation (PW-1.1)
# =============================================================================================

def _field(value, conf, doc: H.DocView | None = None, item=None) -> dict:
    return {"value": value, "confidence": conf, "citation": H.citation_for(doc, item) if (doc and item) else None}


def _rules_baseline(views: list[H.DocView]) -> dict[str, dict]:
    froi = [v for v in views if v.doc_type == "Employer's First Report of Injury (FROI)"]
    others = [v for v in views if v not in froi]
    out: dict[str, dict] = {f: _field(None, 0.0) for f in BASELINE_FIELDS}

    def take(field: str, labels: list[str], post=lambda s: s, primary_conf=0.97, other_conf=0.85):
        for group, conf in ((froi, primary_conf), (others, other_conf)):
            for v in group:
                lv = H.first_labeled(v, labels)
                if lv and lv.value:
                    val = post(lv.value)
                    if val:
                        out[field] = _field(val, conf, v, lv)
                        return

    def first_part(s: str) -> str:
        return re.split(r"\s{2,}|,\s*\d|\s+Occupation:|\s+DOB:", s)[0].strip().rstrip(",")

    take("claim_number", ["Claim Number", "Claim #", "Claim No"], lambda s: (re.search(r"[A-Z]{2}-\d{4}-[A-Z]{2}-\d+", s) or re.search(r"\S+", s)).group(0))
    take("claimant_name", ["Employee", "Patient", "Claimant"], first_part)
    take("employer_name", ["Employer"], lambda s: s.split(",")[0].strip())
    take("insurer", ["Insurer", "Insurance Carrier"], first_part)
    take("tpa", ["Third Party Administrator", "TPA"], first_part)
    take("date_of_injury", ["Date of Injury", "Date/Time of Injury", "Incident Date"], lambda s: H.first_date(s))
    take("body_parts", ["Part of Body", "Body Part"], lambda s: ", ".join(H.body_parts(s)) or s)
    take("mechanism_of_injury", ["Description of Accident", "Mechanism of Injury"], lambda s: s[:300])
    take("assigned_adjuster", ["Assigned Adjuster", "Adjuster"], first_part)
    for v in views:
        head = " ".join(ln.text for ln in v.lines[:3]).upper()
        for name, code in STATES.items():
            if name in head:
                out["jurisdiction_state"] = _field(code, 0.97, v, v.lines[0])
                break
        if out["jurisdiction_state"]["value"]:
            break
    if not out["jurisdiction_state"]["value"] and out["claim_number"]["value"]:
        m = re.match(r"WC-\d{4}-([A-Z]{2})-", out["claim_number"]["value"])
        if m:
            out["jurisdiction_state"] = {**out["claim_number"], "value": m.group(1), "confidence": 0.9}
    return out


def _llm_baseline(res: BaselineOut, amap_rev: dict[str, str]) -> tuple[dict[str, dict], list[dict]]:
    from app.repositories.docs import resolve_cites

    out = {}
    for f in BASELINE_FIELDS:
        bf = getattr(res, f)
        cites = resolve_cites([bf.citation] if bf.citation else [], amap_rev)
        val = bf.value
        if f == "date_of_injury":
            val = H.normalize_date(val)
        masked = isinstance(val, str) and bool(re.search(r"\[(CLAIMANT|SSN|DOB|PHONE|EMAIL)\]", val))
        out[f] = {"value": None if masked else val, "confidence": bf.confidence if cites else min(bf.confidence, 0.5),
                  "citation": cites[0] if cites else None, "masked_in_prompt": masked}
    flags = [{"title": u.title, "detail": u.detail, "severity": u.severity,
              "evidence": resolve_cites([u.citation] if u.citation else [], amap_rev)} for u in res.urgent_flags]
    return out, flags


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _reconcile(ctx: AgentContext, baseline: dict[str, dict], views: list[H.DocView]) -> list[dict]:
    claim = ctx.claim
    cl = ctx.db.get(Claimant, claim.claimant_id)
    claim_values = {
        "claim_number": claim.claim_number, "claimant_name": decrypt_str(cl.full_name_enc) if cl else None,
        "employer_name": claim.employer_name, "insurer": claim.insurer, "tpa": claim.tpa,
        "date_of_injury": claim.date_of_injury, "body_parts": ", ".join(claim.body_parts or []) or None,
        "mechanism_of_injury": claim.mechanism_of_injury, "assigned_adjuster": claim.adjuster_name,
        "jurisdiction_state": claim.jurisdiction_state,
    }
    conflicts = []
    for f, entry in baseline.items():
        cv = claim_values.get(f)
        entry["claim_value"] = cv
        entry["conflict"] = False
        if cv and entry.get("value") and f not in ("mechanism_of_injury",):
            a, b = _norm(cv), _norm(entry["value"])
            if f == "body_parts":
                same = bool(set(H.body_parts(cv)) & set(H.body_parts(entry["value"]))) or a == b
            elif f in ("claimant_name", "assigned_adjuster"):
                same = a[:6] in b or b[:6] in a
            else:
                same = a == b or a in b or b in a
            if not same:
                entry["conflict"] = True
                entry["confidence"] = min(entry["confidence"], 0.6)
                conflicts.append({"field": f, "claim_value": cv, "document_value": entry["value"],
                                  "citation": entry.get("citation"),
                                  "note": "Claim metadata disagrees with the source document"})
    # cross-document consistency of the date of injury (FROI vs medical records)
    doi = baseline["date_of_injury"].get("value")
    for v in views:
        lv = H.first_labeled(v, ["Date/Time of Injury", "Date of Injury", "Incident Date"])
        d = H.first_date(lv.value) if lv else None
        if d and doi and d != doi:
            baseline["date_of_injury"]["confidence"] = min(baseline["date_of_injury"]["confidence"], 0.6)
            baseline["date_of_injury"]["conflict"] = True
            conflicts.append({"field": "date_of_injury", "claim_value": doi, "document_value": d,
                              "citation": H.citation_for(v, lv), "note": f"Date of injury differs in {v.title.title()}"})
    # fill empty claim fields (never overwrite user-entered values; conflicts go to HITL-0)
    if not claim.baseline_locked:
        for f, attr in (("employer_name", "employer_name"), ("insurer", "insurer"), ("tpa", "tpa"),
                        ("date_of_injury", "date_of_injury"), ("mechanism_of_injury", "mechanism_of_injury"),
                        ("jurisdiction_state", "jurisdiction_state"), ("assigned_adjuster", "adjuster_name")):
            if not getattr(claim, attr) and baseline[f].get("value"):
                setattr(claim, attr, baseline[f]["value"])
        if not claim.body_parts and baseline["body_parts"].get("value"):
            claim.body_parts = [p.strip() for p in baseline["body_parts"]["value"].split(",") if p.strip()]
    return conflicts


# =============================================================================================
# Step 4: completeness and priority (PW-1.2)
# =============================================================================================

def find_requests(views: list[H.DocView]) -> list[dict]:
    """Provider treatment / utilization requests (MRI, ESI, PT extensions, surgery, medication)."""
    out = []
    for v in views:
        if v.doc_type == "Utilization Review Request/Decision" and not H.find_line(v, r"^Determination\s*:|DETERMINATION LETTER"):
            lv = H.first_labeled(v, ["Requested Treatment", "Request", "Requested Service"])
            if lv:
                prov = H.first_labeled(v, ["Requesting Provider"])
                rdate = H.first_labeled(v, ["Request Date"])
                due = H.first_labeled(v, ["Response Requested By", "Response Due"])
                out.append({"description": lv.value, "type": request_type(lv.value),
                            "provider": prov.value if prov else v.provider, "date": H.first_date(rdate.value) if rdate else v.service_date,
                            "due": H.first_date(due.value) if due else None, "document_id": v.id,
                            "citation": H.citation_for(v, lv)})
    return out


def request_type(text_: str) -> str:
    t = text_.lower()
    if "physical therapy" in t or re.search(r"\bpt\b", t) or "therapy" in t:
        return "pt_extension"
    if "mri" in t:
        return "mri"
    if "epidural" in t or "esi" in t or "injection" in t:
        return "esi"
    if any(k in t for k in ("surgery", "discectomy", "fusion", "laminectomy", "arthroscopy")):
        return "surgery"
    if any(k in t for k in ("mg", "medication", "prescription")):
        return "medication"
    return "other"


def _urgent_flags(ctx: AgentContext, views: list[H.DocView]) -> list[dict]:
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=ctx.settings.URGENT_SURGERY_WINDOW_DAYS)).isoformat()
    flags: list[dict] = []
    determined = ctx.db.execute(select(URDetermination.id).where(URDetermination.claim_id == ctx.claim_id)).first()
    for v in views:
        for i, ln in enumerate(v.lines):
            t = ln.text
            context = (v.lines[i - 1].text + " " + t) if i else t
            m = re.search(r"surgery scheduled\s*(\d{1,2}/\d{1,2}/\d{4})", t, re.I)
            if m:
                d = H.normalize_date(m.group(1))
                if d and today <= d <= soon:
                    flags.append({"key": f"surgery:{d}", "title": f"Surgery scheduled {fmt_date(d)} (within 7 days)",
                                  "severity": "high", "detail": t, "evidence": [H.citation_for(v, ln)]})
            if re.search(r"(bowel|bladder) (dysfunction|incontinence|retention)|saddle (anesthesia|numbness)|cauda equina", t, re.I) \
                    and not re.search(r"\b(denies|no |return|warning|negative|if you|seek care)", context, re.I):
                flags.append({"key": f"redflag:{v.id}:{ln.page}:{ln.line}", "title": "Red-flag neurological symptom documented",
                              "severity": "high", "detail": t, "evidence": [H.citation_for(v, ln)]})
    for req in find_requests(views):
        if req.get("due") and not determined:
            if req["due"] < today:
                flags.append({"key": f"ur_deadline:{req['document_id']}", "severity": "high",
                              "title": f"Utilization request response deadline {fmt_date(req['due'])} has passed with no determination on file",
                              "detail": req["description"], "evidence": [req["citation"]]})
            elif req["due"] <= soon:
                flags.append({"key": f"ur_deadline:{req['document_id']}", "severity": "high",
                              "title": f"Utilization request response due {fmt_date(req['due'])}", "detail": req["description"],
                              "evidence": [req["citation"]]})
    # opioid escalation / prolonged use (pharmacy stream)
    fills = []
    for v in views:
        for row in H.table_rows(v):
            if any(o in row.value.lower() for o in H.OPIOIDS):
                m = re.search(r"Filled (\d{1,2}/\d{1,2}/\d{4})", row.value)
                if m:
                    fills.append((H.normalize_date(m.group(1)), v, row))
    if len(fills) >= 4:
        fills.sort(key=lambda f: f[0])
        span = (date.fromisoformat(fills[-1][0]) - date.fromisoformat(fills[0][0])).days
        flags.append({"key": "opioid:prolonged", "severity": "high" if span > 90 else "medium",
                      "title": f"Opioid therapy: {len(fills)} fills over {span} days",
                      "detail": f"First fill {fmt_date(fills[0][0])}, latest {fmt_date(fills[-1][0])}",
                      "evidence": [H.citation_for(fills[0][1], fills[0][2]), H.citation_for(fills[-1][1], fills[-1][2])]})
    # TTD without a recent work-status slip
    statuses = []
    for v in views:
        for lv in H.labeled_values(v, ["Work Status"]):
            ws = H.work_status_of(lv.value)
            if ws:
                statuses.append((v.service_date or "", ws, v, lv))
    if statuses:
        statuses.sort(key=lambda s: s[0])
        last = statuses[-1]
        if last[1] == "ttd" and last[0] and (date.today() - date.fromisoformat(last[0])).days > 30:
            flags.append({"key": "ttd:stale", "severity": "medium", "title": "TTD status without a recent work-status slip",
                          "detail": f"Last work status (TTD) documented {fmt_date(last[0])}",
                          "evidence": [H.citation_for(last[2], last[3])]})
    return flags


def _completeness(ctx: AgentContext, views: list[H.DocView], policy: dict) -> list[dict]:
    present = {v.doc_type for v in views}
    missing = []
    if "Employer's First Report of Injury (FROI)" not in present:
        missing.append(("baseline:froi", "Employer's First Report of Injury (FROI)", "Required for baseline data (PW-1.1)", "Employer"))
    if not present & {"ED Visit Record", "Primary Care Note", "Orthopedic/Specialist Consultation"}:
        missing.append(("baseline:initial_medical", "Initial medical documentation", "Required for baseline data (PW-1.1)", "Treating provider"))
    for pattern, expected, label in EXPECTED_DOC_RULES:
        if expected in present or expected in ("Imaging Report", "Physical Therapy Progress Note"):
            continue  # imaging/therapy gaps are dated by the Organization Agent's gap detector
        for v in views:
            ln = H.find_line(v, pattern)
            if ln and re.search(r"(performed|completed|status post|on \d)", ln.text, re.I):
                missing.append((f"expected:{expected}", label.capitalize(),
                                f"Referenced in {v.title.title()} ({fmt_date(v.service_date)})", v.provider or v.facility))
                break
    if policy.get("status") == "not_found":
        missing.append(("baseline:policy", "Policy and coverage information", "Policy not found in the CMS", "Insurer"))
    out = []
    for key, desc, reason, frm in missing:
        upsert_document_request(ctx, key, desc, reason, frm, (date.today() + timedelta(days=14)).isoformat())
        out.append({"key": key, "description": desc, "reason": reason})
    return out


# =============================================================================================
# Step 5: review context (PW-1.3)
# =============================================================================================

def _rules_review_context(ctx: AgentContext, baseline: dict, views: list[H.DocView], requests: list[dict]) -> ReviewContextOut:
    for v in sorted(views, key=lambda x: x.service_date or "", reverse=True):
        lv = H.first_labeled(v, ["Assessment", "Diagnosis", "Postoperative Diagnosis"])
        if lv and v.doc_type not in ("Medical Bill", "Pharmacy/Prescription Record"):
            lv.value.split(".")[0]
            break
    surgery = next((H.first_labeled(v, ["Procedure Performed"]) for v in views if v.doc_type == "Operative Report"), None)
    goals = ["Determine current MMI status and anticipated MMI date",
             "Determine current work capacity, restrictions and return-to-work options"]
    if requests:
        goals.append("Assess medical necessity of pending request(s): " + "; ".join(r["description"][:80] for r in requests))
    goals.append("Evaluate treatment against evidence-based guidelines (duration, opioids, stalled recovery)")
    req_text = requests[0]["description"].rstrip(".") if requests else "ongoing treatment"
    question = (f"Is the request for {req_text[0].lower() + req_text[1:]} consistent with the applicable guidelines "
                f"{'after ' + surgery.value.split('(')[0].strip().lower().rstrip('.') + ' ' if surgery else ''}"
                f"given the documented functional progress, and what are the claimant's current MMI status and work capacity?")
    state = baseline.get("jurisdiction_state", {}).get("value") or ctx.claim.jurisdiction_state or "the jurisdiction"
    return ReviewContextOut(
        review_goals=goals, clinical_question=question,
        required_evidence=["Operative report and post-operative notes" if surgery else "Treating provider notes",
                           "Physical therapy notes with visit counts and functional measures (pain, ODI, ROM)",
                           "Functional capacity evaluation and current work-status slip",
                           "Pharmacy history (opioid duration)", "Imaging reports referenced in the record"]
        + (["Utilization review request and supporting documentation"] if requests else []),
        applicable_guidelines=["ODG - Low Back (sample rule set)", "ACOEM - Low Back Disorders (sample rule set)"],
        state_rules=[f"{state} workers' compensation utilization review rules" + (" (34 Pa. Code Ch. 127)" if state == "PA" else "")],
    )


def _review_context(ctx: AgentContext, baseline: dict, views: list[H.DocView], requests: list[dict]) -> str:
    existing = ctx.db.execute(select(ReviewContext).where(ReviewContext.claim_id == ctx.claim_id,
                                                          ReviewContext.is_current.is_(True))).scalar_one_or_none()
    if existing and existing.source == "user":
        return existing.id  # never overwrite the examiner's refined question
    inventory = "\n".join(f"- {v.doc_type or 'Unclassified'}: {v.title} ({fmt_date(v.service_date)})" for v in views)
    res, _src = run_llm(ctx, "review_context", ReviewContextOut,
                        baseline={k: v.get("value") for k, v in baseline.items()}, inventory=inventory,
                        requests="\n".join(f"- {r['description']} ({r['provider']}, {fmt_date(r['date'])})" for r in requests) or "none",
                        guidelines="ODG (sample), ACOEM (sample), state rules")
    rc = res or _rules_review_context(ctx, baseline, views, requests)
    if existing:
        existing.is_current = False
    row = ReviewContext(id=uuid7(), claim_id=ctx.claim_id, review_goals=rc.review_goals,
                        clinical_question=rc.clinical_question, required_evidence=rc.required_evidence,
                        applicable_guidelines=rc.applicable_guidelines, state_rules=rc.state_rules, source="agent")
    ctx.db.add(row)
    ctx.audit("review_context.draft", "review_context", row.id, after={"question": rc.clinical_question})
    return row.id


# =============================================================================================
# Node
# =============================================================================================

@agent_node("intake_agent", "intake")
def intake_agent(state: dict, ctx: AgentContext) -> dict:
    claim = ctx.claim
    claim.status, claim.current_stage = "in_review", "intake"
    errors: list[dict] = []
    received = ctx.db.execute(select(Document).where(Document.claim_id == ctx.claim_id, Document.status == "received")
                              .order_by(Document.created_at)).scalars().all()
    total_pages = 0
    for doc in received:
        stats = _ingest_file(ctx, doc)
        total_pages += stats["pages"]
        if stats.get("failed"):
            errors.append({"node": "intake_agent", "document_id": doc.id, "error": "document processing failed"})
        if total_pages > ctx.settings.MAX_PAGES_PER_RUN:
            raise DocumentProcessingError(f"run exceeds {ctx.settings.MAX_PAGES_PER_RUN} pages")
    removed = _dedup(ctx)

    amap = alias_map(ctx.db, ctx.claim_id)
    docs = active_documents(ctx.db, ctx.claim_id)
    views = []
    for d in docs:
        v = load_doc_view(ctx.db, d, amap[d.id])
        v.doc_type = v.doc_type or H.classify(v)[0]
        v.service_date = v.service_date or H.service_dates(v)[0]
        v.provider = v.provider or H.provider_info(v)[0]
        views.append(v)

    # ---- baseline (PW-1.1) --------------------------------------------------------------------------
    base_docs = [v for v in views if v.doc_type in ("Employer's First Report of Injury (FROI)", "Employer Accident Report",
                                                    "ED Visit Record", "Policy/Coverage Information")] or views[:3]
    rev = {a: i for i, a in amap.items()}
    llm_res, src = run_llm(ctx, "baseline_extraction", BaselineOut,
                           metadata={"claim_number": claim.claim_number, "employer": claim.employer_name,
                                     "date_of_injury": claim.date_of_injury, "jurisdiction": claim.jurisdiction_state},
                           documents="\n\n".join(v.marked(20000) for v in base_docs))
    if llm_res is not None:
        baseline, llm_flags = _llm_baseline(llm_res, rev)
        rules = _rules_baseline(views)
        for f in BASELINE_FIELDS:  # deterministic corroboration of the model output
            if not baseline[f]["value"] and rules[f]["value"]:
                baseline[f] = rules[f]  # includes fields masked before sending to the LLM (data minimisation)
    else:
        baseline, llm_flags = _rules_baseline(views), []
    conflicts = _reconcile(ctx, baseline, views)
    policy = ctx.tools.call("cms_connector_tool", db=ctx.db, operation="lookup_policy", claim_id=ctx.claim_id,
                            claim_number=claim.claim_number)
    claim.baseline = {"fields": baseline, "conflicts": conflicts, "policy": policy, "source": src,
                      "extracted_at": now_iso()}
    doi = claim.date_of_injury or baseline["date_of_injury"].get("value")
    if doi and not claim.baseline_locked:
        claim.time_window_start = (date.fromisoformat(doi) - timedelta(days=730)).isoformat()
        claim.time_window_end = date.today().isoformat()
    ctx.audit("baseline.extract", "claim", claim.id, after={"conflicts": len(conflicts), "source": src})

    # ---- completeness and urgency (PW-1.2) -------------------------------------------------------------
    missing = _completeness(ctx, views, policy)
    urgent = _urgent_flags(ctx, views) + [{**f, "key": f"llm:{_norm(f['title'])[:40]}"} for f in llm_flags]
    seen = set()
    for f in urgent:
        if f["key"] in seen:
            continue
        seen.add(f["key"])
        upsert_flag(ctx, f"urgent:{f['key']}", flag_type="urgent", severity=f["severity"], title=f["title"],
                    detail=f.get("detail"), evidence=f.get("evidence", []),
                    ai_recommendation="Review immediately and take action" if f["severity"] == "high" else "Review")
    for c in conflicts:
        upsert_flag(ctx, f"baseline:{c['field']}", flag_type="baseline_conflict", severity="high",
                    title=f"Baseline conflict: {c['field'].replace('_', ' ')}",
                    detail=f"Claim metadata '{c['claim_value']}' vs document '{c['document_value']}'",
                    evidence=[c["citation"]] if c.get("citation") else [],
                    ai_recommendation="Confirm the correct value at HITL-0")

    # ---- review context (PW-1.3) ---------------------------------------------------------------------
    requests = find_requests(views)
    rc_id = _review_context(ctx, baseline, views, requests)

    low = [f for f, e in baseline.items() if e.get("value") and e["confidence"] < ctx.settings.CONFIDENCE_THRESHOLD_BASELINE]
    missing_required = [f for f in ("claim_number", "date_of_injury", "body_parts") if not baseline[f].get("value")]
    needs = (not claim.baseline_locked) and bool(conflicts or low or missing_required)
    ctx.commit()
    ctx.emit("tool_called", {"tool": "intake_summary", "documents": len(views), "duplicates_removed": removed,
                             "urgent_flags": len(seen), "missing_documents": len(missing),
                             "baseline_needs_confirmation": needs})
    return {"document_ids": [v.id for v in views], "missing_documents": missing,
            "urgent_flags": [{"title": f["title"], "severity": f["severity"]} for f in urgent],
            "review_context_id": rc_id, "baseline_needs_confirmation": needs, "errors": errors,
            "stage_status": {"intake": "awaiting_review" if needs else "completed"}}


@agent_node("hitl_baseline", "intake")
def hitl_baseline(state: dict, ctx: AgentContext) -> dict:
    """HITL-0 Baseline Confirm (Claims Examiner / Summarization Team)."""
    iteration = (state.get("retry_counts") or {}).get("intake_loop", 0)

    def payload():
        claim = ctx.claim
        rc = ctx.db.get(ReviewContext, state.get("review_context_id")) if state.get("review_context_id") else None
        reqs = ctx.db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == ctx.claim_id,
                                                            DocumentRequest.status == "open")).scalars().all()
        urgent = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id, Flag.flag_type == "urgent")).scalars().all()
        return {"baseline": claim.baseline.get("fields", {}), "conflicts": claim.baseline.get("conflicts", []),
                "policy": claim.baseline.get("policy"),
                "time_window": {"start": claim.time_window_start, "end": claim.time_window_end},
                "review_context": {"id": rc.id, "review_goals": rc.review_goals, "clinical_question": rc.clinical_question,
                                   "required_evidence": rc.required_evidence,
                                   "applicable_guidelines": rc.applicable_guidelines, "state_rules": rc.state_rules} if rc else None,
                "document_requests": [{"id": r.id, "description": r.description, "reason": r.reason} for r in reqs],
                "urgent_flags": [{"id": f.id, "title": f.title, "severity": f.severity} for f in urgent]}

    review, response = await_human(ctx, "HITL-0", iteration, "Confirm claim baseline and review goals", payload, priority=2)
    return {"human_feedback": [{"checkpoint": "HITL-0", "review_id": review.id, "response": response}],
            "baseline_needs_confirmation": False, "stage_status": {"intake": "completed"}}


@agent_node("await_documents", "intake")
def await_documents(state: dict, ctx: AgentContext) -> dict:
    """Run pauses (awaiting_documents) until requested records are uploaded and the run is resumed."""
    iteration = (state.get("retry_counts") or {}).get("await_docs", 0)

    def payload():
        reqs = ctx.db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == ctx.claim_id,
                                                            DocumentRequest.status.in_(["open", "sent"]))).scalars().all()
        return {"document_requests": [{"id": r.id, "description": r.description, "reason": r.reason,
                                       "requested_from": r.requested_from, "due_date": r.due_date, "status": r.status}
                                      for r in reqs],
                "instructions": "Upload the requested records to the claim, then resume the run."}

    review, response = await_human(ctx, "AWAIT-DOCS", iteration, "Awaiting requested records", payload, priority=2)
    return {"human_feedback": [{"checkpoint": "AWAIT-DOCS", "review_id": review.id, "response": response}],
            "retry_counts": {"await_docs": iteration + 1, "intake_loop": (state.get("retry_counts") or {}).get("intake_loop", 0) + 1},
            "mode": "incremental"}
