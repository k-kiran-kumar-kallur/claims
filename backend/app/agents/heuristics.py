"""Deterministic clinical-text heuristics.

Used by the deterministic tools (date normalisation, code lookup, gap detection, duration calculation) and as the
offline fallback for every LLM step (`LLM_PROVIDER=rules`, or when Gemini is unavailable).  Results produced
here always carry exact page/line citations so the grounding rules still hold.
"""
from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from datetime import date

from app.agents.taxonomy import CLASSIFY_RULES

DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/((?:19|20)\d{2})\b")
MONTH_YEAR_RE = re.compile(r"\b(0?[1-9]|1[0-2])/((?:19|20)\d{2})\b")
ICD_RE = re.compile(r"\b([A-TV-Z]\d{2}(?:\.[0-9A-Z]{1,4}))\b")
CPT_RE = re.compile(r"(?:CPT|HCPCS)?\s*\b(\d{5}|[A-V]\d{4})\b")
PAIN_RE = re.compile(r"\b(?:pain|pain level)[^.\d]{0,40}?(\d{1,2})/10", re.I)
PAGE_OF_LINE = re.compile(r"^\s*Page \d+ of \d+\s*$", re.I)
LABEL_RE = re.compile(r"^([A-Z][A-Za-z0-9 /'()&.-]{2,60}?):\s*(.*)$")
BODY_PARTS = {
    "lumbar spine": [r"lumbar", r"low back", r"lower back", r"L\d-[LS]\d"], "cervical spine": [r"cervical", r"neck"],
    "thoracic spine": [r"thoracic"], "shoulder": [r"shoulder", r"rotator cuff"], "knee": [r"\bknee", r"menisc"],
    "hip": [r"\bhip\b"], "wrist/hand": [r"wrist", r"\bhand\b", r"carpal"], "ankle/foot": [r"ankle"],
    "elbow": [r"elbow"], "head": [r"concussion", r"\bhead injury"],
}


@dataclass
class Line:
    page: int
    line: int
    text: str


