"""Data access helpers for documents, pages and citations used by agents and API services."""
from __future__ import annotations

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.heuristics import DocView, Line
from app.core.ids import uuid7
from app.models import Citation, Document, DocumentClassification, Page, PageLine

ACTIVE_STATUSES = ("processed",)


def alias_map(db: Session, claim_id: str) -> dict[str, str]:
    ids = db.execute(select(Document.id).where(Document.claim_id == claim_id).order_by(Document.created_at, Document.id)).scalars()
    return {doc_id: f"D{i}" for i, doc_id in enumerate(ids, 1)}


def current_classification(db: Session, document_id: str) -> DocumentClassification | None:
    return db.execute(select(DocumentClassification).where(DocumentClassification.document_id == document_id,
                                                            DocumentClassification.is_current.is_(True))
                      .order_by(DocumentClassification.version.desc()).limit(1)).scalar_one_or_none()


def classifications_for(db: Session, doc_ids: list[str]) -> dict[str, DocumentClassification]:
    if not doc_ids:
        return {}
    rows = db.execute(select(DocumentClassification).where(DocumentClassification.document_id.in_(doc_ids),
                                                           DocumentClassification.is_current.is_(True))).scalars()
    return {r.document_id: r for r in rows}


def active_documents(db: Session, claim_id: str, include_noise: bool = False) -> list[Document]:
    statuses = ACTIVE_STATUSES + (("noise",) if include_noise else ())
    return list(db.execute(select(Document).where(Document.claim_id == claim_id, Document.status.in_(statuses),
                                                  Document.is_container.is_(False)).order_by(Document.created_at)).scalars())


def load_doc_view(db: Session, doc: Document, alias: str, cls: DocumentClassification | None = None) -> DocView:
    pages = db.execute(select(Page).where(Page.document_id == doc.id).order_by(Page.page_number)).scalars().all()
    page_ids = {p.page_number: p.id for p in pages}
    lines: list[Line] = []
    if pages:
        rows = db.execute(select(PageLine).where(PageLine.page_id.in_(list(page_ids.values())))
                          .order_by(PageLine.page_id, PageLine.line_number)).scalars().all()
        by_page: dict[str, list[PageLine]] = {}
        for r in rows:
            by_page.setdefault(r.page_id, []).append(r)
        for p in pages:
            for r in by_page.get(p.id, []):
                lines.append(Line(p.page_number, r.line_number, r.text))
    cls = cls if cls is not None else current_classification(db, doc.id)
    return DocView(id=doc.id, alias=alias, title=doc.title or doc.original_filename, doc_type=cls.doc_type if cls else None,
                   lines=lines, service_date=cls.service_date_start if cls else None,
                   provider=cls.provider_name if cls else None, facility=cls.facility if cls else None, page_ids=page_ids)


def load_doc_views(db: Session, claim_id: str, doc_ids: list[str] | None = None) -> list[DocView]:
    amap = alias_map(db, claim_id)
    docs = active_documents(db, claim_id) if doc_ids is None else [d for d in (db.get(Document, i) for i in doc_ids) if d]
    cls = classifications_for(db, [d.id for d in docs])
    views = [load_doc_view(db, d, amap[d.id], cls.get(d.id)) for d in docs]
    views.sort(key=lambda v: (v.service_date or "9999-12-31", v.alias))
    return views


# ---- citations ---------------------------------------------------------------------------------

def page_lines(db: Session, document_id: str, page_number: int) -> tuple[Page | None, list[PageLine]]:
    page = db.execute(select(Page).where(Page.document_id == document_id, Page.page_number == page_number)).scalar_one_or_none()
    if page is None:
        return None, []
    lines = db.execute(select(PageLine).where(PageLine.page_id == page.id).order_by(PageLine.line_number)).scalars().all()
    return page, list(lines)


