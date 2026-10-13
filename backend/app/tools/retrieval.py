"""Indexing and retrieval tools: embeddings, hybrid search, guideline retrieval, citation resolver (spec §8)."""
from __future__ import annotations

import re

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agents import heuristics as H
from app.config import settings
from app.core.errors import LLMOutputError, LLMUnavailableError, TransientExternalError
from app.models import Document, GuidelineRule, GuidelineSource, Page, PageChunk, PageLine
from app.tools.registry import tool

LOCAL_EMBED_MODEL = "local-hash-256"


@tool("embedding_tool", description="Embeddings for page chunks and guideline rules (Gemini; local fallback)",
      deterministic=False, timeout_s=300)
def embedding_tool(texts: list[str], llm=None, call_ctx=None) -> tuple[list[list[float]], str]:
    if llm is not None and getattr(llm, "enabled", False):
        try:
            return llm.embed(texts, call_ctx), settings.GEMINI_EMBED_MODEL
        except (LLMUnavailableError, LLMOutputError, TransientExternalError):
            pass  # graceful degradation: search keeps working on local vectors
    return [H.local_embedding(t) for t in texts], LOCAL_EMBED_MODEL


def to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def fts_query(q: str) -> str:
    terms = [t for t in re.findall(r"[A-Za-z0-9]+", q) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in terms[:20]) or '""'


def chunk_page_lines(lines: list[PageLine], max_chars: int = 3200, overlap_lines: int = 4) -> list[tuple[int, int, str]]:
    """~1,000-token chunks with overlap that never cross document boundaries (spec §10.2-§10.3)."""
    chunks, start = [], 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and size + len(lines[end].text) < max_chars:
            size += len(lines[end].text) + 1
            end += 1
        end = max(end, start + 1)
        chunks.append((lines[start].line_number, lines[end - 1].line_number, "\n".join(ln.text for ln in lines[start:end])))
        if end >= len(lines):
            break
        start = max(end - overlap_lines, start + 1)
    return chunks


@tool("search_tool", description="Hybrid keyword (FTS5 BM25) + vector search with reciprocal-rank fusion")
def search_tool(db: Session, claim_id: str, q: str, mode: str = "hybrid", limit: int = 20, llm=None,
                call_ctx=None) -> list[dict]:
    keyword: list[dict] = []
    if mode in ("keyword", "hybrid"):
        rows = db.execute(text(
            "SELECT page_id, document_id, page_number, snippet(pages_fts, 0, '[', ']', ' ... ', 12) AS snip, "
            "bm25(pages_fts) AS score FROM pages_fts WHERE pages_fts MATCH :q AND claim_id = :c "
            "ORDER BY score LIMIT :n"), {"q": fts_query(q), "c": claim_id, "n": limit * 2}).mappings().all()
        keyword = [dict(r) for r in rows]
    semantic: list[dict] = []
    if mode in ("semantic", "hybrid"):
        chunks = db.execute(select(PageChunk).where(PageChunk.claim_id == claim_id, PageChunk.embedding.is_not(None))).scalars().all()
        if chunks:
            models = {c.embedding_model for c in chunks}
            use_llm = llm if (settings.GEMINI_EMBED_MODEL in models) else None
            qvecs, _ = embedding_tool([q], use_llm, call_ctx)
            qv = np.asarray(qvecs[0], dtype=np.float32)
            scored = []
            for c in chunks:
                v = from_blob(c.embedding)
                if v.shape != qv.shape:
                    continue
                sim = float(np.dot(v, qv) / ((np.linalg.norm(v) * np.linalg.norm(qv)) or 1))
                scored.append((sim, c))
            scored.sort(key=lambda x: -x[0])
            semantic = [{"page_id": c.page_id, "document_id": c.document_id, "page_number": c.page_number,
                         "snip": c.text[:240], "score": s, "line_start": c.line_start} for s, c in scored[:limit * 2]]
    # reciprocal-rank fusion
    fused: dict[str, dict] = {}
    for lst in (keyword, semantic):
        for rank, hit in enumerate(lst):
            key = hit["page_id"]
            entry = fused.setdefault(key, {**hit, "rrf": 0.0, "sources": []})
            entry["rrf"] += 1.0 / (60 + rank)
            entry["sources"].append("keyword" if lst is keyword else "semantic")
    hits = sorted(fused.values(), key=lambda h: -h["rrf"])[:limit]
    # resolve best matching line for each hit (for citation chips)
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", q) if len(t) > 2]
    for h in hits:
        lines = db.execute(select(PageLine).where(PageLine.page_id == h["page_id"]).order_by(PageLine.line_number)).scalars().all()
        best = max(lines, key=lambda ln: sum(t in ln.text.lower() for t in terms), default=None)
        h["line_number"] = best.line_number if best else 1
        h["line_text"] = best.text if best else ""
        doc = db.get(Document, h["document_id"])
        h["document_title"] = doc.title if doc else None
    return hits


