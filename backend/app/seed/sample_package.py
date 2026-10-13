"""Synthetic WC sample package (spec Appendix A / golden dataset §17.1).

All people, organisations and identifiers below are fictitious.  The package reproduces the PoC sample claim
(Marcus T. Delgado, WC-2024-PA-087341, DOI 09/14/2024) at reduced size (~45 pages) and deliberately contains the
situations the workflow must handle:

* multi-document fax packets with fax cover sheets (packet splitting, stream routing, noise removal)
* the ED record faxed twice (exact duplicate) and a blank separator page
* an MRI that is referenced and billed but whose report is missing (gap + document request)
* employer conflict: claim header lists Meridian Risk Partners LLC, FROI lists Keystone Industrial Services (HITL-0)
* surgery, post-op course, PT with a pain plateau and an extension request (utilization review)
* long opioid course (guideline deviation), FCE showing light capacity vs. medium job (RTW restrictions)
* MMI "not yet reached" with an anticipated date; an email (.eml) with a work-status-slip attachment
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from fpdf import FPDF

CLAIM = {
    "claim_number": "WC-2024-PA-087341",
    "claimant": {"full_name": "Marcus T. Delgado", "dob": "1986-03-22", "ssn_last4": "4417",
                 "contact": "418 Penn Ave, Reading, PA 19601"},
    "employer_name": "Meridian Risk Partners LLC",  # as listed in the PoC header (conflicts with the FROI)
    "employer_contact": "Sarah Whitfield",
    "insurer": "PMA Companies",
    "tpa": "Lodestar Claims Management",
    "date_of_injury": "2024-09-14",
    "jurisdiction_state": "PA",
    "body_parts": ["lumbar spine"],
    "adjuster_name": "Jennifer Hartwell, AIC",
}

HDR_ED = "READING HOSPITAL - TOWER HEALTH | Emergency Department | 420 S 5th Ave, West Reading, PA"
HDR_ORTHO = "BERKS ORTHOPEDICS & SPORTS MEDICINE | 2605 Keiser Blvd, Wyomissing, PA"
HDR_PT = "HEALTHSTAR PT & REHABILITATION | 1100 Berkshire Blvd, Wyomissing, PA"
HDR_FCE = "ALLIED REHAB SERVICES | Functional Testing Center | Reading, PA"
PATIENT = "Patient: Marcus T. Delgado    DOB: 03/22/1986    Claim #: WC-2024-PA-087341"


def _doc(title: str, header: str, pages: list[list[str]]) -> list[list[str]]:
    out = []
    n = len(pages)
    for i, body in enumerate(pages, 1):
        out.append([header, title, PATIENT, ""] + body + ["", f"Page {i} of {n}"])
    return out


def _fax_cover(sender: str, to: str, date: str, pages: int, regarding: str) -> list[list[str]]:
    return [[
        "FAX COVER SHEET", "", f"Date: {date}", f"From: {sender}", f"To: {to}", f"Number of pages (including cover): {pages}",
        f"Re: {regarding}", "",
        "CONFIDENTIALITY NOTICE: This facsimile contains confidential health information that is legally",
        "privileged. If you are not the intended recipient, you are hereby notified that any disclosure,",
        "copying or distribution is strictly prohibited. Please notify the sender immediately.",
    ]]


ED_RECORD = _doc("EMERGENCY DEPARTMENT VISIT - MEDICAL RECORD", HDR_ED, [
    [
        "Date/Time of Arrival: 09/14/2024 14:42    MRN: RH-5530981",
        "Employer: Keystone Industrial Services    Insurance: Workers' Compensation - PMA Companies",
        "Date/Time of Injury: 09/14/2024 13:15    Place of Injury: Keystone warehouse, bay 4, Reading, PA",
        "Mechanism of Injury: Lifting an approximately 80 lb crate from floor level to a pallet; felt a pop in the low back.",
        "Chief Complaint: Low back pain radiating to the left leg.",
        "History of Present Illness: 38-year-old warehouse associate with immediate onset of low back pain 8/10",
        "radiating to the left buttock and lateral calf, with numbness of the left lateral calf. No prior back",
        "injuries. No prior treatment for this condition. Denies bowel or bladder dysfunction.",
        "Past Medical History: Hypertension (controlled). Tobacco use 1/2 pack per day.",
        "Allergies: No known drug allergies.",
    ],
    [
        "Physical Examination: Lumbar paraspinal tenderness L4-S1. Flexion limited to 30 degrees.",
        "Straight leg raise positive on the left at 40 degrees. EHL strength 4+/5 left, otherwise 5/5.",
        "Reflexes 2+ and symmetric. Sensation decreased over the left lateral calf. Gait antalgic.",
        "Diagnostic Testing: X-ray lumbar spine 3 views: no fracture or listhesis; mild disc space narrowing at L4-L5.",
        "Diagnosis: Strain of muscle and tendon of lower back (S39.012A); Sciatica, left side (M54.32).",
        "Treatment Provided: Ketorolac 30 mg IM given in the ED; ice applied.",
        "Medications Prescribed: Cyclobenzaprine 10 mg three times daily as needed x 10 days; Ibuprofen 800 mg three times daily x 10 days.",
    ],
    [
        "Discharge Instructions: Rest, ice and heat. Follow up with orthopedics within 1 week. Return immediately for",
        "bowel or bladder changes, progressive weakness or saddle numbness.",
        "Activity Restrictions: No lifting over 10 lb until cleared by orthopedics.",
        "Work Status: Off work 09/14/2024 through 09/17/2024, then re-evaluate with orthopedics.",
        "Workers' Compensation: Patient states the injury occurred while performing assigned job duties at Keystone",
        "Industrial Services. The presentation is consistent with the reported workplace lifting incident.",
        "Provider: Priya Natarajan, MD - Emergency Medicine",
        "Electronically signed: Priya Natarajan, MD 09/14/2024 18:05",
    ],
])

FROI = [[
    "EMPLOYER'S FIRST REPORT OF INJURY (FROI) - COMMONWEALTH OF PENNSYLVANIA (LIBC-344)",
    "Employer: Keystone Industrial Services, 1200 Riverfront Dr, Reading, PA 19602",
    "Employee: Marcus T. Delgado    Occupation: Warehouse Associate    Date of Hire: 06/03/2019",
    "Date of Injury: 09/14/2024    Time of Injury: 1:15 PM    Place: Warehouse bay 4",
    "Description of Accident: Employee was lifting a crate (approx. 80 lb) from the floor to a pallet and felt",
    "sudden pain in the low back radiating into the left leg.",
    "Mechanism: Lifting    Nature of Injury: Strain    Part of Body: Low back (lumbar spine)",
    "Witnesses: Tom Becker, shift lead",
    "Date Reported to Employer: 09/14/2024    Lost Time: Yes, beginning 09/15/2024",
    "", "Page 1 of 2",
], [
    "EMPLOYER'S FIRST REPORT OF INJURY (FROI) - continued",
    "Insurer: PMA Companies    Third Party Administrator: Lodestar Claims Management",
    "Claim Number: WC-2024-PA-087341    Assigned Adjuster: Jennifer Hartwell, AIC",
    "Job Physical Demands: Medium - lift up to 50 lb occasionally and 25 lb frequently.",
    "Treating Facility: Reading Hospital - Tower Health Emergency Department",
    "Report Prepared By: Sarah Whitfield, Meridian Risk Partners LLC (employer risk management representative)",
    "Date Prepared: 09/16/2024",
    "", "Page 2 of 2",
]]

EMPLOYER_REPORT = [[
    "KEYSTONE INDUSTRIAL SERVICES - EMPLOYER ACCIDENT / INCIDENT REPORT",
    "Incident Date: 09/14/2024    Time: 13:15    Location: Warehouse bay 4",
    "Employee: Marcus T. Delgado    Supervisor: Tom Becker",
    "Description: While lifting a crate from floor level the employee reported a sharp pain in the lower back.",
    "Employee was escorted to Reading Hospital Emergency Department by the shift lead.",
    "Safety Review: Crate weight exceeded the 50 lb single-person lift guideline; two-person lift required.",
    "Corrective Action: Retraining on team lifts scheduled.",
    "Completed by: Tom Becker, Shift Lead    Date: 09/14/2024",
    "", "Page 1 of 1",
]]

ORTHO_CONSULT = _doc("ORTHOPEDIC SURGERY CONSULTATION", HDR_ORTHO, [
    [
        "Date of Service: 09/26/2024    Provider: Alan Reyes, MD - Orthopedic Surgery",
        "Reason for Consultation: Low back pain with left leg radiculopathy after work injury on 09/14/2024.",
        "History of Injury: Injured at work on 09/14/2024 lifting an 80 lb crate at Keystone Industrial Services.",
        "Symptoms: Low back pain 7/10 radiating to the left buttock, posterior thigh and lateral calf; numbness of",
        "the dorsum of the left foot; pain worse with sitting.",
        "Prior Treatment: ED visit 09/14/2024 with cyclobenzaprine and ibuprofen. No physical therapy yet.",
        "Medical History: No prior lumbar injuries or surgery. Hypertension. Smoker 1/2 pack per day.",
    ],
    [
        "Physical Exam: Lumbar flexion 35 degrees with pain. Positive straight leg raise on the left at 35 degrees.",
        "Diminished sensation in the left L5 dermatome. EHL strength 4/5 on the left. Reflexes symmetric.",
        "Imaging: Lumbar X-rays from 09/14/2024 reviewed: no fracture.",
        "Assessment: Lumbar radiculopathy, left L5 distribution (M54.16); suspected L4-L5 disc herniation.",
        "Causation: Within a reasonable degree of medical certainty the condition was caused by the lifting incident",
        "at work on 09/14/2024.",
    ],
    [
        "Plan: MRI of the lumbar spine without contrast. Physical therapy 2 times per week for 6 weeks after MRI.",
        "Medications: Oxycodone 5 mg every 6 hours as needed for severe pain #28; Gabapentin 300 mg three times daily;",
        "continue ibuprofen 800 mg.",
        "Work Status: Temporary total disability (TTD) - off work pending MRI.",
        "Follow-up: 2 weeks after MRI.",
        "Signed: Alan Reyes, MD 09/26/2024",
    ],
])

ORTHO_FOLLOWUP = _doc("ORTHOPEDIC FOLLOW-UP VISIT", HDR_ORTHO, [
    [
        "Date of Service: 10/10/2024    Provider: Alan Reyes, MD - Orthopedic Surgery",
        "Interval History: MRI of the lumbar spine performed 10/02/2024 at Berks Imaging Center was reviewed.",
        "Symptoms: Pain 8/10, worsening numbness, new weakness of left foot dorsiflexion.",
        "Physical Exam: Left ankle dorsiflexion 4/5, EHL 4-/5. Positive straight leg raise on the left at 30 degrees.",
        "Imaging: MRI 10/02/2024 shows a large left paracentral disc herniation at L4-L5 compressing the traversing",
        "left L5 nerve root.",
    ],
    [
        "Assessment: Lumbar disc herniation with radiculopathy, L4-L5 (M51.16). Diagnosis updated from radiculopathy (M54.16).",
        "Plan: Recommend left L4-L5 microdiscectomy given progressive motor deficit. Surgery scheduled 10/22/2024 at",
        "Reading Hospital. Physical therapy on hold until after surgery.",
        "Medications: Oxycodone 5 mg every 6 hours as needed #40; continue gabapentin 300 mg three times daily.",
        "Work Status: Temporary total disability (TTD) continues.",
        "Signed: Alan Reyes, MD 10/10/2024",
    ],
])

OP_REPORT = _doc("OPERATIVE REPORT", "READING HOSPITAL - TOWER HEALTH | Department of Surgery | West Reading, PA", [
    [
        "Date of Surgery: 10/22/2024    Location: Reading Hospital - Tower Health, OR 6",
        "Preoperative Diagnosis: Left L4-L5 disc herniation with L5 radiculopathy (M51.16).",
        "Postoperative Diagnosis: Same.",
        "Procedure Performed: Left L4-L5 hemilaminotomy and microdiscectomy (CPT 63030).",
        "Surgeon: Alan Reyes, MD    Assistant: Dana Kim, PA-C",
        "Anesthesia: General endotracheal anesthesia.",
        "Indication for Surgery: Progressive left L5 motor deficit with concordant MRI findings despite conservative care.",
    ],
    [
        "Description of Procedure: The patient was positioned prone on a Wilson frame. A midline incision was made",
        "over L4-L5. A left hemilaminotomy was performed under microscopic visualization. The ligamentum flavum was",
        "removed and the left L5 nerve root was identified and gently retracted.",
        "Intraoperative Findings: Large extruded disc fragment compressing the left L5 nerve root. The root was fully",
        "decompressed after removal of the fragment.",
        "Implants: None.    Estimated Blood Loss: 25 mL.    Specimens: Disc fragments to pathology.",
        "Complications: None.",
    ],
    [
        "Condition: Stable, transferred to PACU in good condition.",
        "Postoperative Plan: Discharge home the same day. No lifting over 10 lb and no bending or twisting for 6 weeks.",
        "Follow up in 2 weeks. Begin physical therapy 2 weeks after surgery.",
        "Surgeon Signature: Alan Reyes, MD    Date: 10/22/2024",
    ],
])


def _postop(date: str, pages: list[list[str]]) -> list[list[str]]:
    return _doc("POST-OPERATIVE FOLLOW-UP NOTE", HDR_ORTHO, [[f"Date of Service: {date}    Provider: Alan Reyes, MD - Orthopedic Surgery"] + pages[0]] + pages[1:])


POSTOP_1 = _postop("11/05/2024", [[
    "Surgery Performed: Left L4-L5 microdiscectomy on 10/22/2024 (postoperative day 14).",
    "Postoperative Diagnosis: Status post L4-L5 microdiscectomy for disc herniation with radiculopathy (M51.16).",
    "Symptoms: Leg pain improved about 80 percent. Back pain 4/10. Mild residual numbness of the left foot.",
    "Incision: Well healed. No drainage, no erythema, no signs of infection.",
    "Physical Exam: EHL strength 5-/5 on the left. Straight leg raise negative.",
], [
    "Assessment: Recovering as expected after microdiscectomy. No complications.",
    "Medications: Continue oxycodone 5 mg every 8 hours as needed #30 (taper discussed); gabapentin 300 mg three times daily.",
    "PT/Rehab: Start physical therapy 3 times per week for 8 weeks (24 visits).",
    "Restrictions: No lifting over 10 lb. No bending or twisting.",
    "Work Status: Temporary total disability (TTD) - remain off work.",
    "Next Follow-up: 6 weeks.",
]])

POSTOP_2 = _postop("12/17/2024", [[
    "Surgery Performed: Left L4-L5 microdiscectomy on 10/22/2024.",
    "Symptoms: Back pain 5/10. Intermittent left leg pain 2/10. Difficulty sitting longer than 30 minutes.",
    "Physical Exam: Lumbar flexion 60 degrees. Strength 5/5 bilateral lower extremities. Straight leg raise negative.",
], [
    "Assessment: Improving but slower than expected; residual mechanical low back pain.",
    "Medications: Oxycodone 5 mg every 8 hours as needed #30 refilled; patient reports continued need. Taper discussed.",
    "PT/Rehab: Continue physical therapy 3 times per week.",
    "Work Status: Modified duty effective 12/18/2024 - no lifting over 20 lb, no repetitive bending, alternate sitting",
    "and standing every 30 minutes, maximum 6 hours per day.",
    "Employer Accommodation: Patient reports Keystone has no modified duty available at this time.",
    "Next Follow-up: 6 weeks. Consider functional capacity evaluation.",
]])

POSTOP_3 = _postop("03/25/2025", [[
    "Surgery Performed: Left L4-L5 microdiscectomy on 10/22/2024.",
    "Symptoms: Back pain 5/10, unchanged over the last 3 months. No radicular symptoms.",
    "Imaging/Diagnostics: Functional capacity evaluation dated 03/18/2025 reviewed: light physical demand level.",
    "Physical Exam: Lumbar flexion 65 degrees. Strength 5/5. Neurovascularly intact.",
], [
    "Assessment: Residual low back pain after microdiscectomy with a functional plateau.",
    "MMI: Patient has not yet reached maximum medical improvement. Anticipate MMI in approximately 3 months",
    "(06/2025) after completion of a work hardening program. Impairment rating deferred until MMI.",
    "Plan: Work hardening program 5 days per week for 4 weeks. Discontinue oxycodone. Continue gabapentin.",
    "Work Status: Modified duty per FCE - light duty, lifting up to 20 lb occasionally and 10 lb frequently,",
    "no repetitive bending, full time 8 hours per day.",
    "Next Follow-up: 6 weeks.",
]])


def _pt_note(date: str, visit: int, pain: int, odi: int, flexion: int, extra: list[str]) -> list[list[str]]:
    return _doc("PHYSICAL THERAPY PROGRESS NOTE", HDR_PT, [[
        f"Visit Date: {date}    Visit: {visit} of 24    Therapist: Rachel Ortiz, PT, DPT",
        "Diagnosis: Status post L4-L5 microdiscectomy; lumbar radiculopathy (M51.16). Body Part: Lumbar spine.",
        f"Subjective: Patient reports low back pain {pain}/10. Difficulty with prolonged sitting and lifting.",
        f"Objective: Lumbar flexion {flexion} percent of normal. Oswestry Disability Index {odi} percent. Gait normal.",
        "Treatment: Therapeutic exercise (CPT 97110) 30 minutes; manual therapy (CPT 97140) 15 minutes; moist heat.",
    ] + extra])


PT_EVAL = _doc("PHYSICAL THERAPY INITIAL EVALUATION", HDR_PT, [[
    "Visit Date: 11/12/2024    Visit: 1 of 24    Therapist: Rachel Ortiz, PT, DPT",
    "Referring Provider: Alan Reyes, MD    Diagnosis: Status post L4-L5 microdiscectomy (M51.16).",
    "Subjective: Patient reports low back pain 6/10 and difficulty sitting, bending and lifting.",
    "Objective: Lumbar flexion 40 percent of normal. Hip strength 4/5. Oswestry Disability Index 52 percent.",
    "Assessment: Deficits in lumbar mobility, core strength and functional tolerance consistent with post-surgical status.",
], [
    "Goals: Reduce pain to 2/10; Oswestry below 20 percent; lift 50 lb floor to waist to meet job demands.",
    "Plan: Physical therapy 3 times per week for 8 weeks (24 visits): therapeutic exercise, manual therapy,",
    "core stabilization, home exercise program.",
    "Work Restrictions/Functional Status: Per surgeon - no lifting over 10 lb; off work (TTD).",
    "Therapist Signature: Rachel Ortiz, PT, DPT 11/12/2024",
]])

PT_NOTES = (
    _pt_note("12/03/2024", 6, 5, 44, 55, ["Response: Tolerated treatment well. Improved flexion.",
                                           "Progress Toward Goals: Partially met.",
                                           "Plan: Continue plan of care 3 times per week."])
    + _pt_note("12/30/2024", 12, 5, 42, 60, ["Response: Minimal change in pain since visit 6.",
                                              "Progress Toward Goals: Partially met.",
                                              "Plan: Continue plan of care; progress lifting tasks."])
    + _pt_note("01/21/2025", 18, 5, 42, 62, ["Response: Pain unchanged. Progress has plateaued over the last 6 visits.",
                                              "Progress Toward Goals: Not met.",
                                              "Plan: Continue plan of care; reassess at visit 24."])
    + _pt_note("02/11/2025", 24, 5, 40, 65, ["Response: Pain remains 5/10. Functional gains minimal since visit 12.",
                                              "Progress Toward Goals: Not met. Unable to lift more than 20 lb.",
                                              "Plan: Recommend additional physical therapy 3 times per week for 4 weeks (12 visits).",
                                              "Work Restrictions/Functional Status: Modified duty per surgeon."])
)

PT_EXTENSION = [[
    HDR_PT, "UTILIZATION REVIEW REQUEST - REQUEST FOR AUTHORIZATION", PATIENT, "",
    "Request Date: 02/18/2025    Requesting Provider: Rachel Ortiz, PT, DPT on behalf of Alan Reyes, MD",
    "Requested Treatment: Additional physical therapy 3 times per week for 4 weeks (12 visits), CPT 97110 and 97140.",
    "Diagnosis: Status post L4-L5 microdiscectomy (M51.16).",
    "Visits Completed To Date: 24 visits since 11/12/2024.",
    "Clinical Justification: Patient continues to have low back pain 5/10 and cannot meet the medium job demands.",
    "Additional therapy is requested to improve lifting tolerance prior to return to full duty.",
    "Response Requested By: 03/04/2025",
    "", "Page 1 of 1",
]]

PHARMACY = [[
    "GIANT PHARMACY #0412 | 2701 N 5th Street Hwy, Reading, PA | Pharmacy Prescription History",
    "PHARMACY / PRESCRIPTION RECORDS", PATIENT, "Allergies: No known drug allergies.    Diagnosis: M51.16 / M54.16",
    "Billing: Workers' Compensation - Lodestar Claims Management, Claim WC-2024-PA-087341",
    "",
    "Rx 7710231 | Cyclobenzaprine 10 mg tablet | Qty 30 | 1 tab three times daily as needed | Prescriber: Priya Natarajan, MD | Rx Date 09/14/2024 | Filled 09/14/2024 | Refills 0 | Status: Completed",
    "Rx 7710232 | Ibuprofen 800 mg tablet | Qty 30 | 1 tab three times daily | Prescriber: Priya Natarajan, MD | Rx Date 09/14/2024 | Filled 09/14/2024 | Refills 0 | Status: Completed",
    "Rx 7712877 | Oxycodone HCl 5 mg tablet | Qty 28 | 1 tab every 6 hours as needed | Prescriber: Alan Reyes, MD | Rx Date 09/26/2024 | Filled 09/26/2024 | Refills 0 | Status: Completed",
    "Rx 7712878 | Gabapentin 300 mg capsule | Qty 90 | 1 cap three times daily | Prescriber: Alan Reyes, MD | Rx Date 09/26/2024 | Filled 09/26/2024 | Refills 5 | Status: Active",
    "Rx 7714410 | Oxycodone HCl 5 mg tablet | Qty 40 | 1 tab every 6 hours as needed | Prescriber: Alan Reyes, MD | Rx Date 10/10/2024 | Filled 10/10/2024 | Refills 0 | Status: Completed",
    "", "Page 1 of 2",
], [
    "GIANT PHARMACY #0412 | Pharmacy Prescription History (continued)", PATIENT, "",
    "Rx 7716951 | Oxycodone HCl 5 mg tablet | Qty 30 | 1 tab every 8 hours as needed | Prescriber: Alan Reyes, MD | Rx Date 11/05/2024 | Filled 11/05/2024 | Refills 0 | Status: Completed",
    "Rx 7719020 | Oxycodone HCl 5 mg tablet | Qty 30 | 1 tab every 8 hours as needed | Prescriber: Alan Reyes, MD | Rx Date 12/17/2024 | Filled 12/17/2024 | Refills 0 | Status: Completed",
    "Rx 7721544 | Oxycodone HCl 5 mg tablet | Qty 30 | 1 tab every 8 hours as needed | Prescriber: Alan Reyes, MD | Rx Date 01/28/2025 | Filled 01/28/2025 | Refills 0 | Status: Discontinued 03/25/2025",
    "Gabapentin 300 mg refills filled: 10/26/2024, 11/25/2024, 12/24/2024, 01/23/2025, 02/22/2025.",
    "Adverse Reactions: None reported.",
    "", "Page 2 of 2",
]]

FCE = _doc("FUNCTIONAL CAPACITY EVALUATION (FCE) REPORT", HDR_FCE, [
    [
        "Evaluation Date: 03/18/2025    Evaluator: Kevin Marsh, PT, CEAS    Referring Provider: Alan Reyes, MD",
        "Diagnosis: Status post L4-L5 microdiscectomy (M51.16).",
        "Reason for FCE: Determine safe work capacity prior to return to work.",
        "Job Requirements: Warehouse Associate - Medium physical demand level (lift 50 lb occasionally, 25 lb frequently).",
        "Patient-Reported Symptoms: Low back pain 5/10 at rest, 6/10 after lifting.",
    ],
    [
        "Physical Measurements: Lumbar flexion 65 degrees, extension 15 degrees. Grip strength within normal limits.",
        "Functional Testing: Floor to waist lift 20 lb occasional. Waist to shoulder lift 20 lb occasional.",
        "Carry 20 lb for 50 feet. Push/pull 40 lb force. Sitting tolerance 30 minutes. Standing tolerance 45 minutes.",
        "Walking unrestricted. Bending occasional. Squatting occasional. Kneeling occasional. Stair climbing frequent.",
    ],
    [
        "Consistency of Effort: Valid effort - 22 of 24 consistency measures within expected limits.",
        "Pain Response: Pain increased to 6/10 with repetitive lifting; resolved with rest.",
        "Work Capacity Classification: LIGHT physical demand level.",
        "Can the patient meet job demands: No - the job requires the medium physical demand level.",
    ],
    [
        "Functional Limitations/Restrictions: Lift/carry maximum 20 lb occasionally and 10 lb frequently; alternate",
        "sitting and standing every 30 minutes; no repetitive bending.",
        "RTW Recommendations: Return to work at light duty with the restrictions above.",
        "Recommendations: Work hardening program for 4 weeks to progress toward the medium physical demand level.",
        "Evaluator Signature: Kevin Marsh, PT, CEAS    Date: 03/18/2025",
    ],
])


def _bill(provider: str, rows: list[str], dx: str) -> list[str]:
    return [
        "HEALTH INSURANCE CLAIM FORM - CMS-1500 (02/12)", f"Billing Provider: {provider}", PATIENT,
        "Insured: Keystone Industrial Services / Lodestar Claims Management    Condition related to employment: YES",
        f"21. Diagnosis or nature of illness or injury: A. {dx}", "24. Dates of Service | Place of Service | CPT/HCPCS | Units | Charges",
    ] + rows + ["", "Page 1 of 1"]


BILLS = [
    _bill("Berks Orthopedics & Sports Medicine", ["09/26/2024 | 11 | 99204 | 1 | $310.00", "10/10/2024 | 11 | 99214 | 1 | $165.00"], "M54.16"),
    _bill("Berks Imaging Center", ["10/02/2024 | 22 | 72148 MRI lumbar spine without contrast | 1 | $1,250.00"], "M54.16"),
    _bill("Reading Hospital - Tower Health", ["10/22/2024 | 22 | 63030 | 1 | $18,450.00"], "M51.16"),
    _bill("HealthStar PT & Rehabilitation", ["11/12/2024 | 11 | 97163 | 1 | $185.00", "12/03/2024 | 11 | 97110 | 2 | $140.00",
                                              "12/03/2024 | 11 | 97140 | 1 | $65.00", "02/11/2025 | 11 | 97110 | 2 | $140.00"], "M51.16"),
]

WORK_STATUS_SLIP = [[
    HDR_ORTHO, "WORK STATUS SLIP", PATIENT, "",
    "Date of Visit: 12/17/2024    Provider: Alan Reyes, MD",
    "Work Status: Modified duty effective 12/18/2024.",
    "Restrictions: No lifting over 20 lb; no repetitive bending; alternate sitting and standing every 30 minutes;",
    "maximum 6 hours per day.",
    "Duration: Until next re-evaluation in 6 weeks.",
    "Next Appointment: 01/28/2025",
    "", "Page 1 of 1",
]]


def render_pdf(pages: list[list[str]]) -> bytes:
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(False)
    pdf.set_margins(54, 54, 54)
    for lines in pages:
        pdf.add_page()
        y = 60
        for i, line in enumerate(lines):
            if not line:
                y += 8
                continue
            bold = (i < 2 and line.isupper()) or line.startswith(("FAX COVER", "HEALTH INSURANCE CLAIM"))
            pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
            width = pdf.w - 108
            for chunk in _wrap(pdf, line, width):
                pdf.set_xy(54, y)
                pdf.cell(width, 12, chunk)
                y += 14
    return bytes(pdf.output())


def _wrap(pdf: FPDF, text: str, width: float) -> list[str]:
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if pdf.get_string_width(trial) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def build_files() -> list[tuple[str, bytes, str]]:
    """Return [(filename, bytes, source_channel)] for the whole sample package."""
    packet1 = _fax_cover("Reading Hospital - Tower Health HIM", "Lodestar Claims Management", "10/01/2024", 8,
                         "Delgado, WC-2024-PA-087341 - ED record, FROI and employer report") + ED_RECORD + FROI + EMPLOYER_REPORT
    packet2 = (_fax_cover("Berks Orthopedics & Sports Medicine", "Lodestar Claims Management", "10/15/2024", 10,
                          "Delgado - orthopedic records") + ORTHO_CONSULT + ORTHO_FOLLOWUP + [[""]] + ED_RECORD)
    postops = POSTOP_1 + POSTOP_2 + POSTOP_3
    pt = PT_EVAL + PT_NOTES + PT_EXTENSION
    bills = BILLS

    slip_pdf = render_pdf(WORK_STATUS_SLIP)
    msg = EmailMessage()
    msg["From"] = "Sarah Whitfield <swhitfield@meridianrisk.example>"
    msg["To"] = "Jennifer Hartwell <jhartwell@lodestar.example>"
    msg["Subject"] = "RE: Delgado WC-2024-PA-087341 work status update"
    msg["Date"] = "Wed, 18 Dec 2024 09:12:00 -0500"
    msg.set_content(
        "Jennifer,\n\nAttached is the work status slip from Dr. Reyes dated 12/17/2024 releasing Mr. Delgado to "
        "modified duty (no lifting over 20 lb, max 6 hours per day).\n\nKeystone Industrial Services is unable to "
        "accommodate modified duty at this time, so he remains off work.\n\nRegards,\nSarah Whitfield\n"
        "Meridian Risk Partners LLC - Risk Management for Keystone Industrial Services\n")
    msg.add_attachment(slip_pdf, maintype="application", subtype="pdf", filename="WorkStatus_2024-12-17.pdf")

    return [
        ("FAX_2024-10-01_ReadingHospital_packet.pdf", render_pdf(packet1), "fax"),
        ("FAX_2024-10-15_BerksOrtho_packet.pdf", render_pdf(packet2), "fax"),
        ("Operative_Report_2024-10-22.pdf", render_pdf(OP_REPORT), "mail"),
        ("BerksOrtho_PostOp_Notes.pdf", render_pdf(postops), "upload"),
        ("HealthStar_PT_Notes_and_Request.pdf", render_pdf(pt), "upload"),
        ("GiantPharmacy_Rx_History.pdf", render_pdf(PHARMACY), "mail"),
        ("Allied_Rehab_FCE_2025-03-18.pdf", render_pdf(FCE), "upload"),
        ("CMS1500_Bills.pdf", render_pdf(bills), "cms"),
        ("RE_Delgado_work_status_update.eml", msg.as_bytes(), "email"),
    ]


def write_package(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for name, data, _ in build_files():
        p = directory / name
        p.write_bytes(data)
        out.append(p)
    return out


if __name__ == "__main__":  # python -m app.seed.sample_package <dir>
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_package")
    for p in write_package(target):
        print(p)
