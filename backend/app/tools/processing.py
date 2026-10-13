"""Document processing tools: packet splitting, dedup, classification, dates, codes, timeline, gaps, durations."""
from __future__ import annotations

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import heuristics as H
from app.agents.taxonomy import DOC_TYPE_STREAM, DOC_TYPES, EXPECTED_DOC_RULES
from app.core.errors import LLMOutputError, LLMUnavailableError
from app.models import CodeEntry
from app.schemas.llm import BoundariesOut, ClassificationOut, ClassificationTags
from app.tools.registry import tool

# ---- packet splitter -----------------------------------------------------------------------------

PAGE_OF_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)


@dataclass
class Segment:
    start: int  # 1-based physical page numbers, inclusive
    end: int
    title: str
    is_blank: bool = False
    is_cover: bool = False


def _title(lines: list[str]) -> str:
    for t in lines[:4]:
        s = t.strip()
        if len(s) > 6 and s.upper() == s and "|" not in s and not s.startswith("PATIENT"):
            return s[:120]
    for t in lines[:3]:
        if t.strip():
            return t.strip()[:120]
    return "Untitled"


def heuristic_boundaries(pages: list[list[str]]) -> list[Segment]:
    segs: list[Segment] = []
    prev_k = prev_n = None
    for idx, lines in enumerate(pages, start=1):
        text = " ".join(lines)
        blank = not text.strip()
        cover = any("FAX COVER" in ln.upper() or "FACSIMILE COVER" in ln.upper() for ln in lines[:3])
        m = None
        for ln in reversed(lines[-3:] if lines else []):
            m = PAGE_OF_RE.search(ln)
            if m:
                break
        k, n = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        prev = segs[-1] if segs else None
        new = (prev is None or blank or cover or prev.is_blank or prev.is_cover or k == 1
               or (prev_k is not None and prev_n is not None and prev_k >= prev_n)
               or (k is None and prev_k is None and _title(lines) != prev.title))
        if new:
            segs.append(Segment(idx, idx, "Blank page" if blank else _title(lines), is_blank=blank, is_cover=cover))
        else:
            segs[-1].end = idx
        prev_k, prev_n = k, n
    return segs


@tool("packet_splitter_tool", description="Detect document boundaries in a multi-document packet", deterministic=False)
def packet_splitter_tool(pages: list[list[str]], llm=None, call_ctx=None) -> list[Segment]:
    segs = heuristic_boundaries(pages)
    if llm is None or not getattr(llm, "enabled", False) or len(pages) < 3:
        return segs
    # Gemini Flash boundary check: confirms/adds boundaries the heuristics may miss (letterhead changes etc.)
    digest = "\n".join(f"[page {i}] " + " / ".join(ln for ln in p[:4] if ln) + (f" ... {p[-1]}" if p else "")
                       for i, p in enumerate(pages, 1))
    try:
        res = llm.generate_json(template="packet_boundaries", version="1", schema=BoundariesOut, tier="fast",
                                prompt="Below are the first lines of each page of a faxed/scanned packet. Identify where "
                                       "each distinct document starts (cover sheets, blank separators, letterhead or "
                                       "document-title changes, 'Page 1 of N' resets). Return every document start "
                                       f"page and its title.\n<document>\n{digest}\n</document>", ctx=call_ctx)
    except (LLMUnavailableError, LLMOutputError):
        return segs
    starts = {s.start for s in segs} | {b.start_page for b in res.data.documents if 1 <= b.start_page <= len(pages)}
    titles = {b.start_page: b.title for b in res.data.documents}
    merged: list[Segment] = []
    for st in sorted(starts):
        base = next((s for s in segs if s.start == st), None)
        merged.append(Segment(st, st, base.title if base else titles.get(st, "Untitled"),
                              base.is_blank if base else False, base.is_cover if base else False))
    for i, s in enumerate(merged):
        s.end = merged[i + 1].start - 1 if i + 1 < len(merged) else len(pages)
    return merged


# ---- dedup ---------------------------------------------------------------------------------------

