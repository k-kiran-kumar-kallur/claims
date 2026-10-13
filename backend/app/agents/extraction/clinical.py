"""clinical_fact_extractor: mechanism, symptoms, diagnoses, imaging, procedures, response, causation, medications."""
from __future__ import annotations

import re

from app.agents import heuristics as H
from app.agents.extraction.base import fact, run_extractor
from app.orchestration.context import AgentContext
from app.orchestration.decorators import agent_node

SKIP = {"Medical Bill", "Administrative/Fax Cover", "Legal/Correspondence", "Policy/Coverage Information"}


def _direction(text: str) -> str:
    t = text.lower()
    if re.search(r"plateau|unchanged|minimal (change|gains)|not met|remains", t):
        return "unchanged"
    if re.search(r"worse|worsening|progressive", t):
        return "worsened"
    if re.search(r"improv|resolved|tolerated .* well|as expected", t):
        return "improved"
    return "unchanged"


def rules_clinical(v: H.DocView) -> list[dict]:
    out: list[dict] = []
    if v.doc_type == "Pharmacy/Prescription Record":
        for row in H.table_rows(v):
            parts = [p.strip() for p in row.value.split("|")]
            if len(parts) < 8:
                continue
            med = H.medications_in(parts[1])
            value = {"name": med[0]["name"] if med else parts[1], "dose": med[0]["dose"] if med else None,
                     "route": "oral", "quantity": parts[2].replace("Qty", "").strip(), "frequency": parts[3],
                     "prescriber": parts[4].replace("Prescriber:", "").strip(), "rx_date": H.first_date(parts[5]),
                     "fill_date": H.first_date(parts[6]), "status": parts[-1].replace("Status:", "").strip(),
                     "is_opioid": bool(med and med[0]["is_opioid"])}
            out.append(fact("medication", f"{parts[1]} #{value['quantity']} filled {parts[6].replace('Filled', '').strip()}",
                            value, v, row, 0.95, value["fill_date"]))
        return out
    for lv in H.labeled_values(v, ["Mechanism of Injury", "Description of Accident"]):
        out.append(fact("mechanism", f"Mechanism: {lv.value[:120]}", {"description": lv.value}, v, lv, 0.94))
    for lv in H.labeled_values(v, ["Chief Complaint", "Symptoms", "Subjective", "Patient-Reported Symptoms"]):
        pain = re.search(r"(\d{1,2})/10", lv.value)
        out.append(fact("symptom", f"Symptoms: {lv.value[:120]}", {"description": lv.value,
                                                                    "severity_0_10": int(pain.group(1)) if pain else None}, v, lv, 0.92))
    for lv in H.labeled_values(v, ["Physical Exam", "Physical Examination", "Objective", "Physical Measurements", "Incision"]):
        out.append(fact("exam_finding", f"Exam: {lv.value[:120]}", {"description": lv.value, "objective": True}, v, lv, 0.92))
    for lv in H.labeled_values(v, ["Diagnosis", "Assessment", "Postoperative Diagnosis", "Preoperative Diagnosis"]):
        codes = H.icd_codes(lv.value)
        for code in codes:
            seg = next((s for s in re.split(r";|\.\s", lv.value) if code in s), lv.value)
            desc = re.sub(r"\(\s*" + re.escape(code) + r"\s*\)", "", seg).strip(" .;:")
            out.append(fact("diagnosis", f"Diagnosis: {desc[:100]} ({code})", {"description": desc, "icd10": code}, v, lv, 0.93))
    for lv in H.labeled_values(v, ["Diagnostic Testing", "Imaging", "Imaging/Diagnostics"]):
        mod = re.search(r"\b(MRI|X-ray|X-rays|CT|EMG|functional capacity evaluation)\b", lv.value, re.I)
        if mod:
            out.append(fact("imaging", f"{mod.group(1)}: {lv.value[:120]}", {"modality": mod.group(1), "date": H.first_date(lv.value) or v.service_date,
                                                                            "findings": lv.value}, v, lv, 0.92, H.first_date(lv.value) or v.service_date))
    for lv in H.labeled_values(v, ["Procedure Performed", "Surgery Performed"]):
        cpt = re.search(r"CPT (\d{5})", lv.value)
        when = H.first_date(lv.value) or v.service_date
        if v.doc_type == "Operative Report" or lv.label.lower() == "procedure performed":
            out.append(fact("procedure", f"Procedure: {lv.value[:120]}", {"description": lv.value, "cpt": cpt.group(1) if cpt else None,
                                                                         "date": when}, v, lv, 0.95, when))
    for lv in H.labeled_values(v, ["Response", "Progress Toward Goals", "Pain Response"]):
        out.append(fact("response", f"Response: {lv.value[:120]}", {"description": lv.value, "direction": _direction(lv.value)}, v, lv, 0.9))
    if v.doc_type in ("Post-Op Follow-Up Note", "Orthopedic/Specialist Consultation"):
        for lv in H.labeled_values(v, ["Assessment"]):
            if not H.icd_codes(lv.value):
                out.append(fact("response", f"Assessment: {lv.value[:120]}", {"description": lv.value, "direction": _direction(lv.value)}, v, lv, 0.88))
    for lv in H.labeled_values(v, ["Causation", "Workers' Compensation"]):
        out.append(fact("causation", f"Causation: {lv.value[:120]}", {"opinion": lv.value, "provider": v.provider}, v, lv, 0.9))
    for lv in H.labeled_values(v, ["Recommendations", "RTW Recommendations"]):
        out.append(fact("recommendation", f"Recommendation: {lv.value[:120]}", {"description": lv.value}, v, lv, 0.9))
    return out


@agent_node("clinical_fact_extractor", "extraction")
def clinical_fact_extractor(state: dict, ctx: AgentContext) -> dict:
    return run_extractor(ctx, state, "clinical_fact_extractor", "extract_clinical",
                         {"mechanism", "symptom", "exam_finding", "diagnosis", "imaging", "procedure", "treatment", "response",
                          "recommendation", "causation", "medication"},
                         lambda v: v.doc_type not in SKIP, rules_clinical)