@tool("guideline_retrieval_tool", description="Retrieve guideline rules by jurisdiction, body part, diagnosis, procedure")
def guideline_retrieval_tool(db: Session, query: str, jurisdiction: str | None = None, body_part: str | None = None,
                             diagnosis_codes: list[str] | None = None, procedure_codes: list[str] | None = None,
                             category: str | None = None, limit: int = 8) -> list[dict]:
    stmt = select(GuidelineRule, GuidelineSource).join(GuidelineSource, GuidelineRule.source_id == GuidelineSource.id) \
        .where(GuidelineRule.is_active.is_(True), GuidelineSource.is_active.is_(True))
    rules = db.execute(stmt).all()
    fts_rank: dict[str, int] = {}
    try:
        rows = db.execute(text("SELECT rule_id FROM guideline_rules_fts WHERE guideline_rules_fts MATCH :q "
                               "ORDER BY bm25(guideline_rules_fts) LIMIT 50"), {"q": fts_query(query)}).scalars().all()
        fts_rank = {rid: i for i, rid in enumerate(rows)}
    except Exception:
        pass
    scored = []
    dx = {c.upper() for c in diagnosis_codes or []}
    px = set(procedure_codes or [])
    for rule, src in rules:
        if src.jurisdiction and jurisdiction and src.jurisdiction not in (jurisdiction, "US", "ALL"):
            continue
        if category and rule.category != category:
            continue
        score = 0.0
        if body_part and rule.body_part and rule.body_part.lower() in body_part.lower():
            score += 2
        if dx & {c.upper() for c in rule.diagnosis_codes or []}:
            score += 3
        if px & set(rule.procedure_codes or []):
            score += 3
        q = query.lower()
        score += sum(1.5 for k in rule.keywords or [] if k.lower() in q)
        if rule.id in fts_rank:
            score += 2.0 / (1 + fts_rank[rule.id])
        if score > 0:
            scored.append((score, rule, src))
    scored.sort(key=lambda x: -x[0])
    return [{"rule_id": r.id, "rule_code": r.rule_code, "title": r.title, "source": f"{s.name} {s.edition or ''}".strip(),
             "category": r.category, "criteria_text": r.criteria_text, "max_visits": r.max_visits,
             "max_duration_days": r.max_duration_days, "prerequisites": r.prerequisites,
             "recommendation": r.recommendation, "score": round(sc, 2)} for sc, r, s in scored[:limit]]


@tool("citation_resolver_tool", description="Resolve [doc:page:line] to text and page-image coordinates")
def citation_resolver_tool(db: Session, document_id: str, page_number: int, line_start: int, line_end: int) -> dict:
    page = db.execute(select(Page).where(Page.document_id == document_id, Page.page_number == page_number)).scalar_one_or_none()
    if page is None:
        return {"found": False, "text": "", "bboxes": [], "page_id": None}
    lines = db.execute(select(PageLine).where(PageLine.page_id == page.id, PageLine.line_number >= line_start,
                                              PageLine.line_number <= line_end).order_by(PageLine.line_number)).scalars().all()
    return {"found": bool(lines), "page_id": page.id, "text": " ".join(ln.text for ln in lines),
            "bboxes": [ln.bbox for ln in lines if ln.bbox], "page_text": page.text}