@tool("dedup_tool", description="Exact (SHA-256 of normalised text) and near-duplicate (SimHash) detection")
def dedup_tool(items: list[dict], near_threshold: int = 3) -> list[dict]:
    """items: [{id, text, received_at}] -> groups [{canonical, members, method, similarity}]"""
    from app.core.security import sha256_hex

    groups: list[dict] = []
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        norm = H.normalize_text(it["text"])
        if len(norm) < 40:
            continue
        by_hash[sha256_hex(norm)].append(it)
    seen: set[str] = set()
    for members in by_hash.values():
        if len(members) > 1:
            members = sorted(members, key=lambda m: (m.get("received_at") or "", m["id"]))
            groups.append({"canonical": members[0]["id"], "members": [m["id"] for m in members[1:]],
                           "method": "exact", "similarity": 1.0})
            seen |= {m["id"] for m in members}
    rest = [it for it in items if it["id"] not in seen and len(H.normalize_text(it["text"])) >= 200]
    hashes = {it["id"]: H.simhash(it["text"]) for it in rest}
    dates = {it["id"]: sorted(set(H.find_dates(it["text"]))) for it in rest}
    used: set[str] = set()
    for i, a in enumerate(rest):
        if a["id"] in used:
            continue
        # templated forms (bills, therapy notes, work slips) differ mainly by dates: a near-duplicate must share them
        dupes = [b for b in rest[i + 1:] if b["id"] not in used and H.hamming(hashes[a["id"]], hashes[b["id"]]) <= near_threshold
                 and dates[a["id"]] == dates[b["id"]]]
        if dupes:
            used |= {d["id"] for d in dupes}
            sim = 1 - max(H.hamming(hashes[a["id"]], hashes[d["id"]]) for d in dupes) / 64
            groups.append({"canonical": a["id"], "members": [d["id"] for d in dupes], "method": "near",
                           "similarity": round(sim, 3)})
    return groups


# ---- classifier ----------------------------------------------------------------------------------

def rules_classification(doc: H.DocView, valid_cpt: set[str] | None = None) -> ClassificationOut:
    doc_type, conf, rationale = H.classify(doc)
    doc.doc_type = doc_type
    start, end = H.service_dates(doc)
    provider, specialty, facility = H.provider_info(doc)
    text = doc.text
    cpts = [c for c in H.cpt_candidates(text) if valid_cpt is None or c in valid_cpt]
    tags = ClassificationTags(
        treatment=[m["name"] + " " + m["dose"] for m in H.medications_in(text)][:8],
        imaging=sorted({w for w in re.findall(r"\b(MRI|X-ray|X-rays|CT scan)\b", text)}),
        surgery=["microdiscectomy"] if re.search(r"microdiscectomy|laminotomy|fusion|arthroscopy", text, re.I) else [],
        therapy=["physical therapy"] if re.search(r"physical therapy|therapeutic exercise", text, re.I) else [],
        work_status=H.work_status_of(" ".join(lv.value for lv in H.labeled_values(doc, ["Work Status"]))) or None,
    )
    return ClassificationOut(doc_type=doc_type, confidence=conf, provider_name=provider, provider_specialty=specialty,
                             facility=facility, service_date_start=start, service_date_end=end,
                             encounter_type=_encounter(doc_type), body_parts=H.body_parts(text), tags=tags,
                             icd10_codes=H.icd_codes(text), cpt_codes=cpts, rationale=f"Rule-based: {rationale}")


def _encounter(doc_type: str) -> str | None:
    return {"ED Visit Record": "emergency", "Operative Report": "surgery", "Post-Op Follow-Up Note": "follow_up",
            "Physical Therapy Progress Note": "therapy", "FCE Report": "evaluation", "IME Report": "ime",
            "Orthopedic/Specialist Consultation": "office_visit"}.get(doc_type)


CLASSIFY_SYSTEM = (
    "Classify one workers' compensation medical-record document. Use headers, layouts, letterheads, form structures "
    "(e.g. CMS-1500 boxes), section titles (Operative Findings, SOAP) and contextual phrases (estimated blood loss, "
    "range of motion, lifting capacity). doc_type MUST be one of: " + "; ".join(DOC_TYPES) + ". Dates as YYYY-MM-DD. "
    "Only report ICD-10 / CPT codes that literally appear in the text. Give a one-sentence rationale."
)


