"""Versioned prompt templates (spec §7, §17.3).

Defaults live here (v1).  Admins can publish new versions into `prompt_templates`; the active DB version wins.
Templates are Jinja2; every prompt places document text inside <document> blocks (prompt-injection defence §15.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from jinja2 import Environment, StrictUndefined
from sqlalchemy import select
from sqlalchemy.orm import Session

_env = Environment(undefined=StrictUndefined, autoescape=False)


@dataclass
class Prompt:
    name: str
    version: str
    system: str
    template: str
    tier: str = "fast"
    temperature: float = 0.0

    def render(self, **kwargs) -> str:
        return _env.from_string(self.template).render(**kwargs)


DEFAULTS: dict[str, Prompt] = {p.name: p for p in [
    Prompt("baseline_extraction", "1",
           "You extract the claim baseline for a workers' compensation file from the FROI, the employer's accident "
           "report and the initial medical documentation (PW-1.1: 100% accuracy on baseline data). For every field give "
           "the value exactly as documented, a confidence 0..1 and one citation. If sources disagree, use the FROI "
           "for employer data and lower the confidence. Also list urgent items needing immediate attention (surgery "
           "scheduled within 7 days, pending utilization-review deadlines, TTD without a recent work-status slip, "
           "opioid escalation, red-flag symptoms such as cauda equina signs).",
           "Claim metadata entered by the user:\n{{ metadata }}\n\nSource documents:\n<document>\n{{ documents }}\n</document>"),
    Prompt("review_context", "1",
           "You draft the review context for a WC medical-record review (PW-1.3): a precise, narrowly defined clinical "
           "question the review must answer, review goals, the evidence required and the applicable guidelines and "
           "state rules. Be specific to this claim (diagnosis, procedure, pending requests, jurisdiction).",
           "Claim baseline:\n{{ baseline }}\n\nDocument inventory:\n{{ inventory }}\n\nPending treatment / utilization "
           "requests:\n{{ requests }}\n\nAvailable guideline sources: {{ guidelines }}", tier="reasoning", temperature=0.2),
    Prompt("episode_summary", "1",
           "Summarize one episode of care for a Nurse Case Manager. Cover symptoms, diagnoses, tests, treatments, the "
           "patient's response, daily functioning and work limitations. Every sentence must cite the supporting lines "
           "and state whether the evidence is objective (exam, imaging, testing, FCE) or subjective (patient report).",
           "Episode: {{ episode }}\n<document>\n{{ documents }}\n</document>", tier="reasoning", temperature=0.2),
    Prompt("clinical_summary", "1",
           "Write the longitudinal clinical summary (PW-3.1, POC-3) from the episode summaries. The executive summary must "
           "be at most 250 words and highlight key narrative changes (improved, worsened, plateaued) with dates. State "
           "functional and work limitations explicitly. Keep the citations of the episode summaries; do not add facts "
           "that are not in them.",
           "Claim: {{ claim }}\nReview question: {{ question }}\n\nEpisode summaries (with citations):\n{{ episodes }}",
           tier="reasoning", temperature=0.2),
    Prompt("utilization_assessment", "1",
           "Draft a utilization/clinical assessment (PW-3.2, PW-3.3). For each provider request (MRI, ESI, PT extension, "
           "surgery, medication) assess medical-necessity indicators (each citing clinical evidence AND a guideline rule "
           "code from the supplied rules), appropriateness, progression of care, barriers to recovery (psychosocial, "
           "comorbidities, non-compliance, delays) and unresolved questions. Then list clinical issues: inconsistencies "
           "(e.g. pain scores vs function), conflicting diagnoses, unexplained treatment changes and missing evidence, "
           "each with severity and a targeted fact-finding action. This is an AI DRAFT - never a determination.",
           "Claim: {{ claim }}\nClinical summary:\n{{ summary }}\n\nRequests:\n{{ requests }}\n\nGuideline rules:\n"
           "{{ rules }}\n\n<document>\n{{ documents }}\n</document>", tier="reasoning", temperature=0.1),
    Prompt("extract_mmi", "1",
           "Extract Maximum Medical Improvement information: fact_type 'mmi' with value {status: reached|not_reached|"
           "anticipated, date, anticipated_date, declaring_provider, body_part} and fact_type 'impairment_rating' with "
           "value {percent_whole_person, guide_edition, body_part, provider} when present. Note conflicting opinions.",
           "<document>\n{{ documents }}\n</document>"),
    Prompt("extract_rtw", "1",
           "Extract return-to-work data: fact_type 'work_status' with value {work_status: full_duty|modified_duty|ttd|tpd|"
           "off_work, restrictions: [{type, limit_lb?, frequency?, max_hours_per_day?, limit?}], duration, "
           "next_reevaluation, employer_accommodation}; fact_type 'rtw' for FCE work-capacity classification with value "
           "{capacity: sedentary|light|medium|heavy, meets_job_demands: bool, job_demand_level}; fact_type 'restriction' "
           "for each explicit restriction. Units: lb, minutes, hours.",
           "<document>\n{{ documents }}\n</document>"),
    Prompt("extract_treatment_plan", "1",
           "Extract planned treatments: fact_type 'treatment_plan' with value {category: therapy|medication|injection|"
           "surgery|dme|referral|diagnostic|work_hardening, description, frequency, duration, visits, ordering_provider, "
           "status: requested|approved|completed|discontinued|on_hold}. One fact per planned item.",
           "<document>\n{{ documents }}\n</document>"),
    Prompt("extract_clinical", "1",
           "Extract clinical facts. fact_type one of: mechanism, symptom (value {description, severity_0_10}), exam_finding "
           "(objective examination findings, value {description}), diagnosis "
           "(value {description, icd10}), imaging (value {modality, date, findings}), procedure (value {description, "
           "cpt, date}), treatment, response (value {description, direction: improved|worsened|unchanged}), "
           "recommendation, causation (value {opinion, provider}), medication (value {name, dose, route, quantity, "
           "frequency, prescriber, fill_date, status}). Focus on functional outcomes: how the patient responded and the "
           "resulting restrictions.",
           "<document>\n{{ documents }}\n</document>"),
    Prompt("extract_ime", "1",
           "Extract Independent Medical Examination opinions: causation, impairment rating, MMI opinion, work capacity "
           "and treatment recommendations. Use fact types causation, impairment_rating, mmi, work_status, recommendation.",
           "<document>\n{{ documents }}\n</document>"),
    Prompt("fact_judge", "1",
           "For each item decide whether the quoted source text supports the extracted value: 'yes' (fully supported), "
           "'partial' (partly supported or needs inference) or 'no' (not supported). Zero extrapolation is allowed.",
           "Items:\n{{ items }}"),
    Prompt("turning_points", "1",
           "Identify the true turning points (PW-4.3): validated events that shifted diagnosis, plan, outlook, "
           "functioning or work capacity. For each give before/after state and impacted dimensions. Use only the facts "
           "supplied and reference them by key.",
           "Validated facts (chronological):\n{{ facts }}", tier="reasoning", temperature=0.1),
    Prompt("milestone_impacts", "1",
           "For each clinically significant milestone explain the cause -> effect on the claim (diagnosis, treatment, "
           "prognosis, function, work status) and link it directly to work capacity (PW-5.2). One or two sentences each.",
           "Milestones:\n{{ milestones }}\n\nWork-status history:\n{{ rtw }}", tier="reasoning", temperature=0.2),
    Prompt("guideline_assessment", "1",
           "Assess whether the treatment/request meets the criteria of the supplied guideline rule ONLY (never rely on "
           "memory of ODG/ACOEM). List missing prerequisites and explain briefly.",
           "Rule {{ rule_code }}: {{ rule_text }}\nPrerequisites: {{ prerequisites }}\n\nTreatment/request: {{ request }}\n\n"
           "Relevant validated facts:\n{{ facts }}", tier="reasoning"),
    Prompt("chronology_descriptions", "1",
           "Write a concise (max 30 words) factual description and key findings for each chronology event, using only "
           "the supplied facts. No opinions.",
           "Events:\n{{ events }}"),
    Prompt("report_narrative", "1",
           "Write the clinical narrative for a claim file review: injury -> diagnosis -> treatment -> response -> function "
           "-> current status (PW-6.2). Defensible clarity: no unverified assumptions or bias; filter administrative and "
           "clinical noise; focus on milestones that drive approval, cost exposure and occupational recovery. Cite the "
           "supplied citation markers for every sentence. Then list recommended next actions.",
           "Review question: {{ question }}\n{% if instructions %}Reviewer instructions for this revision: {{ instructions }}\n{% endif %}"
           "\nCase facts (validated, with citation markers):\n{{ facts }}\n\nGuideline findings:\n{{ findings }}",
           tier="reasoning", temperature=0.3),
    Prompt("decision_draft", "1",
           "Draft (do not decide) a recommendation for the Claims Examiner on treatment, disability status and claim "
           "trajectory, grounded only in the supplied evidence, guideline findings and work status. List outstanding "
           "questions and next steps with owners where possible.",
           "Claim: {{ claim }}\nReview question: {{ question }}\nFlags:\n{{ flags }}\n\nSummary:\n{{ summary }}",
           tier="reasoning", temperature=0.2),
    Prompt("routing_rationale", "1",
           "Explain in 2-3 sentences why this claim was scored with the given risk and complexity, citing the factors.",
           "Risk score: {{ score }}\nComplexity: {{ complexity }}\nFactors:\n{{ factors }}"),
]}


def get_prompt(db: Session | None, name: str) -> Prompt:
    default = DEFAULTS[name]
    if db is None:
        return default
    from app.models import PromptTemplate

    row = db.execute(select(PromptTemplate).where(PromptTemplate.name == name, PromptTemplate.is_active.is_(True))
                     .order_by(PromptTemplate.created_at.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return default
    return Prompt(name, row.version, row.system or default.system, row.template, row.model_tier, row.temperature)
