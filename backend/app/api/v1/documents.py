"""Documents: upload (multipart + chunked), index, viewer, classification edits, split, search (spec §12.3)."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import envelope, get_db, require_permission
from app.api.v1.claims import clinical_access
from app.config import settings
from app.core.errors import BadRequest, NotFound, PayloadTooLarge
from app.core.ids import uuid7
from app.models import (
    Citation,
    Claim,
    Document,
    DocumentClassification,
    DocumentIndex,
    Episode,
    ExtractedFact,
    Page,
    PageLine,
)
from app.repositories.docs import alias_map
from app.services import audit, file_store
from app.services.actions import Principal, reclassify, split_document
from app.services.claims import get_claim_for, upload_documents

router = APIRouter(tags=["documents"])


def _doc_for(db: Session, user: Principal, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise NotFound("Document not found")
    if set(user.roles) == {"attorney"}:
        from app.core.errors import Forbidden
        raise Forbidden("Defence counsel can access approved reports and the chronology only")
    get_claim_for(db, user, doc.claim_id)
    return doc


def doc_dict(d: Document, cls: DocumentClassification | None, alias: str | None = None, episode: Episode | None = None) -> dict:
    return {"id": d.id, "alias": alias, "title": d.title or d.original_filename, "original_filename": d.original_filename,
            "mime_type": d.mime_type, "source_channel": d.source_channel, "stream": d.stream, "status": d.status,
            "status_reason": d.status_reason, "page_count": d.page_count, "parent_document_id": d.parent_document_id,
            "is_container": d.is_container, "received_at": d.received_at, "duplicate_of_id": d.duplicate_of_id,
            "classification": {"doc_type": cls.doc_type, "confidence": cls.confidence, "provider_name": cls.provider_name,
                               "provider_specialty": cls.provider_specialty, "facility": cls.facility,
                               "service_date_start": cls.service_date_start, "service_date_end": cls.service_date_end,
                               "body_parts": cls.body_parts, "tags": cls.tags, "icd10_codes": cls.icd10_codes,
                               "cpt_codes": cls.cpt_codes, "rationale": cls.rationale, "classified_by": cls.classified_by,
                               "version": cls.version, "needs_attention": cls.needs_attention} if cls else None,
            "episode": {"id": episode.id, "label": episode.label} if episode else None}


@router.post("/claims/{claim_id}/documents", status_code=201)
async def upload(claim_id: str, files: list[UploadFile] = File(...), source_channel: str = Form("upload"),
                 db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:upload"))):
    claim = get_claim_for(db, user, claim_id)
    payload = []
    for f in files:
        data = await f.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise PayloadTooLarge(f"{f.filename} exceeds {settings.MAX_UPLOAD_MB} MB")
        payload.append((f.filename or "upload.bin", data))
    docs = upload_documents(db, user, claim, payload, source_channel)
    return envelope([{"document_id": d.id, "filename": d.original_filename, "status": d.status, "mime_type": d.mime_type} for d in docs])


# ---- chunked uploads for large files (> 50 MB) ------------------------------------------------------

class ChunkInit(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    total_size: int = Field(gt=0)
    source_channel: str = "upload"


@router.post("/claims/{claim_id}/documents/uploads", status_code=201)
def init_upload(claim_id: str, body: ChunkInit, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:upload"))):
    claim = get_claim_for(db, user, claim_id)
    if body.total_size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise PayloadTooLarge(f"File exceeds {settings.MAX_UPLOAD_MB} MB")
    upload_id = uuid7()
    file_store.put(f"{claim.id}/uploads/{upload_id}/meta", f"{body.filename}\n{body.total_size}\n{body.source_channel}\n{user.id}".encode())
    return envelope({"upload_id": upload_id, "chunk_size": settings.CHUNK_UPLOAD_MAX_MB * 1024 * 1024})


@router.put("/claims/{claim_id}/documents/uploads/{upload_id}/chunks/{n}")
async def put_chunk(claim_id: str, upload_id: str, n: int, request: Request, db: Session = Depends(get_db),
                    user: Principal = Depends(require_permission("document:upload"))):
    claim = get_claim_for(db, user, claim_id)
    if not file_store.exists(f"{claim.id}/uploads/{upload_id}/meta") or n < 0 or n > 10_000:
        raise NotFound("Unknown upload")
    data = await request.body()
    if len(data) > settings.CHUNK_UPLOAD_MAX_MB * 1024 * 1024:
        raise PayloadTooLarge("Chunk too large")
    file_store.put(f"{claim.id}/uploads/{upload_id}/{n:05d}", data)
    return envelope({"chunk": n, "size": len(data)})


@router.post("/claims/{claim_id}/documents/uploads/{upload_id}/complete", status_code=201)
def complete_upload(claim_id: str, upload_id: str, total_chunks: int, db: Session = Depends(get_db),
                    user: Principal = Depends(require_permission("document:upload"))):
    claim = get_claim_for(db, user, claim_id)
    meta_path = f"{claim.id}/uploads/{upload_id}/meta"
    if not file_store.exists(meta_path):
        raise NotFound("Unknown upload")
    filename, total, channel, owner = file_store.get(meta_path).decode().split("\n")
    if owner != user.id:
        raise BadRequest("Upload belongs to another user")
    buf = io.BytesIO()
    for n in range(total_chunks):
        path = f"{claim.id}/uploads/{upload_id}/{n:05d}"
        if not file_store.exists(path):
            raise BadRequest(f"Missing chunk {n}")
        buf.write(file_store.get(path))
    data = buf.getvalue()
    if len(data) != int(total):
        raise BadRequest(f"Assembled size {len(data)} does not match declared size {total}")
    docs = upload_documents(db, user, claim, [(filename, data)], channel)
    return envelope({"document_id": docs[0].id, "status": docs[0].status})


# ---- index / viewer -------------------------------------------------------------------------------

@router.get("/claims/{claim_id}/documents")
def list_documents(doc_type: str | None = None, stream: str | None = None, episode_id: str | None = None, provider: str | None = None,
                   date_from: str | None = None, date_to: str | None = None, status: str | None = None,
                   claim: Claim = Depends(clinical_access), db: Session = Depends(get_db)):
    docs = db.execute(select(Document).where(Document.claim_id == claim.id).order_by(Document.created_at)).scalars().all()
    amap = alias_map(db, claim.id)
    cls = {c.document_id: c for c in db.execute(select(DocumentClassification).where(
        DocumentClassification.document_id.in_([d.id for d in docs]), DocumentClassification.is_current.is_(True))).scalars()}
    version = db.execute(select(func.max(DocumentIndex.timeline_version)).where(DocumentIndex.claim_id == claim.id)).scalar()
    idx = {i.document_id: i for i in db.execute(select(DocumentIndex).where(DocumentIndex.claim_id == claim.id,
                                                                            DocumentIndex.timeline_version == version)).scalars()}
    eps = {e.id: e for e in db.execute(select(Episode).where(Episode.claim_id == claim.id, Episode.timeline_version == version)).scalars()}
    out = []
    for d in docs:
        c = cls.get(d.id)
        if doc_type and (not c or c.doc_type != doc_type):
            continue
        if stream and d.stream != stream:
            continue
        if status and d.status != status:
            continue
        i = idx.get(d.id)
        if episode_id and (not i or i.episode_id != episode_id):
            continue
        if provider and (not c or not c.provider_name or provider.lower() not in c.provider_name.lower()):
            continue
        if date_from and (not c or (c.service_date_start or "") < date_from):
            continue
        if date_to and (not c or (c.service_date_start or "9999") > date_to):
            continue
        item = doc_dict(d, c, amap.get(d.id), eps.get(i.episode_id) if i else None)
        item["sort_order"] = i.sort_order if i else None
        out.append(item)
    out.sort(key=lambda x: (x["sort_order"] is None, x["sort_order"] or 0))
    return envelope(out, timeline_version=version)


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    doc = _doc_for(db, user, doc_id)
    history = db.execute(select(DocumentClassification).where(DocumentClassification.document_id == doc.id)
                         .order_by(DocumentClassification.version)).scalars().all()
    pages = db.execute(select(Page).where(Page.document_id == doc.id).order_by(Page.page_number)).scalars().all()
    facts = db.execute(select(ExtractedFact).where(ExtractedFact.document_id == doc.id, ExtractedFact.is_current.is_(True))).scalars().all()
    cites = {}
    for c in db.execute(select(Citation).where(Citation.owner_type == "fact", Citation.owner_id.in_([f.id for f in facts]))).scalars():
        cites.setdefault(c.owner_id, []).append({"id": c.id, "page_number": c.page_number, "line_start": c.line_start, "line_end": c.line_end})
    current = next((h for h in history if h.is_current), None)
    amap = alias_map(db, doc.claim_id)
    return envelope({**doc_dict(doc, current, amap.get(doc.id)),
                     "classification_history": [h.to_dict() for h in history],
                     "pages": [{"page_number": p.page_number, "source_page_number": p.source_page_number, "text_source": p.text_source,
                                "ocr_confidence": p.ocr_confidence, "is_blank": p.is_blank, "has_image": bool(p.image_path),
                                "width": p.width, "height": p.height} for p in pages],
                     "facts": [{"id": f.id, "fact_type": f.fact_type, "label": f.label, "validation_status": f.validation_status,
                                "effective_date": f.effective_date, "citations": cites.get(f.id, [])} for f in facts]})


def _page(db: Session, doc: Document, n: int) -> Page:
    page = db.execute(select(Page).where(Page.document_id == doc.id, Page.page_number == n)).scalar_one_or_none()
    if page is None:
        raise NotFound("Page not found")
    return page


@router.get("/documents/{doc_id}/pages/{n}/image")
def page_image(doc_id: str, n: int, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    doc = _doc_for(db, user, doc_id)
    page = _page(db, doc, n)
    if not page.image_path:
        raise NotFound("No image for this page")
    data = file_store.get(page.image_path)
    audit.record(db, action="phi.view", entity_type="page_image", entity_id=page.id, claim_id=doc.claim_id, actor_id=user.id, ip=user.ip)
    return StreamingResponse(io.BytesIO(data), media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/documents/{doc_id}/pages/{n}/text")
def page_text(doc_id: str, n: int, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))):
    doc = _doc_for(db, user, doc_id)
    page = _page(db, doc, n)
    lines = db.execute(select(PageLine).where(PageLine.page_id == page.id).order_by(PageLine.line_number)).scalars().all()
    audit.record(db, action="phi.view", entity_type="page_text", entity_id=page.id, claim_id=doc.claim_id, actor_id=user.id, ip=user.ip)
    return envelope({"page_id": page.id, "page_number": page.page_number, "text_source": page.text_source,
                     "ocr_confidence": page.ocr_confidence,
                     "lines": [{"line_number": ln.line_number, "text": ln.text, "bbox": ln.bbox} for ln in lines]})


class ClassificationPatch(BaseModel):
    doc_type: str
    tags: dict | None = None
    reason: str = Field(min_length=3)


@router.patch("/documents/{doc_id}/classification")
def patch_classification(doc_id: str, body: ClassificationPatch, db: Session = Depends(get_db),
                         user: Principal = Depends(require_permission("classification:edit"))):
    doc = _doc_for(db, user, doc_id)
    row = reclassify(db, doc, user, body.doc_type, body.tags, body.reason)
    return envelope(row.to_dict())


class SplitIn(BaseModel):
    page_ranges: list[list[int]] = Field(min_length=2)
    reason: str | None = None


@router.post("/documents/{doc_id}/split", status_code=201)
def split(doc_id: str, body: SplitIn, db: Session = Depends(get_db), user: Principal = Depends(require_permission("classification:edit"))):
    doc = _doc_for(db, user, doc_id)
    if doc.is_container or doc.status not in ("processed", "noise"):
        raise BadRequest("Only processed, unsplit documents can be split")
    children = split_document(db, doc, user, body.page_ranges, body.reason)
    return envelope([{"document_id": c.id, "title": c.title, "page_start": c.page_start, "page_end": c.page_end} for c in children])


@router.get("/claims/{claim_id}/search")
def search(q: str, mode: str = "hybrid", claim: Claim = Depends(clinical_access), db: Session = Depends(get_db),
           user: Principal = Depends(require_permission("document:view_phi"))):
    if mode not in ("keyword", "semantic", "hybrid"):
        raise BadRequest("mode must be keyword, semantic or hybrid")
    if len(q.strip()) < 2:
        raise BadRequest("Query too short")
    from app.llm.gateway import get_gateway
    from app.tools.retrieval import search_tool

    hits = search_tool(db, claim.id, q, mode, 25, get_gateway(), None)
    audit.record(db, action="search.execute", entity_type="claim", entity_id=claim.id, claim_id=claim.id, actor_id=user.id,
                 after={"mode": mode, "hits": len(hits)})
    return envelope([{"document_id": h["document_id"], "document_title": h.get("document_title"), "page_number": h["page_number"],
                      "line_number": h.get("line_number"), "line_text": h.get("line_text"), "snippet": h.get("snip"),
                      "sources": h.get("sources"), "score": round(h["rrf"], 4)} for h in hits])