@tool("classifier_tool", description="Document type and granular tags (Gemini Flash, structured output)",
      deterministic=False, timeout_s=180)
def classifier_tool(doc: H.DocView, llm, call_ctx, valid_cpt: set[str] | None = None) -> tuple[ClassificationOut, str]:
    rules = rules_classification(doc, valid_cpt)
    try:
        res = llm.generate_json(template="classify_document", version="1", system=CLASSIFY_SYSTEM,
                                prompt=f"<document>\n{doc.marked(24000)}\n</document>", schema=ClassificationOut,
                                tier="fast", ctx=call_ctx)
    except LLMUnavailableError:
        return rules, "rules"
    except LLMOutputError:
        rules.confidence = min(rules.confidence, 0.6)
        return rules, "rules_fallback"
    out = res.data
    if out.doc_type not in DOC_TYPES:
        out.doc_type, out.confidence = "Other", min(out.confidence, 0.5)
    # deterministic corroboration: codes must literally exist in the text; dates must parse
    text = doc.text
    out.icd10_codes = [c for c in out.icd10_codes if c in text]
    out.cpt_codes = [c for c in out.cpt_codes if c in text]
    out.service_date_start = H.normalize_date(out.service_date_start) or rules.service_date_start
    out.service_date_end = H.normalize_date(out.service_date_end) or out.service_date_start
    if rules.doc_type != "Other" and rules.confidence >= 0.9 and rules.doc_type != out.doc_type:
        out.confidence = min(out.confidence, 0.7)  # disagreement with a strong header match -> human attention
        out.rationale += f" (rule-based header match suggested '{rules.doc_type}')"
    return out, "llm"


# ---- dates & codes -------------------------------------------------------------------------------

@tool("date_normalizer_tool", description="Parse and normalise dates; resolve relative dates (POD 14)")
def date_normalizer_tool(value: str, reference: str | None = None) -> str | None:
    return H.normalize_date(value, reference)


@tool("code_lookup_tool", description="Validate/normalise ICD-10-CM and CPT/HCPCS codes against local code tables")
def code_lookup_tool(db: Session, codes: list[str], system: str = "icd10cm") -> list[dict]:
    out = []
    for raw in codes:
        code = raw.strip().upper()
        if system == "icd10cm" and "." not in code and len(code) > 3:
            code = code[:3] + "." + code[3:]
        entry = db.get(CodeEntry, (system, code))
        if entry is None and system == "icd10cm":
            # accept a valid parent category (e.g. S39.012A -> S39.012)
            entry = db.get(CodeEntry, (system, code[:-1])) or db.get(CodeEntry, (system, code[:3]))
        out.append({"code": code, "valid": entry is not None, "description": entry.description if entry else None,
                    "body_part": entry.body_part if entry else None})
    return out


def valid_cpt_codes(db: Session) -> set[str]:
    return set(db.execute(select(CodeEntry.code).where(CodeEntry.code_system.in_(["cpt", "hcpcs"]))).scalars())


# ---- timeline ------------------------------------------------------------------------------------

@tool("timeline_builder_tool", description="Sort documents by date of service then encounter; group episodes")
def timeline_builder_tool(docs: list[dict], episode_window_days: int = 45) -> list[dict]:
    """docs: [{id, date, doc_type, episode_type, provider}] -> episodes [{episode_type, label, doc_ids, start, end}]"""
    from app.agents.taxonomy import EPISODE_LABELS

    ordered = sorted(docs, key=lambda d: (d.get("date") or "9999-12-31", d.get("order", 0)))
    episodes: list[dict] = []
    open_by_type: dict[str, dict] = {}
    for d in ordered:
        et = d.get("episode_type") or "other"
        ep = open_by_type.get(et)
        # surgery episode absorbs post-op visits; therapy episode absorbs all therapy notes of the course
        within = ep and d.get("date") and ep["end"] and _days(ep["end"], d["date"]) <= (
            400 if et in ("therapy", "surgery") else episode_window_days)
        if ep and (within or not d.get("date")):
            ep["doc_ids"].append(d["id"])
            if d.get("date"):
                ep["end"] = max(ep["end"] or d["date"], d["date"])
            ep["providers"].add(d.get("provider") or "")
        else:
            ep = {"episode_type": et, "label": EPISODE_LABELS.get(et, "Other records"), "doc_ids": [d["id"]],
                  "start": d.get("date"), "end": d.get("date"), "providers": {d.get("provider") or ""}}
            episodes.append(ep)
            open_by_type[et] = ep
    for ep in episodes:
        ep["providers"] = sorted(p for p in ep["providers"] if p)
        if ep["start"]:
            ep["label"] = f"{ep['label']} ({_fmt(ep['start'])}" + (f" - {_fmt(ep['end'])})" if ep["end"] != ep["start"] else ")")
    episodes.sort(key=lambda e: e["start"] or "9999")
    return episodes


