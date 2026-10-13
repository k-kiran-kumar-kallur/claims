"""mmi_extractor: MMI status/date/provider/impairment rating; IME opinions (spec §7.6)."""
from __future__ import annotations

import re

from app.agents import heuristics as H
from app.agents.extraction.base import fact, run_extractor
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node


def _has_mmi(v: H.DocView) -> bool:
    return bool(re.search(r"maximum medical improvement|\bMMI\b|impairment rating", v.text, re.I))


def rules_mmi(v: H.DocView) -> list[dict]:
    out = []
    for lv in H.labeled_values(v, ["MMI", "Maximum Medical Improvement", "Impairment Rating"]):
        parsed = H.mmi_of(lv.value if "mmi" in lv.value.lower() or "maximum" in lv.value.lower() else f"MMI {lv.value}")
        if parsed:
            label = {"reached": "MMI reached", "not_reached": "MMI not reached",
                     "anticipated": "MMI not yet reached - anticipated " + (f"{parsed['anticipated_date'][5:7]}/{parsed['anticipated_date'][:4]}" if parsed["anticipated_date"] else "date not given")}[parsed["status"]]
            value = {"status": parsed["status"], "date": v.service_date if parsed["status"] == "reached" else None,
                     "anticipated_date": parsed["anticipated_date"], "declaring_provider": v.provider,
                     "body_part": ", ".join(H.body_parts(v.text)[:1]) or None,
                     "impairment_rating": parsed["impairment_rating"]}
            out.append(fact("mmi", label, value, v, lv, 0.94))
            if parsed.get("impairment_rating_pct") is not None:
                out.append(fact("impairment_rating", f"Impairment rating {parsed['impairment_rating_pct']}% whole person",
                                {"percent_whole_person": parsed["impairment_rating_pct"], "provider": v.provider}, v, lv, 0.9))
    return out


@agent_node("mmi_extractor", "extraction")
def mmi_extractor(state: dict, ctx: AgentContext) -> dict:
    return run_extractor(ctx, state, "mmi_extractor", "extract_mmi", {"mmi", "impairment_rating"}, _has_mmi, rules_mmi)


def rules_ime(v: H.DocView) -> list[dict]:
    out = rules_mmi(v)
    for lv in H.labeled_values(v, ["Causation", "Opinion"]):
        out.append(fact("causation", f"IME causation opinion: {lv.value[:120]}", {"opinion": lv.value, "provider": v.provider}, v, lv, 0.88))
    return out


@agent_node("ime_extractor", "extraction")
def ime_extractor(state: dict, ctx: AgentContext) -> dict:
    """Optional sub-extractor selected by the supervisor when IME reports exist (spec §6.6 run_ime_analysis)."""
    return run_extractor(ctx, state, "ime_extractor", "extract_ime",
                         {"causation", "impairment_rating", "mmi", "work_status", "recommendation"},
                         lambda v: v.doc_type == "IME Report", rules_ime)