def best_match(db: Session, document_id: str, page_number: int, line_start: int, line_end: int, quote: str,
               window: int = 3) -> dict:
    """Score the quote against the cited lines; search nearby lines (and other pages) if the model was off by a few."""
    page, lines = page_lines(db, document_id, page_number)
    q = " ".join(quote.split()).lower()
    if not q:
        return {"score": 0.0, "page_id": page.id if page else None, "line_start": line_start, "line_end": line_end,
                "page_number": page_number}

    def score_range(ls: list[PageLine], a: int, b: int) -> float:
        txt = " ".join(x.text for x in ls if a <= x.line_number <= b).lower()
        if not txt:
            return 0.0
        return fuzz.partial_ratio(q, txt) / 100 if len(q) <= len(txt) else fuzz.ratio(q, txt) / 100

    best = {"score": score_range(lines, line_start, line_end), "page_id": page.id if page else None,
            "line_start": line_start, "line_end": line_end, "page_number": page_number}
    if best["score"] >= 0.97:
        return best
    span = max(line_end - line_start, 0)
    for a in range(max(1, line_start - window), line_start + window + 1):
        for extra in (0, 1, 2):
            b = a + span + extra
            s = score_range(lines, a, b)
            if s > best["score"] + 0.01:
                best = {"score": s, "page_id": page.id if page else None, "line_start": a, "line_end": b,
                        "page_number": page_number}
    if best["score"] < 0.9:  # wrong page number from the model: scan the whole document
        pages = db.execute(select(Page).where(Page.document_id == document_id)).scalars().all()
        for p in pages:
            if p.page_number == page_number:
                continue
            _, pl = page_lines(db, document_id, p.page_number)
            for ln in pl:
                s = score_range(pl, ln.line_number, ln.line_number + span)
                if s > best["score"] + 0.01:
                    best = {"score": s, "page_id": p.id, "line_start": ln.line_number,
                            "line_end": ln.line_number + span, "page_number": p.page_number}
    return best


def resolve_cites(cites: list, alias_rev: dict[str, str]) -> list[dict]:
    """LLM `Cite` objects (doc alias) -> citation dicts with document ids; unknown aliases are dropped."""
    out = []
    for c in cites or []:
        alias = c.doc if c.doc.startswith("D") else f"D{c.doc}"
        doc_id = alias_rev.get(alias)
        if doc_id:
            out.append({"document_id": doc_id, "page_number": c.page, "line_start": c.line_start,
                        "line_end": max(c.line_end, c.line_start), "quote": c.quote})
    return out


def save_citations(db: Session, owner_type: str, owner_id: str, cites: list[dict], fact_id: str | None = None,
                   rescore: bool = True) -> list[Citation]:
    out = []
    for c in cites:
        if rescore:
            m = best_match(db, c["document_id"], c["page_number"], c["line_start"], c["line_end"], c.get("quote", ""))
        else:
            page, _ = page_lines(db, c["document_id"], c["page_number"])
            m = {"score": c.get("match_score"), "page_id": page.id if page else None, "line_start": c["line_start"],
                 "line_end": c["line_end"], "page_number": c["page_number"]}
        row = Citation(id=uuid7(), owner_type=owner_type, owner_id=owner_id, fact_id=fact_id,
                       document_id=c["document_id"], page_id=m["page_id"], page_number=m["page_number"],
                       line_start=m["line_start"], line_end=m["line_end"], quote=(c.get("quote") or "")[:1000],
                       match_score=round(m["score"], 3) if m["score"] is not None else None)
        db.add(row)
        out.append(row)
    return out


def citations_for(db: Session, owner_type: str, owner_ids: list[str]) -> dict[str, list[Citation]]:
    if not owner_ids:
        return {}
    rows = db.execute(select(Citation).where(Citation.owner_type == owner_type, Citation.owner_id.in_(owner_ids))).scalars()
    out: dict[str, list[Citation]] = {}
    for r in rows:
        out.setdefault(r.owner_id, []).append(r)
    return out


def citation_dict(c: Citation) -> dict:
    return {"id": c.id, "document_id": c.document_id, "page_number": c.page_number, "line_start": c.line_start,
            "line_end": c.line_end, "quote": c.quote, "match_score": c.match_score}
