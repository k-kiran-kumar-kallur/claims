"""rtw_extractor: work status per date, restrictions, FCE work-capacity classification (spec §7.6)."""
from __future__ import annotations

import re

from app.agents import heuristics as H
from app.agents.extraction.base import fact, run_extractor
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node

WS_LABEL = {"ttd": "Temporary total disability (off work)", "tpd": "Temporary partial disability",
            "modified_duty": "Modified duty", "full_duty": "Full duty", "off_work": "Off work"}


def _relevant(v: H.DocView) -> bool:
    return v.doc_type not in ("Medical Bill", "Pharmacy/Prescription Record", "Administrative/Fax Cover") and bool(
        re.search(r"work status|restriction|light duty|modified duty|work capacity|off work", v.text, re.I))


def rules_rtw(v: H.DocView) -> list[dict]:
    out = []
    accommodation = H.first_labeled(v, ["Employer Accommodation"])
    for lv in H.labeled_values(v, ["Work Status"]):
        ws = H.work_status_of(lv.value)
        if not ws:
            continue
        eff = re.search(r"effective (\d{1,2}/\d{1,2}/\d{4})", lv.value, re.I)
        thru = re.search(r"through (\d{1,2}/\d{1,2}/\d{4})", lv.value, re.I)
        value = {"work_status": ws, "restrictions": H.restrictions_of(lv.value), "description": lv.value,
                 "duration": f"through {thru.group(1)}" if thru else None,
                 "employer_accommodation": accommodation.value if accommodation else None}
        out.append(fact("work_status", f"Work status: {WS_LABEL[ws]}", value, v, lv, 0.93,
                        H.normalize_date(eff.group(1)) if eff else v.service_date))
    for lv in H.labeled_values(v, ["Restrictions", "Activity Restrictions", "Functional Limitations/Restrictions"]):
        r = H.restrictions_of(lv.value)
        if r:
            out.append(fact("restriction", f"Restrictions: {lv.value[:120]}", {"restrictions": r, "description": lv.value}, v, lv, 0.92))
    cap = H.first_labeled(v, ["Work Capacity Classification"])
    if cap:
        level = next((w for w in ("sedentary", "light", "medium", "heavy") if w in cap.value.lower()), None)
        meets = H.first_labeled(v, ["Can the patient meet job demands"])
        job = H.first_labeled(v, ["Job Requirements"])
        out.append(fact("rtw", f"FCE work capacity: {level or cap.value}", {
            "capacity": level, "meets_job_demands": (not meets.value.lower().startswith("no")) if meets else None,
            "job_demand_level": next((w for w in ("sedentary", "light", "medium", "heavy") if job and w in job.value.lower()), None)},
            v, cap, 0.95))
    rec = H.first_labeled(v, ["RTW Recommendations"])
    if rec:
        out.append(fact("rtw", f"RTW recommendation: {rec.value[:120]}", {"recommendation": rec.value,
                                                                          "work_status": H.work_status_of(rec.value)}, v, rec, 0.9))
    return out


@agent_node("rtw_extractor", "extraction")
def rtw_extractor(state: dict, ctx: AgentContext) -> dict:
    return run_extractor(ctx, state, "rtw_extractor", "extract_rtw", {"work_status", "rtw", "restriction"}, _relevant, rules_rtw)
