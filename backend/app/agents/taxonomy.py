"""Document taxonomy, streams and labels (spec §7.1, §7.2)."""
from __future__ import annotations

DOC_TYPES = [
    "ED Visit Record", "Orthopedic/Specialist Consultation", "Operative Report", "IME Report",
    "Physical Therapy Progress Note", "Rehab Note", "Chiropractic Note", "Pain Management Note", "Primary Care Note",
    "Post-Op Follow-Up Note", "Treatment Plan", "Imaging Report", "Lab Report", "Pharmacy/Prescription Record",
    "FCE Report", "Work Status Slip", "Utilization Review Request/Decision", "Medical Bill",
    "Employer's First Report of Injury (FROI)", "Employer Accident Report", "Policy/Coverage Information",
    "Legal/Correspondence", "Administrative/Fax Cover", "Other",
]

STREAMS = ["clinical_provider_notes", "rehab_notes", "billing", "legal_admin", "pharmacy", "employer_reports"]

DOC_TYPE_STREAM = {
    "ED Visit Record": "clinical_provider_notes", "Orthopedic/Specialist Consultation": "clinical_provider_notes",
    "Operative Report": "clinical_provider_notes", "IME Report": "clinical_provider_notes",
    "Physical Therapy Progress Note": "rehab_notes", "Rehab Note": "rehab_notes", "Chiropractic Note": "rehab_notes",
    "Pain Management Note": "clinical_provider_notes", "Primary Care Note": "clinical_provider_notes",
    "Post-Op Follow-Up Note": "clinical_provider_notes", "Treatment Plan": "clinical_provider_notes",
    "Imaging Report": "clinical_provider_notes", "Lab Report": "clinical_provider_notes",
    "Pharmacy/Prescription Record": "pharmacy", "FCE Report": "rehab_notes",
    "Work Status Slip": "clinical_provider_notes", "Utilization Review Request/Decision": "legal_admin",
    "Medical Bill": "billing", "Employer's First Report of Injury (FROI)": "employer_reports",
    "Employer Accident Report": "employer_reports", "Policy/Coverage Information": "legal_admin",
    "Legal/Correspondence": "legal_admin", "Administrative/Fax Cover": "legal_admin", "Other": "legal_admin",
}

NOISE_TYPES = {"Administrative/Fax Cover"}
NON_CLINICAL_TYPES = {"Medical Bill", "Administrative/Fax Cover", "Policy/Coverage Information", "Legal/Correspondence",
                      "Employer's First Report of Injury (FROI)", "Employer Accident Report"}

