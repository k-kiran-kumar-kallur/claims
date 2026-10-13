"""treatment_plan_extractor: planned treatments, ordering provider, status, dates (spec §7.6)."""
from __future__ import annotations

import re

from app.agents import heuristics as H
from app.agents.extraction.base import fact, run_extractor
from app.agents.taxonomy import NON_CLINICAL_TYPES
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node


def category_of(text: str) -> str:
    t = text.lower()
    for cat, pats in (("work_hardening", ["work hardening", "work conditioning"]), ("surgery", ["surgery", "discectomy", "fusion", "laminectomy"]),
                      ("injection", ["injection", "epidural"]), ("diagnostic", ["mri", "x-ray", "ct ", "emg", "functional capacity evaluation"]),
                      ("therapy", ["physical therapy", "therapy", " pt "]), ("medication", [" mg", "medication", "discontinue oxycodone"]),
                      ("referral", ["refer", "consult"]), ("dme", ["brace", "tens", "cane", "walker"])):
        if any(p in f" {t} " for p in pats):
            return cat
    return "other"


def status_of(text: str, doc_type: str | None) -> str:
    t = text.lower()
    if "discontinue" in t:
        return "discontinued"
    if "on hold" in t:
        return "on_hold"
    if doc_type == "Utilization Review Request/Decision" or "recommend" in t or "request" in t:
        return "requested"
    if "scheduled" in t or "start" in t or "continue" in t or "refilled" in t:
        return "approved"
    return "requested"


def _relevant(v: H.DocView) -> bool:
    return v.doc_type not in NON_CLINICAL_TYPES or v.doc_type == "Utilization Review Request/Decision"


def rules_treatment_plan(v: H.DocView) -> list[dict]:
    out = []
    for lv in H.labeled_values(v, ["Plan", "PT/Rehab", "Postoperative Plan", "Recommendations", "Requested Treatment",
                                   "Medications", "Medications Prescribed"]):
        for sentence in [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", lv.value) if len(s.strip()) > 8]:
            cat = category_of(sentence)
            if cat == "other" and lv.label.lower() not in ("plan", "recommendations"):
                continue
            fp = H.frequency_plan(sentence)
            out.append(fact("treatment_plan", f"{cat.replace('_', ' ').title()}: {sentence[:140]}", {
                "category": cat, "description": sentence, "frequency": f"{fp['per_week']}x/week" if fp else None,
                "duration": f"{fp['weeks']} weeks" if fp else None, "visits": fp["visits"] if fp else None,
                "ordering_provider": v.provider, "status": status_of(sentence, v.doc_type)}, v, lv, 0.9))
    return out


@agent_node("treatment_plan_extractor", "extraction")
def treatment_plan_extractor(state: dict, ctx: AgentContext) -> dict:
    return run_extractor(ctx, state, "treatment_plan_extractor", "extract_treatment_plan", {"treatment_plan"},
                         _relevant, rules_treatment_plan)