@dataclass
class DocView:
    """A logical document as seen by agents: ordered lines with page/line coordinates."""
    id: str
    alias: str
    title: str
    doc_type: str | None
    lines: list[Line]
    service_date: str | None = None
    provider: str | None = None
    facility: str | None = None
    page_ids: dict[int, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    def marked(self, max_chars: int = 60000) -> str:
        """Text with citation markers <<D{alias}|P{page}|L{line}>> (spec §10.3)."""
        out, size = [], 0
        for ln in self.lines:
            s = f"<<{self.alias}|P{ln.page}|L{ln.line}>> {ln.text}"
            size += len(s) + 1
            if size > max_chars:
                out.append("[... truncated ...]")
                break
            out.append(s)
        return "\n".join(out)


# ---- dates ------------------------------------------------------------------------------------

def to_iso(m: re.Match) -> str | None:
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> list[str]:
    return [d for d in (to_iso(m) for m in DATE_RE.finditer(text)) if d]


def first_date(text: str) -> str | None:
    d = find_dates(text)
    return d[0] if d else None


def normalize_date(value: str | None, reference: str | None = None) -> str | None:
    """Normalise a date string to ISO-8601; resolves 'POD 14' / 'postoperative day 14' against `reference`."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    m = DATE_RE.search(value)
    if m:
        return to_iso(m)
    pod = re.search(r"(?:POD|post-?operative day)\s*#?\s*(\d+)", value, re.I)
    if pod and reference:
        from datetime import timedelta
        return (date.fromisoformat(reference) + timedelta(days=int(pod.group(1)))).isoformat()
    my = MONTH_YEAR_RE.search(value)
    if my:
        return f"{my.group(2)}-{int(my.group(1)):02d}-01"
    try:
        import dateparser

        parsed = dateparser.parse(value, settings={"PREFER_DAY_OF_MONTH": "first", "RETURN_AS_TIMEZONE_AWARE": False})
        return parsed.date().isoformat() if parsed else None
    except Exception:
        return None


LABELED_DATE_KEYS = ["Date of Service", "Visit Date", "Date of Surgery", "Evaluation Date", "Date of Visit",
                     "Request Date", "Date/Time of Arrival", "Incident Date", "Date of Injury", "Date Prepared", "Date"]


def service_dates(doc: DocView) -> tuple[str | None, str | None]:
    for key in LABELED_DATE_KEYS:
        for ln in doc.lines[:40]:
            if re.search(rf"\b{re.escape(key)}\s*:", ln.text, re.I):
                d = first_date(ln.text[ln.text.lower().find(key.lower()):])
                if d:
                    if doc.doc_type in ("Medical Bill", "Pharmacy/Prescription Record"):
                        break
                    return d, d
    dates = sorted(set(find_dates(doc.text)))
    if doc.doc_type in ("Medical Bill", "Pharmacy/Prescription Record") and dates:
        # rows of service / fill dates; ignore DOB-like dates far in the past
        dates = [d for d in dates if d >= "2000-01-01" and not _is_dob(doc, d)]
        return (dates[0], dates[-1]) if dates else (None, None)
    dates = [d for d in dates if not _is_dob(doc, d)]
    return (dates[0], dates[0]) if dates else (None, None)


def _is_dob(doc: DocView, iso: str) -> bool:
    y, m, d = iso.split("-")
    needle = f"{int(m):02d}/{int(d):02d}/{y}"
    return any("DOB" in ln.text and needle in ln.text for ln in doc.lines)


# ---- labelled sections ---------------------------------------------------------------------------

@dataclass
class Labeled:
    label: str
    value: str
    page: int
    line_start: int
    line_end: int
    quote: str


def labeled_values(doc: DocView, labels: list[str], continuation: bool = True) -> list[Labeled]:
    """Find 'Label: value' occurrences (value may continue on following non-label lines)."""
    out: list[Labeled] = []
    pattern = re.compile(r"(?:^|\s|\|\s*)(" + "|".join(re.escape(lb) for lb in labels) + r")\s*:\s*(.*)", re.I)
    lines = doc.lines
    for i, ln in enumerate(lines):
        m = pattern.search(ln.text)
        if not m:
            continue
        value = m.group(2).strip()
        # cut at an inline second label ("Provider: X    Surgeon: Y")
        # cut at an inline second label ("Date of Service: x    Provider: y"; PDF extraction may collapse the spacing)
        value = re.split(r"\s+(?=(?:Provider|Surgeon|Assistant|Therapist|Evaluator|Visit|MRN|Time|Place|Occupation|Date of Hire|Location|"
                         r"Requesting Provider|Referring Provider|Ordering Provider|Lost Time|Insurance|Supervisor|Specimens|Estimated Blood Loss|"
                         r"Implants|Assigned Adjuster|Response Requested By|DOB|Claim #):)", value)[0].strip()
        end = i
        if continuation:
            j = i + 1
            while j < len(lines) and lines[j].page == ln.page and not LABEL_RE.match(lines[j].text) \
                    and not PAGE_OF_LINE.match(lines[j].text) and len(value) < 600:
                value += " " + lines[j].text.strip()
                end = j
                j += 1
        out.append(Labeled(m.group(1), value.strip(), ln.page, ln.line, lines[end].line,
                           " ".join(x.text for x in lines[i:end + 1])))
    return out


def first_labeled(doc: DocView, labels: list[str]) -> Labeled | None:
    vals = labeled_values(doc, labels)
    return vals[0] if vals else None


def find_line(doc: DocView, pattern: str, flags: int = re.I) -> Line | None:
    rx = re.compile(pattern, flags)
    for ln in doc.lines:
        if rx.search(ln.text):
            return ln
    return None


def citation_for(doc: DocView, item: Labeled | Line) -> dict:
    if isinstance(item, Labeled):
        return {"document_id": doc.id, "page_number": item.page, "line_start": item.line_start,
                "line_end": item.line_end, "quote": item.quote[:500]}
    return {"document_id": doc.id, "page_number": item.page, "line_start": item.line, "line_end": item.line,
            "quote": item.text[:500]}


# ---- classification -----------------------------------------------------------------------------

def classify(doc: DocView) -> tuple[str, float, str]:
    head = " ".join(ln.text for ln in doc.lines[:6]).upper()
    body = doc.text.lower()
    if not body.strip():
        return "Other", 0.3, "No readable text (blank or unreadable page)"
    if doc.lines and doc.lines[0].text.startswith("From:") and any(ln.text.startswith("Subject:") for ln in doc.lines[:6]):
        return "Legal/Correspondence", 0.9, "Email header (From/Subject)"
    for doc_type, titles, kws in CLASSIFY_RULES:
        for t in titles:
            if t in head:
                hits = sum(1 for k in kws if k in body)
                conf = 0.92 if (hits or not kws) else 0.88
                return doc_type, conf, f"Header contains '{t}'" + (f"; {hits} supporting phrase(s)" if hits else "")
    for doc_type, _titles, kws in CLASSIFY_RULES:
        hits = [k for k in kws if k in body]
        if len(hits) >= 2:
            return doc_type, 0.72, f"Body phrases: {', '.join(hits)}"
    return "Other", 0.45, "No distinctive header or contextual phrases found"


def provider_info(doc: DocView) -> tuple[str | None, str | None, str | None]:
    facility = None
    first = doc.lines[0].text if doc.lines else ""
    if "|" in first:
        facility = first.split("|")[0].strip().title().replace("Pt &", "PT &").replace(" - ", " - ")
    for label in ("Provider", "Surgeon", "Therapist", "Evaluator", "Billing Provider", "Prescriber", "Completed by"):
        lv = first_labeled(doc, [label])
        if lv:
            name = re.split(r"\s{2,}|\s\|", lv.value)[0]
            parts = [p.strip() for p in name.split(" - ")]
            spec = parts[1] if len(parts) > 1 else None
            return parts[0].rstrip(".,"), spec, facility
    return None, None, facility


def body_parts(text: str) -> list[str]:
    found = []
    for part, pats in BODY_PARTS.items():
        if any(re.search(p, text, re.I) for p in pats):
            found.append(part)
    return found


def icd_codes(text: str) -> list[str]:
    return sorted(set(ICD_RE.findall(text)))


def cpt_candidates(text: str) -> list[str]:
    cands = set(re.findall(r"CPT\s*(?:code)?\s*:?\s*(\d{5})", text, re.I))
    cands |= set(re.findall(r"\|\s*(\d{5})\b", text))
    cands |= set(re.findall(r"\b(\d{5})\s+(?:MRI|CT|X-ray)", text))
    cands |= set(re.findall(r"\(CPT (\d{5})\)", text))
    cands |= set(re.findall(r"CPT \d{5} and (\d{5})", text))
    return sorted(cands)


# ---- clinical parsing ----------------------------------------------------------------------------

def work_status_of(text: str) -> str | None:
    t = text.lower()
    if re.search(r"temporary total|\bttd\b|off work|remain off", t):
        return "ttd"
    if re.search(r"temporary partial|\btpd\b", t):
        return "tpd"
    if re.search(r"modified duty|light duty|restricted duty|transitional duty", t):
        return "modified_duty"
    if re.search(r"full duty|regular duty|no restrictions|unrestricted", t):
        return "full_duty"
    return None


def restrictions_of(text: str) -> list[dict]:
    out = []
    t = text.lower()
    for m in re.finditer(r"(?:no lifting (?:over|greater than|more than|>)\s*(\d+)\s*lb)|(?:lift(?:ing)?(?:/carry)?\s*(?:up to|maximum|max)?\s*(\d+)\s*lb\s*(occasionally|frequently)?)", t):
        lb = m.group(1) or m.group(2)
        out.append({"type": "lift", "limit_lb": int(lb), "frequency": m.group(3) or "max"})
    for m in re.finditer(r"(\d+)\s*lb\s*(occasionally|frequently)", t):
        if not any(r.get("limit_lb") == int(m.group(1)) and r.get("frequency") == m.group(2) for r in out):
            out.append({"type": "lift", "limit_lb": int(m.group(1)), "frequency": m.group(2)})
    m = re.search(r"maximum (\d+) hours per day|max(?:imum)? (\d+) hours|(\d+) hours per day", t)
    if m:
        out.append({"type": "hours", "max_hours_per_day": int(next(g for g in m.groups() if g))})
    if "repetitive bending" in t or "no bending" in t:
        out.append({"type": "bending", "limit": "no repetitive bending" if "repetitive" in t else "no bending"})
    m = re.search(r"alternate sitting and standing every (\d+) minutes", t)
    if m:
        out.append({"type": "sit_stand", "alternate_every_minutes": int(m.group(1))})
    if "twisting" in t:
        out.append({"type": "twisting", "limit": "no twisting"})
    return out


def pain_scores(doc: DocView) -> list[tuple[Line, int]]:
    out = []
    for ln in doc.lines:
        for m in PAIN_RE.finditer(ln.text):
            out.append((ln, int(m.group(1))))
    return out


def mmi_of(text: str) -> dict | None:
    t = text.lower()
    if "maximum medical improvement" not in t and not re.search(r"\bmmi\b", t):
        return None
    anticipated = None
    m = re.search(r"anticipate[sd]?\s+mmi[^.]*?(?:\((\d{1,2})/(\d{4})\)|(\d{1,2})/(\d{1,2})/(\d{4}))", t)
    if m:
        if m.group(1):
            anticipated = f"{m.group(2)}-{int(m.group(1)):02d}-01"
        else:
            anticipated = f"{m.group(5)}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"
    if re.search(r"not (yet )?reached (maximum medical improvement|mmi)|not at mmi", t):
        status = "anticipated" if anticipated else "not_reached"
    elif re.search(r"(has )?reached (maximum medical improvement|mmi)|at mmi", t):
        status = "reached"
    else:
        return None
    rating = re.search(r"(\d{1,2})\s*%\s*whole person", t)
    return {"status": status, "anticipated_date": anticipated,
            "impairment_rating_pct": int(rating.group(1)) if rating else None,
            "impairment_rating": "deferred until MMI" if "rating deferred" in t else None}


MED_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+HCl)?)\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g)\b")
OPIOIDS = {"oxycodone", "hydrocodone", "tramadol", "morphine", "hydromorphone", "codeine", "tapentadol", "fentanyl",
           "oxymorphone", "methadone"}


def medications_in(text: str) -> list[dict]:
    meds = []
    for m in MED_RE.finditer(text):
        name = m.group(1).replace(" HCl", "")
        if name.lower() in {"page", "lift", "carry", "push", "the"}:
            continue
        meds.append({"name": name, "dose": f"{m.group(2)} {m.group(3)}", "is_opioid": name.lower() in OPIOIDS})
    return meds


def frequency_plan(text: str) -> dict | None:
    m = re.search(r"(\d+)\s*(?:times|x)\s*(?:per|/|a)?\s*week\s*(?:for|x)\s*(\d+)\s*weeks", text, re.I)
    if not m:
        return None
    per_week, weeks = int(m.group(1)), int(m.group(2))
    visits = re.search(r"\((\d+)\s*visits\)", text)
    return {"per_week": per_week, "weeks": weeks, "visits": int(visits.group(1)) if visits else per_week * weeks}


# ---- similarity ---------------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    text = re.sub(r"Page \d+ of \d+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def simhash(text: str, bits: int = 64) -> int:
    tokens = normalize_text(text).split()
    shingles = [" ".join(tokens[i:i + 3]) for i in range(max(len(tokens) - 2, 1))]
    v = [0] * bits
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(bits) if v[i] > 0)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def local_embedding(text: str, dim: int = 256) -> list[float]:
    """Deterministic feature-hashing embedding used when Gemini embeddings are unavailable."""
    import math

    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for tok in tokens + [f"{a}_{b}" for a, b in itertools.pairwise(tokens)]:
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "big")
        vec[h % dim] += 1.0 if (h >> 31) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


NEGATED_FINDING = re.compile(r"\b(no|without|negative for|free of)\s+(acute\s+)?(fracture|listhesis|herniation|tear|compression|dislocation)", re.I)
POSITIVE_FINDING = re.compile(r"herniat|compress|\btear\b|fracture|stenosis|impingement|extrud", re.I)


def positive_finding(text: str) -> bool:
    """True when imaging text reports a structural abnormality (negated mentions such as 'no fracture' excluded)."""
    return bool(POSITIVE_FINDING.search(NEGATED_FINDING.sub(" ", text)))


def table_rows(doc: DocView, start: str = r"^Rx\s") -> list[Labeled]:
    """Logical table rows that may wrap across several printed lines (e.g. pharmacy histories)."""
    rx = re.compile(start)
    rows: list[Labeled] = []
    cur: Labeled | None = None
    for ln in doc.lines:
        if rx.search(ln.text):
            cur = Labeled("row", ln.text.strip(), ln.page, ln.line, ln.line, ln.text.strip())
            rows.append(cur)
        elif cur is not None and ln.page == cur.page and ln.text.strip() and not LABEL_RE.match(ln.text) \
                and not PAGE_OF_LINE.match(ln.text) and ln.line == cur.line_end + 1:
            cur.value += " " + ln.text.strip()
            cur.quote += " " + ln.text.strip()
            cur.line_end = ln.line
        else:
            cur = None
    return rows