# ordered title / keyword rules for the deterministic classifier: (doc_type, title patterns, body patterns)
CLASSIFY_RULES: list[tuple[str, list[str], list[str]]] = [
    ("Administrative/Fax Cover", ["FAX COVER", "FACSIMILE COVER"], ["confidentiality notice", "number of pages"]),
    ("Medical Bill", ["CMS-1500", "HEALTH INSURANCE CLAIM FORM", "UB-04", "ITEMIZED BILL"], ["charges", "place of service"]),
    ("Employer's First Report of Injury (FROI)", ["FIRST REPORT OF INJURY", "FROI", "LIBC-344"], ["date reported to employer"]),
    ("Employer Accident Report", ["ACCIDENT / INCIDENT REPORT", "ACCIDENT REPORT", "INCIDENT REPORT"], ["corrective action"]),
    ("IME Report", ["INDEPENDENT MEDICAL EXAM", "INDEPENDENT MEDICAL EVALUATION", "IME REPORT"], ["independent medical"]),
    ("Operative Report", ["OPERATIVE REPORT", "OPERATION REPORT", "PROCEDURE NOTE"], ["estimated blood loss", "preoperative diagnosis"]),
    ("FCE Report", ["FUNCTIONAL CAPACITY EVALUATION", "FCE REPORT"], ["physical demand level", "consistency of effort"]),
    ("Utilization Review Request/Decision", ["UTILIZATION REVIEW", "REQUEST FOR AUTHORIZATION", "UR DETERMINATION"], ["requested treatment"]),
    ("Work Status Slip", ["WORK STATUS SLIP", "WORK STATUS REPORT", "RETURN TO WORK SLIP"], []),
    ("Pharmacy/Prescription Record", ["PHARMACY", "PRESCRIPTION HISTORY", "PRESCRIPTION RECORD"], ["refills", "dispensed"]),
    ("ED Visit Record", ["EMERGENCY DEPARTMENT", "EMERGENCY ROOM", "ED VISIT"], ["chief complaint", "discharge instructions"]),
    ("Post-Op Follow-Up Note", ["POST-OPERATIVE", "POSTOPERATIVE", "POST-OP"], ["incision"]),
    ("Physical Therapy Progress Note", ["PHYSICAL THERAPY", "PT PROGRESS", "THERAPY PROGRESS"], ["therapeutic exercise", "oswestry"]),
    ("Chiropractic Note", ["CHIROPRACTIC"], ["adjustment", "subluxation"]),
    ("Pain Management Note", ["PAIN MANAGEMENT", "PAIN MEDICINE"], ["epidural", "facet"]),
    ("Imaging Report", ["RADIOLOGY REPORT", "MRI REPORT", "CT REPORT", "X-RAY REPORT", "IMAGING REPORT"], ["impression:", "technique:"]),
    ("Lab Report", ["LABORATORY REPORT", "LAB RESULTS"], ["reference range"]),
    ("Treatment Plan", ["TREATMENT PLAN", "PLAN OF CARE"], []),
    ("Rehab Note", ["REHABILITATION NOTE", "REHAB NOTE", "WORK HARDENING", "OCCUPATIONAL THERAPY"], []),
    ("Primary Care Note", ["PRIMARY CARE", "FAMILY MEDICINE", "INTERNAL MEDICINE"], []),
    ("Orthopedic/Specialist Consultation", ["CONSULTATION", "ORTHOPEDIC", "NEUROLOGY", "SPECIALIST", "FOLLOW-UP VISIT"], ["assessment", "plan"]),
    ("Policy/Coverage Information", ["POLICY DECLARATIONS", "COVERAGE INFORMATION", "CERTIFICATE OF INSURANCE"], []),
    ("Legal/Correspondence", ["SUBJECT:", "RE:", "DEAR "], ["regards", "sincerely"]),
]

EPISODE_TYPES = {
    "ED Visit Record": "emergency", "Orthopedic/Specialist Consultation": "specialist", "Operative Report": "surgery",
    "Post-Op Follow-Up Note": "surgery", "Physical Therapy Progress Note": "therapy", "Rehab Note": "therapy",
    "Chiropractic Note": "therapy", "FCE Report": "functional_evaluation", "IME Report": "ime",
    "Pain Management Note": "pain_management", "Primary Care Note": "primary_care", "Imaging Report": "diagnostics",
    "Lab Report": "diagnostics", "Work Status Slip": "specialist", "Treatment Plan": "specialist",
    "Utilization Review Request/Decision": "therapy",
}

EPISODE_LABELS = {
    "emergency": "Emergency care", "specialist": "Specialist evaluation", "surgery": "Surgical episode",
    "therapy": "Rehabilitation / therapy course", "functional_evaluation": "Functional capacity evaluation",
    "ime": "Independent medical examination", "pain_management": "Pain management", "primary_care": "Primary care",
    "diagnostics": "Diagnostics",
}

FACT_TYPES = ["mechanism", "symptom", "exam_finding", "diagnosis", "imaging", "procedure", "treatment", "response", "restriction",
              "work_status", "recommendation", "medication", "mmi", "rtw", "treatment_plan", "causation",
              "impairment_rating"]
MILESTONE_FACT_TYPES = {"mmi", "rtw", "procedure", "diagnosis", "impairment_rating", "work_status"}

# expected-document checklist rules (completeness check PW-1.2): (trigger regex, expected doc type, description)
EXPECTED_DOC_RULES = [
    (r"\b(surgery|microdiscectomy|laminectomy|arthroscopy|fusion|ORIF)\b", "Operative Report", "operative report"),
    (r"\bMRI\b", "Imaging Report", "MRI report"),
    (r"\b(CT scan|CT of)\b", "Imaging Report", "CT report"),
    (r"\b(functional capacity evaluation|FCE)\b", "FCE Report", "FCE report"),
    (r"\b(physical therapy|PT)\b", "Physical Therapy Progress Note", "physical therapy notes"),
    (r"\b(IME|independent medical)\b", "IME Report", "IME report"),
]
BASELINE_DOC_TYPES = ["Employer's First Report of Injury (FROI)", "ED Visit Record"]