def _days(a: str, b: str) -> int:
    return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)


def _fmt(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


# ---- gaps ----------------------------------------------------------------------------------------

@tool("gap_detector_tool", description="Missing referenced records, treatment-interval gaps, visit-count mismatches, date anomalies")
def gap_detector_tool(docs: list[H.DocView], doc_types: dict[str, str], doc_dates: dict[str, str | None],
                      date_of_injury: str | None, gap_days: int = 30, billed: list[dict] | None = None) -> list[dict]:
    gaps: list[dict] = []
    present = set(doc_types.values())
    clinical = [d for d in docs if doc_types.get(d.id) not in (None, "Medical Bill", "Administrative/Fax Cover",
                                                                 "Legal/Correspondence", "Pharmacy/Prescription Record")]
    # 1. referenced but missing records (e.g. "MRI ... reviewed" without an MRI report)
    for d in clinical:
        for ln in d.lines:
            m = re.search(r"\b(MRI|CT|EMG|nerve conduction|X-ray)\b[^.]*?(?:performed|dated|on)?\s*(\d{1,2}/\d{1,2}/\d{4})[^.]*?(reviewed|shows|showed)", ln.text, re.I) \
                or re.search(r"\b(MRI|CT|EMG)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(shows|showed)", ln.text, re.I)
            if m and not _has_imaging_near(H.normalize_date(m.group(2)), doc_types, doc_dates):
                study, dt = m.group(1).upper(), H.normalize_date(m.group(2))
                gaps.append({"gap_type": "missing_referenced_record", "severity": "high",
                             "description": f"{study} dated {H.normalize_date(m.group(2))} is referenced in "
                                            f"{d.title.title()} but the {study} report is not in the file.",
                             "start_date": dt, "end_date": dt, "evidence": [H.citation_for(d, ln)],
                             "request": f"{study} report dated {dt}", "dedup_key": f"missing:{study}:{dt}"})
    for pattern, expected, label in EXPECTED_DOC_RULES:
        if expected in present or expected == "Imaging Report":
            continue
        for d in clinical:
            ln = H.find_line(d, pattern, re.I)
            if ln and doc_types.get(d.id) not in (expected,) and expected not in ("Physical Therapy Progress Note",) \
                    and re.search(r"(performed|scheduled|completed|reviewed|status post)", ln.text, re.I):
                gaps.append({"gap_type": "missing_referenced_record", "severity": "medium",
                             "description": f"Records reference a {label} but no {label} is in the file.",
                             "start_date": doc_dates.get(d.id), "end_date": doc_dates.get(d.id),
                             "evidence": [H.citation_for(d, ln)], "request": label, "dedup_key": f"missing:{label}"})
                break
    # billed services without corresponding clinical records (billing stream corroboration)
    for b in billed or []:
        if b.get("kind") == "imaging" and not _has_imaging_near(b["date"], doc_types, doc_dates) and not any(
                g.get("start_date") == b["date"] for g in gaps):
            gaps.append({"gap_type": "missing_referenced_record", "severity": "medium",
                         "description": f"Billed imaging service {b['code']} on {b['date']} has no imaging report.",
                         "start_date": b["date"], "end_date": b["date"], "evidence": [b["citation"]],
                         "request": f"Imaging report for DOS {b['date']}", "dedup_key": f"missing:billed:{b['code']}:{b['date']}"})
    # 2. treatment-interval gaps
    dated = sorted({doc_dates[d.id] for d in clinical if doc_dates.get(d.id)})
    for a, b in itertools.pairwise(dated):
        if _days(a, b) > gap_days:
            gaps.append({"gap_type": "treatment_interval", "severity": "medium" if _days(a, b) < 60 else "high",
                         "description": f"No clinical encounter for {_days(a, b)} days between {_fmt(a)} and {_fmt(b)} "
                                        f"(threshold {gap_days} days).", "start_date": a, "end_date": b,
                         "evidence": [], "dedup_key": f"interval:{a}:{b}"})
    # 3. visit-count mismatches (prescribed vs documented therapy visits)
    prescribed = None
    for d in clinical:
        if doc_types.get(d.id) in ("Post-Op Follow-Up Note", "Physical Therapy Progress Note", "Rehab Note",
                                   "Orthopedic/Specialist Consultation", "Primary Care Note"):
            for lv in H.labeled_values(d, ["PT/Rehab", "Plan"]):
                fp = H.frequency_plan(lv.value)
                if fp and "physical therapy" in lv.value.lower() and not re.search(r"additional|recommend|request|extension", lv.value, re.I) \
                        and prescribed is None:
                    prescribed = (fp, d, lv)
    visit_numbers = []
    for d in clinical:
        for ln in d.lines[:8]:
            m = re.search(r"Visit:\s*(\d+)\s*of\s*(\d+)", ln.text) if "therap" in d.title.lower() or doc_types.get(d.id) in (
                "Physical Therapy Progress Note", "Rehab Note") else None
            if m:
                visit_numbers.append((int(m.group(1)), int(m.group(2)), d, ln))
    if prescribed and visit_numbers:
        fp, d, lv = prescribed
        max_visit = max(v[0] for v in visit_numbers)
        if max_visit > fp["visits"]:
            gaps.append({"gap_type": "visit_count_mismatch", "severity": "medium",
                         "description": f"{max_visit} therapy visits documented vs {fp['visits']} prescribed.",
                         "evidence": [H.citation_for(d, lv)], "dedup_key": "visits:excess"})
    # 4. date anomalies
    for d in clinical:
        dt = doc_dates.get(d.id)
        if dt and date_of_injury and dt < date_of_injury and doc_types.get(d.id) not in ("Primary Care Note",):
            gaps.append({"gap_type": "date_anomaly", "severity": "low",
                         "description": f"{d.title.title()} is dated {_fmt(dt)}, before the date of injury.",
                         "start_date": dt, "end_date": dt, "evidence": [], "dedup_key": f"anomaly:{d.id}"})
        if dt and dt > date.today().isoformat():
            gaps.append({"gap_type": "date_anomaly", "severity": "medium",
                         "description": f"{d.title.title()} has a future date of service ({_fmt(dt)}).",
                         "start_date": dt, "end_date": dt, "evidence": [], "dedup_key": f"future:{d.id}"})
    return gaps


def _has_imaging_near(when: str | None, doc_types: dict[str, str], doc_dates: dict[str, str | None], days: int = 3) -> bool:
    if not when:
        return True
    return any(t == "Imaging Report" and doc_dates.get(i) and _days(doc_dates[i], when) <= days for i, t in doc_types.items())


# ---- durations -----------------------------------------------------------------------------------

@tool("duration_calculator_tool", description="Compare actual vs guideline durations and visit counts")
def duration_calculator_tool(actual_visits: int | None = None, max_visits: int | None = None,
                             start_date: str | None = None, end_date: str | None = None,
                             max_duration_days: int | None = None) -> dict:
    out: dict = {"actual_visits": actual_visits, "max_visits": max_visits, "max_duration_days": max_duration_days}
    out["visits_exceeded_by"] = (actual_visits - max_visits) if (actual_visits is not None and max_visits is not None
                                                                 and actual_visits > max_visits) else 0
    if start_date and end_date:
        out["actual_days"] = _days(start_date, end_date)
        out["days_exceeded_by"] = max(out["actual_days"] - max_duration_days, 0) if max_duration_days else 0
    else:
        out["actual_days"], out["days_exceeded_by"] = None, 0
    out["exceeds"] = bool(out["visits_exceeded_by"] or out["days_exceeded_by"])
    return out


def stream_for(doc_type: str) -> str:
    return DOC_TYPE_STREAM.get(doc_type, "legal_admin")
