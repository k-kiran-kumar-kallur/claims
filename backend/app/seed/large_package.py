"""Large synthetic WC claim package (~280 pages) for volume testing.

Everything here is fictitious.  Claim WC-2025-PA-114209, claimant Daniel R. Okafor, DOI 01/06/2025, lumbar spine.
The package spans ~15 months of care across many providers and deliberately includes the hard cases:
multi-document fax packets with cover sheets and blank separators, duplicate faxes, scanned (image-only) pages that
need OCR, a referenced-but-missing repeat MRI, a long PT course well beyond the prescription and the guideline,
escalating opioids, three epidural injections in one year, a lumbar fusion request, an IME that declares MMI while the
treating surgeon does not, an FCE below job demands, CMS-1500 bills, pharmacy history, and an email with an attachment.

Usage:  python -m app.seed.large_package <output-dir>
"""
from __future__ import annotations

import io
import random
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.seed.sample_package import render_pdf

rnd = random.Random(20250106)

CLAIM = {
    "claim_number": "WC-2025-PA-114209", "claimant": "Daniel R. Okafor", "dob": "1979-07-11", "ssn_last4": "6602",
    "employer_claim_header": "Harbor Point Benefits Group (TPA intake listing)", "employer_froi": "Allegheny Freight & Logistics Inc.",
    "insurer": "Keystone Mutual Casualty", "tpa": "Lodestar Claims Management", "date_of_injury": "2025-01-06",
    "jurisdiction": "PA", "body_part": "lumbar spine", "adjuster": "Jennifer Hartwell, AIC",
}
DOI = date(2025, 1, 6)
PATIENT = "Patient: Daniel R. Okafor    DOB: 07/11/1979    Claim #: WC-2025-PA-114209"
LINES_PER_PAGE = 38


def d(x: date) -> str:
    return x.strftime("%m/%d/%Y")


def paginate(header: str, title: str, body: list[str], min_pages: int = 1) -> list[list[str]]:
    """Split body lines into pages with letterhead, title, patient line and 'Page k of N' footers."""
    chunks = [body[i:i + LINES_PER_PAGE] for i in range(0, max(len(body), 1), LINES_PER_PAGE)] or [[]]
    while len(chunks) < min_pages:
        chunks.append(["(continued)", "Review of Systems: Negative except as noted in the history of present illness.",
                       "Social History: Married, two children. Works full time as a dock loader/forklift operator.",
                       "Family History: Non-contributory.", "Patient education provided; questions answered."])
    n = len(chunks)
    return [[header, title, PATIENT, ""] + c + ["", f"Page {i} of {n}"] for i, c in enumerate(chunks, 1)]


def fax_cover(sender: str, when: date, pages: int, regarding: str) -> list[list[str]]:
    return [["FAX COVER SHEET", "", f"Date: {d(when)}", f"From: {sender}", "To: Lodestar Claims Management - WC Intake",
             f"Number of pages (including cover): {pages}", f"Re: Okafor, WC-2025-PA-114209 - {regarding}", "",
             "CONFIDENTIALITY NOTICE: This facsimile contains confidential health information that is legally privileged.",
             "If you are not the intended recipient, any disclosure, copying or distribution is strictly prohibited."]]


H_ED = "UPMC MERCY | Emergency Department | 1400 Locust St, Pittsburgh, PA"
H_PCP = "NORTH HILLS FAMILY MEDICINE | 4200 McKnight Rd, Pittsburgh, PA"
H_ORTHO = "THREE RIVERS SPINE & ORTHOPEDICS | 300 Penn Center Blvd, Pittsburgh, PA"
H_IMG = "ALLEGHENY DIAGNOSTIC IMAGING | 1001 Liberty Ave, Pittsburgh, PA"
H_PT = "PEAK MOTION PHYSICAL THERAPY | 7700 Perry Hwy, Pittsburgh, PA"
H_PT2 = "STEEL CITY REHAB & SPORTS THERAPY | 225 Ross St, Pittsburgh, PA"
H_CHIRO = "RIVERVIEW CHIROPRACTIC CENTER | 18 Grant Ave, Millvale, PA"
H_PAIN = "WESTERN PA PAIN MANAGEMENT ASSOCIATES | 5 Allegheny Sq, Pittsburgh, PA"
H_LAB = "QUESTLINE LABORATORIES | Pittsburgh Patient Service Center"
H_FCE = "WORKFIT FUNCTIONAL TESTING | 90 Industry Dr, Coraopolis, PA"
H_IME = "INDEPENDENT MEDICAL EVALUATIONS OF PENNSYLVANIA | 600 Grant St, Pittsburgh, PA"

ORTHO_MD = "Victoria Chen, MD - Orthopedic Spine Surgery"
PAIN_MD = "Rahul Iyer, MD - Pain Medicine"
PCP_MD = "Gregory Malone, DO - Family Medicine"


# ---------------------------------------------------------------------------------------------
# clinical documents
# ---------------------------------------------------------------------------------------------

def ed_record() -> list[list[str]]:
    return paginate(H_ED, "EMERGENCY DEPARTMENT VISIT - MEDICAL RECORD", [
        f"Date/Time of Arrival: {d(DOI)} 10:20    MRN: UPM-88310452",
        "Employer: Allegheny Freight & Logistics Inc.    Insurance: Workers' Compensation - Keystone Mutual Casualty",
        f"Date/Time of Injury: {d(DOI)} 08:45    Place of Injury: Allegheny Freight dock 3, Pittsburgh, PA",
        "Mechanism of Injury: Twisted while lifting a 70 lb freight box from a pallet onto a conveyor; immediate low back pain.",
        "Chief Complaint: Low back pain radiating to the right buttock and thigh.",
        "History of Present Illness: 45-year-old dock loader with sudden low back pain 9/10 after a twisting lift. Pain radiates",
        "to the right posterior thigh. No numbness. No bowel or bladder dysfunction. No prior back injury.",
        "Past Medical History: Type 2 diabetes (diet controlled). Hyperlipidemia. Former smoker (quit 2019).",
        "Medications at Home: Atorvastatin 20 mg daily.", "Allergies: Penicillin (rash).",
        "Physical Examination: Paraspinal spasm L3-S1 bilaterally. Flexion limited to 20 degrees. Straight leg raise positive on",
        "the right at 50 degrees. Strength 5/5. Reflexes 2+ and symmetric. Sensation intact.",
        "Diagnostic Testing: X-ray lumbar spine 3 views: no fracture; mild loss of disc height at L5-S1.",
        "Diagnosis: Strain of muscle and tendon of lower back (S39.012A); Low back pain (M54.50).",
        "Treatment Provided: Ketorolac 30 mg IM; diazepam 5 mg PO once.",
        "Medications Prescribed: Cyclobenzaprine 10 mg three times daily as needed x 10 days; Naproxen 500 mg twice daily.",
        "Discharge Instructions: Heat, gentle activity, follow up with primary care in 3-5 days. Return for bowel/bladder changes.",
        f"Work Status: Off work {d(DOI)} through {d(DOI + timedelta(days=4))}; follow up with primary care.",
        "Workers' Compensation: Injury reported as occurring during assigned job duties; history consistent with mechanism.",
        "Provider: Amanda Ruiz, MD - Emergency Medicine", f"Electronically signed: Amanda Ruiz, MD {d(DOI)} 13:02",
    ] + ["Nursing Notes: Pain reassessed 7/10 after ketorolac. Ambulating with antalgic gait. Discharged with family."] * 1,
        min_pages=3)


def froi() -> list[list[str]]:
    return [[
        "EMPLOYER'S FIRST REPORT OF INJURY (FROI) - COMMONWEALTH OF PENNSYLVANIA (LIBC-344)",
        "Employer: Allegheny Freight & Logistics Inc., 2100 Railroad St, Pittsburgh, PA 15222",
        "Employee: Daniel R. Okafor    Occupation: Dock Loader / Forklift Operator    Date of Hire: 03/14/2016",
        f"Date of Injury: {d(DOI)}    Time of Injury: 8:45 AM    Place: Dock 3", "Description of Accident: While lifting a",
        "freight box (approx. 70 lb) from a pallet to a conveyor the employee twisted and felt sharp low back pain.",
        "Mechanism: Lifting/twisting    Nature of Injury: Strain    Part of Body: Low back (lumbar spine)",
        "Witnesses: Maria Kowalski, dock supervisor", f"Date Reported to Employer: {d(DOI)}    Lost Time: Yes, beginning {d(DOI + timedelta(days=1))}",
        "", "Page 1 of 2"], [
        "EMPLOYER'S FIRST REPORT OF INJURY (FROI) - continued",
        "Insurer: Keystone Mutual Casualty    Third Party Administrator: Lodestar Claims Management",
        "Claim Number: WC-2025-PA-114209    Assigned Adjuster: Jennifer Hartwell, AIC",
        "Job Physical Demands: Heavy - lift up to 75 lb occasionally and 35 lb frequently; forklift operation.",
        "Report Prepared By: Kevin Brandt, Harbor Point Benefits Group (TPA intake / employer benefits representative)",
        f"Date Prepared: {d(DOI + timedelta(days=2))}", "", "Page 2 of 2"]]


def employer_report() -> list[list[str]]:
    return [["ALLEGHENY FREIGHT & LOGISTICS - EMPLOYER ACCIDENT / INCIDENT REPORT",
             f"Incident Date: {d(DOI)}    Time: 08:45    Location: Dock 3", "Employee: Daniel R. Okafor    Supervisor: Maria Kowalski",
             "Description: Employee lifted a freight box and twisted to place it on the conveyor; reported immediate back pain.",
             "Safety Review: Conveyor height required twisting; lift assist available but not used.",
             "Corrective Action: Conveyor relocation and refresher training on lift-assist devices.",
             f"Completed by: Maria Kowalski, Dock Supervisor    Date: {d(DOI)}", "", "Page 1 of 1"]]


def pcp_note(when: date, pain: int, ws: str, extra: list[str]) -> list[list[str]]:
    return paginate(H_PCP, "PRIMARY CARE OFFICE VISIT", [
        f"Date of Service: {d(when)}    Provider: {PCP_MD}",
        f"Symptoms: Low back pain {pain}/10 radiating to the right leg; difficulty sleeping and with prolonged sitting.",
        "Physical Exam: Lumbar paraspinal tenderness. Flexion 30 degrees. Straight leg raise positive on the right at 45 degrees.",
        "Assessment: Low back pain with right-sided sciatica (M54.41) after work injury.",
    ] + extra + [f"Work Status: {ws}", f"Signed: Gregory Malone, DO {d(when)}"], min_pages=2)


def ortho_note(when: date, title: str, body: list[str], pages: int = 3) -> list[list[str]]:
    return paginate(H_ORTHO, title, [f"Date of Service: {d(when)}    Provider: {ORTHO_MD}"] + body + [f"Signed: Victoria Chen, MD {d(when)}"],
                    min_pages=pages)


def imaging(when: date, title: str, findings: list[str], impression: str) -> list[list[str]]:
    return paginate(H_IMG, title, [f"Date of Service: {d(when)}    Ordering Provider: {ORTHO_MD}",
                                   "Technique: Multiplanar multisequence imaging without contrast.", "Findings:"] + findings +
                    [f"Impression: {impression}", "Radiologist: Peter Novak, MD", f"Electronically signed: {d(when)}"], min_pages=2)


def pt_eval(header: str, when: date, plan: str, pain: int, odi: int, therapist: str) -> list[list[str]]:
    return paginate(header, "PHYSICAL THERAPY INITIAL EVALUATION", [
        f"Visit Date: {d(when)}    Visit: 1 of 12    Therapist: {therapist}", f"Referring Provider: {ORTHO_MD}",
        "Diagnosis: Lumbar radiculopathy (M54.16). Body Part: Lumbar spine.",
        f"Subjective: Patient reports low back pain {pain}/10 with right leg symptoms; difficulty lifting and sitting.",
        f"Objective: Lumbar flexion 35 percent of normal. Oswestry Disability Index {odi} percent. Core endurance poor.",
        "Assessment: Impairments in mobility, strength and functional tolerance consistent with lumbar radiculopathy.",
        "Goals: Pain 2/10; Oswestry below 20 percent; return to heavy duty lifting 75 lb.",
        f"Plan: {plan}", "Work Restrictions/Functional Status: Per physician.", f"Therapist Signature: {therapist} {d(when)}",
    ], min_pages=2)


def pt_note(header: str, when: date, visit: int, total: int, pain: int, odi: int, flex: int, therapist: str, resp: str) -> list[list[str]]:
    return paginate(header, "PHYSICAL THERAPY PROGRESS NOTE", [
        f"Visit Date: {d(when)}    Visit: {visit} of {total}    Therapist: {therapist}",
        "Diagnosis: Lumbar radiculopathy (M54.16). Body Part: Lumbar spine.",
        f"Subjective: Patient reports low back pain {pain}/10. Sitting tolerance limited.",
        f"Objective: Lumbar flexion {flex} percent of normal. Oswestry Disability Index {odi} percent.",
        "Treatment: Therapeutic exercise (CPT 97110) 30 minutes; manual therapy (CPT 97140) 15 minutes; neuromuscular re-education.",
        f"Response: {resp}", "Plan: Continue plan of care."])


def chiro_note(when: date, visit: int, pain: int) -> list[str]:
    return [H_CHIRO, "CHIROPRACTIC TREATMENT NOTE", PATIENT, "", f"Date of Service: {d(when)}    Visit: {visit}    Provider: Lisa Moretti, DC",
            f"Subjective: Low back pain {pain}/10.", "Objective: Subluxation L4, L5 and sacrum; paraspinal hypertonicity.",
            "Treatment: Spinal manipulation (CPT 98941), electrical stimulation, hot pack.",
            "Response: Temporary relief reported.", "Plan: Continue 2 times per week.", "", "Page 1 of 1"]


# ---------------------------------------------------------------------------------------------
# package assembly
# ---------------------------------------------------------------------------------------------

def build() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    T = DOI

    # 1. initial fax packet: cover + ED + FROI + employer report + blank + PCP notes
    pcp = (pcp_note(T + timedelta(days=3), 8, "Off work - temporary total disability (TTD) pending orthopedic evaluation.",
                    ["Plan: Refer to orthopedic spine surgery. Physical therapy 2 times per week for 6 weeks (12 visits).",
                     "Medications: Hydrocodone-acetaminophen 5-325 mg every 6 hours as needed #20; continue naproxen."])
           + pcp_note(T + timedelta(days=17), 7, "Temporary total disability (TTD) continues.",
                      ["Plan: Await orthopedic consult. Continue home exercise.", "Medications: Hydrocodone-acetaminophen 5-325 mg #30 refilled."]))
    body = ed_record() + froi() + employer_report() + [[""]] + pcp
    files.append(("FAX_2025-01-24_Intake_packet.pdf", render_pdf(fax_cover("UPMC Mercy HIM", T + timedelta(days=18), len(body) + 1, "ED, FROI, PCP") + body)))

    # 2. orthopedic course (pre-surgery) + imaging
    o1 = ortho_note(T + timedelta(days=27), "ORTHOPEDIC SPINE CONSULTATION", [
        "Reason for Consultation: Low back pain with right leg radiculopathy after work injury on 01/06/2025.",
        "History of Injury: Twisting lift injury at Allegheny Freight & Logistics on 01/06/2025.",
        "Symptoms: Low back pain 7/10 radiating to the right posterior thigh and lateral foot; numbness of the right small toe.",
        "Prior Treatment: ED visit, primary care, cyclobenzaprine, naproxen and hydrocodone. No therapy yet.",
        "Medical History: Type 2 diabetes. Former smoker. No prior lumbar injury.",
        "Physical Exam: Straight leg raise positive on the right at 40 degrees. Diminished right Achilles reflex. Plantarflexion 5/5.",
        "Imaging: Lumbar X-rays from 01/06/2025 reviewed: mild L5-S1 disc height loss.",
        "Assessment: Lumbar radiculopathy, right S1 distribution (M54.16); suspected L5-S1 disc herniation.",
        "Causation: Within a reasonable degree of medical certainty the condition is causally related to the 01/06/2025 work injury.",
        "Plan: MRI lumbar spine without contrast. Physical therapy 2 times per week for 6 weeks (12 visits). Gabapentin 300 mg at bedtime.",
        "Work Status: Modified duty - no lifting over 15 lb, no repetitive bending, no forklift operation.",
    ])
    mri1 = imaging(T + timedelta(days=34), "MRI LUMBAR SPINE WITHOUT CONTRAST - RADIOLOGY REPORT", [
        "L3-L4: Mild disc bulge without stenosis.", "L4-L5: Mild facet arthropathy.",
        "L5-S1: Right paracentral disc protrusion contacting the descending right S1 nerve root; mild right foraminal narrowing."],
        "Right paracentral L5-S1 disc protrusion contacting the right S1 nerve root.")
    o2 = ortho_note(T + timedelta(days=48), "ORTHOPEDIC FOLLOW-UP VISIT", [
        "Interval History: MRI 02/09/2025 reviewed with the patient. Attending physical therapy; partial benefit.",
        "Symptoms: Pain 6/10 with intermittent right leg pain.", "Physical Exam: Straight leg raise positive on the right at 50 degrees.",
        "Imaging: MRI 02/09/2025 shows a right paracentral L5-S1 disc protrusion contacting the S1 root.",
        "Assessment: Lumbar disc displacement with radiculopathy, L5-S1 (M51.17). Diagnosis updated from radiculopathy (M54.16).",
        "Plan: Refer to pain management for epidural steroid injection. Continue physical therapy.",
        "Work Status: Modified duty - no lifting over 15 lb; employer reports no modified duty available.",
        "Employer Accommodation: Employer reports no modified duty available at this time.",
    ])
    emg = paginate(H_ORTHO, "ELECTRODIAGNOSTIC STUDY (EMG/NCS) REPORT", [
        f"Date of Service: {d(T + timedelta(days=62))}    Provider: Samuel Ortiz, MD - Physical Medicine and Rehabilitation",
        "Findings: Mild chronic right S1 radiculopathy without active denervation. No peripheral neuropathy.",
        "Impression: Electrodiagnostic evidence of a mild chronic right S1 radiculopathy.", "Signed: Samuel Ortiz, MD"], min_pages=2)
    packet2 = o1 + mri1 + o2 + o1 + emg  # consult faxed twice (duplicate)
    files.append(("FAX_2025-03-12_ThreeRivers_packet.pdf", render_pdf(fax_cover("Three Rivers Spine & Orthopedics", T + timedelta(days=65), len(packet2) + 1, "ortho records, MRI, EMG") + packet2)))

    # 3. PT course 1 (pre-surgery): prescription 12 visits, actual 36 visits
    pt = pt_eval(H_PT, T + timedelta(days=31), "Physical therapy 2 times per week for 6 weeks (12 visits).", 7, 56, "Brian Walsh, PT, DPT")
    visit_date = T + timedelta(days=31)
    pains = [7, 6, 6, 6, 5, 5, 5, 5, 5, 5, 5, 5]
    for v in range(2, 37):
        visit_date += timedelta(days=rnd.choice([3, 4, 3, 4, 7]))
        pain = pains[min(v // 3, len(pains) - 1)]
        odi = max(40, 56 - v)
        resp = "Tolerated treatment well." if v < 14 else ("Pain unchanged; progress has plateaued." if v > 20 else "Minimal change since last week.")
        pt += pt_note(H_PT, visit_date, v, 36, pain, odi, min(70, 35 + v), "Brian Walsh, PT, DPT", resp)
    files.append(("PeakMotion_PT_Course_1.pdf", render_pdf(pt)))

    # 4. chiropractic - scanned TIFF (image-only pages -> OCR)
    chiro_pages = [chiro_note(T + timedelta(days=40 + 4 * i), i + 1, rnd.choice([6, 6, 5, 7])) for i in range(16)]
    files.append(("Riverview_Chiro_SCANNED.tif", _scanned_tiff(chiro_pages)))

    # 5. pain management: consult + 3 ESIs within 12 months (guideline max 2)
    pain_docs = paginate(H_PAIN, "PAIN MANAGEMENT CONSULTATION", [
        f"Date of Service: {d(T + timedelta(days=70))}    Provider: {PAIN_MD}",
        "Reason for Consultation: Right S1 radiculopathy refractory to therapy.",
        "Symptoms: Low back pain 6/10, right leg pain 5/10.", "Physical Exam: Straight leg raise positive on the right.",
        "Assessment: Lumbar disc displacement with radiculopathy L5-S1 (M51.17).",
        "Plan: Right L5-S1 transforaminal epidural steroid injection (CPT 64483). Continue gabapentin 300 mg three times daily.",
        "Medications: Hydrocodone-acetaminophen 7.5-325 mg every 6 hours as needed #60 (dose increased).",
        "Work Status: Modified duty - no lifting over 15 lb.", "Signed: Rahul Iyer, MD"], min_pages=3)
    for i, days in enumerate([84, 140, 300], 1):
        when = T + timedelta(days=days)
        pain_docs += paginate(H_PAIN, "PROCEDURE NOTE - EPIDURAL STEROID INJECTION", [
            f"Date of Service: {d(when)}    Provider: {PAIN_MD}",
            f"Procedure Performed: Right L5-S1 transforaminal epidural steroid injection #{i} under fluoroscopy (CPT 64483).",
            "Indication: Right S1 radiculopathy with concordant MRI findings.", "Medication: Dexamethasone 10 mg, lidocaine 1 percent.",
            "Complications: None.", f"Response: {'About 50 percent relief for 3 weeks' if i < 3 else 'Less than 30 percent relief'}.",
            "Plan: Follow up in 4 weeks.", "Signed: Rahul Iyer, MD"], min_pages=2)
    files.append(("WPA_PainMgmt_Records.pdf", render_pdf(pain_docs)))

    # 6. surgery request, UR, surgery, post-op
    surg = T + timedelta(days=175)
    o3 = ortho_note(T + timedelta(days=155), "ORTHOPEDIC FOLLOW-UP VISIT", [
        "Interval History: Two epidural injections with temporary relief only. Completed 36 therapy visits.",
        "Symptoms: Pain 7/10, worsening right leg pain, new weakness of right plantarflexion.",
        "Physical Exam: Right plantarflexion 4/5. Absent right Achilles reflex. Straight leg raise positive at 35 degrees.",
        "Assessment: Lumbar disc displacement with radiculopathy, L5-S1 (M51.17), progressive motor deficit.",
        f"Plan: Recommend right L5-S1 microdiscectomy. Surgery scheduled {d(surg)} at UPMC Mercy.",
        "Medications: Oxycodone 5 mg every 6 hours as needed #60 (changed from hydrocodone).",
        "Work Status: Temporary total disability (TTD) - off work pending surgery.",
    ])
    ur_req = [[H_ORTHO, "UTILIZATION REVIEW REQUEST - REQUEST FOR AUTHORIZATION", PATIENT, "",
               f"Request Date: {d(T + timedelta(days=156))}    Requesting Provider: {ORTHO_MD}",
               "Requested Treatment: Right L5-S1 microdiscectomy (CPT 63030) with 1 day inpatient stay.",
               "Diagnosis: Lumbar disc displacement with radiculopathy L5-S1 (M51.17).",
               "Clinical Justification: Progressive motor deficit, concordant MRI and EMG, failed 5 months of conservative care.",
               f"Response Requested By: {d(T + timedelta(days=170))}", "", "Page 1 of 1"]]
    ur_dec = paginate("LODESTAR UTILIZATION REVIEW SERVICES | Physician Review", "UTILIZATION REVIEW DETERMINATION LETTER", [
        f"Determination Date: {d(T + timedelta(days=166))}", "Request: Right L5-S1 microdiscectomy (CPT 63030).",
        "Determination: Certified. Criteria met: radiculopathy with concordant imaging and progressive motor deficit.",
        "Reviewer: Helen Park, MD - Orthopedic Surgery"], min_pages=2)
    op = paginate("UPMC MERCY | Department of Surgery | Pittsburgh, PA", "OPERATIVE REPORT", [
        f"Date of Surgery: {d(surg)}    Location: UPMC Mercy, OR 4",
        "Preoperative Diagnosis: Right L5-S1 disc herniation with S1 radiculopathy (M51.17).", "Postoperative Diagnosis: Same.",
        "Procedure Performed: Right L5-S1 hemilaminotomy and microdiscectomy (CPT 63030).",
        "Surgeon: Victoria Chen, MD    Assistant: Owen Grant, PA-C", "Anesthesia: General endotracheal anesthesia.",
        "Indication for Surgery: Progressive right S1 motor deficit with concordant MRI and EMG despite conservative care.",
        "Intraoperative Findings: Sequestered disc fragment compressing the right S1 nerve root; root decompressed.",
        "Implants: None.    Estimated Blood Loss: 40 mL.    Specimens: Disc fragments to pathology.", "Complications: None.",
        "Postoperative Plan: Discharge postoperative day 1. No lifting over 10 lb for 6 weeks. Begin physical therapy at 3 weeks.",
        f"Surgeon Signature: Victoria Chen, MD    Date: {d(surg)}"], min_pages=3)
    postop = []
    for i, (days, pain, ws, mmi) in enumerate([
        (14, 4, "Temporary total disability (TTD) - remain off work.", None),
        (49, 4, "Temporary total disability (TTD) continues.", None),
        (98, 5, "Modified duty - no lifting over 20 lb, no repetitive bending, maximum 6 hours per day.", None),
        (161, 5, "Modified duty - no lifting over 20 lb, no repetitive bending.", None),
        (245, 5, "Modified duty per FCE - light duty, lifting up to 20 lb occasionally and 10 lb frequently.",
         "Patient has not yet reached maximum medical improvement. Anticipate MMI in approximately 4 months (08/2026) after the requested fusion is decided."),
    ], 1):
        when = surg + timedelta(days=days)
        body = [f"Surgery Performed: Right L5-S1 microdiscectomy on {d(surg)}.",
                "Postoperative Diagnosis: Status post L5-S1 microdiscectomy (M51.17).",
                f"Symptoms: Back pain {pain}/10. Right leg pain {'resolved' if i < 3 else 'intermittent 3/10'}.",
                "Incision: Well healed, no signs of infection." if i == 1 else "Physical Exam: Strength 5/5. Straight leg raise negative.",
                "Assessment: Recovering after microdiscectomy." if i < 3 else "Assessment: Persistent mechanical low back pain; functional plateau.",
                "Medications: Oxycodone 5 mg every 8 hours as needed #45 refilled." if i < 5 else "Medications: Discontinue oxycodone; tramadol 50 mg as needed.",
                f"Work Status: {ws}"]
        if i == 2:
            body.insert(3, "PT/Rehab: Start physical therapy 2 times per week for 8 weeks (16 visits).")
        if i == 4:
            body.insert(3, "Interval History: Repeat MRI lumbar spine performed 02/02/2026 at Allegheny Diagnostic Imaging was reviewed.")
            body.insert(4, "Imaging: Repeat MRI 02/02/2026 shows postoperative changes and L5-S1 disc degeneration without recurrent herniation.")
        if mmi:
            body += [f"MMI: {mmi}", "Plan: Request authorization for L5-S1 lumbar fusion (CPT 22612) for discogenic pain."]
        postop += ortho_note(when, "POST-OPERATIVE FOLLOW-UP NOTE", body, pages=3)
    surg_pkt = o3 + ur_req + ur_dec + op + postop
    files.append(("ThreeRivers_Surgery_and_PostOp.pdf", render_pdf(surg_pkt)))

    # 7. post-op PT course 2 (prescribed 16, 24 documented), pain plateau
    pt2 = pt_eval(H_PT2, surg + timedelta(days=52), "Physical therapy 2 times per week for 8 weeks (16 visits).", 5, 46, "Nina Petrov, PT")
    vd = surg + timedelta(days=52)
    for v in range(2, 25):
        vd += timedelta(days=rnd.choice([3, 4, 3, 4]))
        pt2 += pt_note(H_PT2, vd, v, 24, 5 if v > 6 else 4, max(34, 46 - v), min(75, 45 + v), "Nina Petrov, PT",
                       "Pain unchanged at 5/10; minimal functional gains." if v > 12 else "Improving core endurance.")
    files.append(("SteelCity_PostOp_PT.pdf", render_pdf(pt2)))
    files.append(("SteelCity_PostOp_PT_DUPLICATE_FAX.pdf", render_pdf(fax_cover("Steel City Rehab", vd, 9, "PT notes (resend)") + pt2[2:10])))

    # 8. FCE, IME (MMI reached - conflicts with treating surgeon), fusion request, second UR
    fce = paginate(H_FCE, "FUNCTIONAL CAPACITY EVALUATION (FCE) REPORT", [
        f"Evaluation Date: {d(surg + timedelta(days=230))}    Evaluator: Carla Jensen, OTR/L, CEAS    Referring Provider: {ORTHO_MD}",
        "Diagnosis: Status post L5-S1 microdiscectomy (M51.17).", "Reason for FCE: Determine safe work capacity.",
        "Job Requirements: Dock Loader - Heavy physical demand level (lift 75 lb occasionally, 35 lb frequently).",
        "Patient-Reported Symptoms: Low back pain 5/10.",
        "Functional Testing: Floor to waist lift 20 lb occasional. Carry 20 lb 50 feet. Sitting tolerance 30 minutes.",
        "Consistency of Effort: Valid effort - 20 of 22 consistency measures within expected limits.",
        "Work Capacity Classification: LIGHT physical demand level.",
        "Can the patient meet job demands: No - the job requires the heavy physical demand level.",
        "Functional Limitations/Restrictions: Lift/carry maximum 20 lb occasionally and 10 lb frequently; no repetitive bending.",
        "RTW Recommendations: Return to work at light duty; vocational assessment recommended.",
        "Evaluator Signature: Carla Jensen, OTR/L"], min_pages=8)
    ime = paginate(H_IME, "INDEPENDENT MEDICAL EXAMINATION (IME) REPORT", [
        f"Date of Service: {d(surg + timedelta(days=262))}    Provider: Robert Feldman, MD - Orthopedic Surgery (Independent Examiner)",
        "Records Reviewed: ED, primary care, orthopedic, pain management, therapy, chiropractic, operative and FCE records.",
        "History of Injury: Lifting/twisting injury 01/06/2025.", "Symptoms: Low back pain 5/10, no radicular pain.",
        "Physical Exam: Lumbar flexion 60 degrees, strength 5/5, straight leg raise negative, non-organic signs 1 of 5.",
        "Assessment: Status post L5-S1 microdiscectomy (M51.17) with residual mechanical low back pain.",
        "Causation: The L5-S1 herniation and surgery are causally related to the 01/06/2025 work injury.",
        "MMI: In my opinion the claimant has reached maximum medical improvement as of this examination.",
        "Impairment Rating: 8% whole person impairment per AMA Guides 6th edition.",
        "Opinion: Lumbar fusion is not medically indicated; no instability on imaging. Further passive therapy not indicated.",
        "Work Status: Light duty per FCE restrictions; permanent restrictions lift 20 lb occasionally.",
        "Signed: Robert Feldman, MD"], min_pages=16)
    fusion_req = [[H_ORTHO, "UTILIZATION REVIEW REQUEST - REQUEST FOR AUTHORIZATION", PATIENT, "",
                   f"Request Date: {d(surg + timedelta(days=247))}    Requesting Provider: {ORTHO_MD}",
                   "Requested Treatment: L5-S1 posterior lumbar fusion (CPT 22612) with instrumentation.",
                   "Diagnosis: Status post microdiscectomy with discogenic low back pain (M51.17).",
                   "Clinical Justification: Persistent mechanical back pain after microdiscectomy and 60 therapy visits.",
                   f"Response Requested By: {d(surg + timedelta(days=261))}", "", "Page 1 of 1"]]
    esi3_req = [[H_PAIN, "UTILIZATION REVIEW REQUEST - REQUEST FOR AUTHORIZATION", PATIENT, "",
                 f"Request Date: {d(T + timedelta(days=290))}    Requesting Provider: {PAIN_MD}",
                 "Requested Treatment: Third right L5-S1 transforaminal epidural steroid injection (CPT 64483) within 12 months.",
                 "Diagnosis: Lumbar radiculopathy (M54.16).", "Clinical Justification: Recurrent radicular pain.",
                 f"Response Requested By: {d(T + timedelta(days=298))}", "", "Page 1 of 1"]]
    files.append(("FCE_IME_and_UR_Requests.pdf", render_pdf(fce + ime + fusion_req + esi3_req)))

    # 9. pharmacy history (escalating opioids)
    rows, rx, fills = [], 8100400, []
    for days, drug, qty, freq, presc in [
        (0, "Cyclobenzaprine 10 mg tablet", 30, "1 tab three times daily as needed", "Amanda Ruiz, MD"),
        (0, "Naproxen 500 mg tablet", 60, "1 tab twice daily", "Amanda Ruiz, MD"),
        (3, "Hydrocodone-Acetaminophen 5-325 mg tablet", 20, "1 tab every 6 hours as needed", "Gregory Malone, DO"),
        (17, "Hydrocodone-Acetaminophen 5-325 mg tablet", 30, "1 tab every 6 hours as needed", "Gregory Malone, DO"),
        (27, "Gabapentin 300 mg capsule", 30, "1 cap at bedtime", "Victoria Chen, MD"),
        (45, "Hydrocodone-Acetaminophen 5-325 mg tablet", 45, "1 tab every 6 hours as needed", "Victoria Chen, MD"),
        (70, "Hydrocodone-Acetaminophen 7.5-325 mg tablet", 60, "1 tab every 6 hours as needed", "Rahul Iyer, MD"),
        (100, "Hydrocodone-Acetaminophen 7.5-325 mg tablet", 60, "1 tab every 6 hours as needed", "Rahul Iyer, MD"),
        (128, "Hydrocodone-Acetaminophen 7.5-325 mg tablet", 60, "1 tab every 6 hours as needed", "Rahul Iyer, MD"),
        (155, "Oxycodone HCl 5 mg tablet", 60, "1 tab every 6 hours as needed", "Victoria Chen, MD"),
        (176, "Oxycodone HCl 5 mg tablet", 40, "1 tab every 6 hours as needed", "Victoria Chen, MD"),
        (190, "Oxycodone HCl 5 mg tablet", 45, "1 tab every 8 hours as needed", "Victoria Chen, MD"),
        (224, "Oxycodone HCl 5 mg tablet", 45, "1 tab every 8 hours as needed", "Victoria Chen, MD"),
        (262, "Oxycodone HCl 5 mg tablet", 45, "1 tab every 8 hours as needed", "Victoria Chen, MD"),
        (300, "Oxycodone HCl 5 mg tablet", 45, "1 tab every 8 hours as needed", "Victoria Chen, MD"),
        (336, "Oxycodone HCl 5 mg tablet", 45, "1 tab every 8 hours as needed", "Victoria Chen, MD"),
        (420, "Tramadol 50 mg tablet", 60, "1 tab every 6 hours as needed", "Victoria Chen, MD"),
    ]:
        when = T + timedelta(days=days)
        rx += rnd.randint(11, 97)
        rows.append(f"Rx {rx} | {drug} | Qty {qty} | {freq} | Prescriber: {presc} | Rx Date {d(when)} | Filled {d(when)} | Refills 0 | Status: Completed")
        fills.append(when)
    pharm = []
    for i in range(0, len(rows), 6):
        pharm.append(["CVS PHARMACY #2291 | 3300 Fifth Ave, Pittsburgh, PA | Pharmacy Prescription History", "PHARMACY / PRESCRIPTION RECORDS",
                      PATIENT, "Allergies: Penicillin.    Billing: Workers' Compensation - Lodestar Claims Management", ""] + rows[i:i + 6] + ["", f"Page {i // 6 + 1} of {(len(rows) + 5) // 6}"])
    files.append(("CVS_Pharmacy_History.pdf", render_pdf(pharm)))

    # 10. labs (pre-op)
    labs = paginate(H_LAB, "LABORATORY REPORT", [
        f"Date of Service: {d(surg - timedelta(days=7))}    Ordering Provider: {ORTHO_MD}",
        "Hemoglobin A1c 6.4 percent (reference below 5.7) - HIGH", "Basic metabolic panel within normal limits.",
        "CBC within normal limits.", "Urine drug screen: positive for hydrocodone (prescribed); otherwise negative.",
        "Reference range values listed per test."], min_pages=4)
    files.append(("Questline_Labs.pdf", render_pdf(labs)))

    # 11. work status slips (monthly)
    slips = []
    for m in range(1, 13):
        when = T + timedelta(days=30 * m)
        ws = ("Temporary total disability (TTD) - off work." if 150 <= 30 * m <= 230 else
              "Modified duty - no lifting over 15 lb; no forklift operation." if 30 * m < 150 else
              "Modified duty - no lifting over 20 lb, no repetitive bending.")
        slips.append([H_ORTHO, "WORK STATUS SLIP", PATIENT, "", f"Date of Visit: {d(when)}    Provider: Victoria Chen, MD",
                      f"Work Status: {ws}", "Duration: Until next re-evaluation.", "", "Page 1 of 1"])
    files.append(("Work_Status_Slips_2025-2026.pdf", render_pdf(slips)))

    # 12. CMS-1500 bills (note: billed repeat MRI 02/02/2026 whose report is missing)
    bill_rows = [("Three Rivers Spine & Orthopedics", f"{d(T + timedelta(days=27))} | 11 | 99204 | 1 | $325.00", "M54.16"),
                 ("Allegheny Diagnostic Imaging", f"{d(T + timedelta(days=34))} | 22 | 72148 MRI lumbar spine without contrast | 1 | $1,320.00", "M54.16"),
                 ("Allegheny Diagnostic Imaging", "02/02/2026 | 22 | 72148 MRI lumbar spine without contrast | 1 | $1,320.00", "M51.17"),
                 ("UPMC Mercy", f"{d(surg)} | 21 | 63030 | 1 | $21,980.00", "M51.17")]
    bill_rows += [("Western PA Pain Management Associates", f"{d(T + timedelta(days=x))} | 22 | 64483 | 1 | $1,150.00", "M51.17") for x in (84, 140, 300)]
    for k in range(18):
        bill_rows.append(("Peak Motion Physical Therapy" if k < 12 else "Steel City Rehab & Sports Therapy",
                          f"{d(T + timedelta(days=35 + 9 * k))} | 11 | 97110 | 2 | $150.00", "M54.16"))
    bills = [["HEALTH INSURANCE CLAIM FORM - CMS-1500 (02/12)", f"Billing Provider: {prov}", PATIENT,
              "Insured: Allegheny Freight & Logistics / Lodestar Claims Management    Condition related to employment: YES",
              f"21. Diagnosis or nature of illness or injury: A. {dx}", "24. Dates of Service | Place of Service | CPT/HCPCS | Units | Charges",
              row, "", "Page 1 of 1"] for prov, row, dx in bill_rows]
    files.append(("CMS1500_Bills_2025-2026.pdf", render_pdf(bills)))

    # 12b. primary care follow-ups (diabetes / pain) - mostly routine, some noise for the summarizer
    pcp2 = []
    for k, days in enumerate([60, 110, 200, 260, 330, 400]):
        pcp2 += pcp_note(T + timedelta(days=days), 5 if days > 200 else 6, "Per orthopedics.",
                         ["Plan: Diabetes follow-up; A1c monitoring. Back care per orthopedics.",
                          "Medications: Metformin 500 mg twice daily started." if k == 2 else "Medications: No change."])
    files.append(("NorthHills_PCP_FollowUps.pdf", render_pdf(pcp2)))

    psych = paginate("ALLEGHENY BEHAVIORAL HEALTH | Pain Psychology", "PSYCHOLOGICAL EVALUATION FOR CHRONIC PAIN", [
        f"Date of Service: {d(surg + timedelta(days=200))}    Provider: Elaine Brooks, PhD - Clinical Psychology",
        "Reason for Referral: Pre-fusion psychological screening requested by Victoria Chen, MD.",
        "Symptoms: Low back pain 5/10; sleep disturbance; worry about job loss.",
        "Testing: PHQ-9 = 11 (moderate depression); GAD-7 = 9; Pain Catastrophizing Scale = 31 (elevated).",
        "Assessment: Adjustment disorder with mixed anxiety and depressed mood (F43.23); elevated fear-avoidance.",
        "Recommendations: Cognitive behavioral therapy 8 sessions; address fear-avoidance before any further surgery.",
        "Signed: Elaine Brooks, PhD"], min_pages=6)
    files.append(("Behavioral_Health_Eval.pdf", render_pdf(psych)))

    wc = []
    for k in range(10):
        when = surg + timedelta(days=270 + 3 * k)
        wc += paginate(H_PT2, "WORK CONDITIONING DAILY NOTE", [
            f"Visit Date: {d(when)}    Visit: {k + 1} of 10    Therapist: Nina Petrov, PT",
            "Subjective: Low back pain 5/10.", f"Objective: Floor to waist lift {20 + 2 * (k // 3)} lb; carry 20 lb 100 feet.",
            "Treatment: Work hardening/conditioning (CPT 97545) 2 hours.",
            "Response: Minimal change in lifting tolerance." if k > 4 else "Tolerated program.", "Plan: Continue program."])
    files.append(("SteelCity_Work_Conditioning.pdf", render_pdf(wc)))

    # 13. correspondence email with attachment
    msg = EmailMessage()
    msg["From"] = "Kevin Brandt <kbrandt@harborpoint.example>"
    msg["To"] = "Jennifer Hartwell <jhartwell@lodestar.example>"
    msg["Subject"] = "RE: Okafor WC-2025-PA-114209 - light duty availability"
    msg["Date"] = "Mon, 13 Apr 2026 10:05:00 -0400"
    msg.set_content("Jennifer,\n\nAllegheny Freight & Logistics cannot offer a light-duty position within the FCE restrictions "
                    "(20 lb occasional). Mr. Okafor remains off work. Attached is the latest work status slip.\n\n"
                    "Kevin Brandt\nHarbor Point Benefits Group\n")
    msg.add_attachment(render_pdf([slips[-1]]), maintype="application", subtype="pdf", filename="WorkStatus_latest.pdf")
    files.append(("RE_Okafor_light_duty.eml", msg.as_bytes()))
    return files


def _scanned_tiff(pages: list[list[str]]) -> bytes:
    """Image-only multi-page TIFF (simulated fax scan) - text must be recovered by OCR."""
    font = ImageFont.load_default()
    frames = []
    for lines in pages:
        img = Image.new("L", (1275, 1650), 255)
        dr = ImageDraw.Draw(img)
        y = 90
        for ln in lines:
            dr.text((80 + rnd.randint(-2, 2), y), ln, fill=rnd.randint(0, 40), font=font)
            y += 32
        frames.append(img.rotate(rnd.uniform(-0.8, 0.8), fillcolor=255))
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:], compression="tiff_deflate")
    return buf.getvalue()


ANSWER_KEY = """# Answer key - synthetic claim WC-2025-PA-114209 (all data fictitious)

## Create the claim with this metadata (Claims -> New claim)
| Field | Value |
|---|---|
| Claim number | WC-2025-PA-114209 |
| Injured worker | Daniel R. Okafor (DOB 1979-07-11, SSN last 4: 6602) |
| Date of injury | 2025-01-06 |
| Employer (enter as listed by TPA intake) | Harbor Point Benefits Group  <- intentional conflict: FROI says Allegheny Freight & Logistics Inc. |
| Insurer / TPA | Keystone Mutual Casualty / Lodestar Claims Management |
| Jurisdiction / body part | PA / lumbar spine |

Upload every file in this folder (source channel: fax), then click **Start processing**.

## What the app should find
* **HITL-0**: employer conflict (Harbor Point vs Allegheny Freight & Logistics - confirm the FROI employer).
* **Packet splitting / noise**: fax cover sheets and a blank separator removed; the orthopedic consultation faxed twice and
  8 post-op PT pages re-sent by fax are detected as duplicates.
* **OCR**: `Riverview_Chiro_SCANNED.tif` is image-only (12 chiropractic notes). With Gemini enabled the pages are OCR'd; in
  offline rules mode they have no text and are flagged for human handling.
* **Missing record**: repeat MRI dated 02/02/2026 is referenced in the post-op note and billed (CPT 72148) but its report is not in the file.
* **Visit-count mismatch / excessive PT**: first course prescribed 12 visits, 36 documented; post-op course prescribed 16,
  24 documented (guideline sample: 16 post-surgical).
* **Opioids**: hydrocodone escalating 5 -> 7.5 mg, then oxycodone, ~14 months of fills (guideline sample: 14 days).
* **Epidural injections**: three ESIs in < 12 months and a request for a third (guideline sample: max 2 per year).
* **Stalled recovery**: pain flat at 5/10 across the later PT notes and post-op visits.
* **Fusion request (CPT 22612)**: guideline sample says not recommended without instability; IME also says not indicated.
* **Conflicting MMI opinions**: IME (Robert Feldman, MD) = MMI reached, 8% WPI; treating surgeon = not reached, anticipated 08/2026.
* **FCE**: light capacity vs heavy job -> cannot return to regular job; employer cannot accommodate light duty (email).
* **Barriers**: diabetes (A1c 6.4%), no modified duty available, prolonged opioids.
* **Risk**: high / exceptional -> HITL-5 supervisor sign-off.
"""


def write_package(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for name, data in build():
        p = directory / name
        p.write_bytes(data)
        out.append(p)
    (directory / "ANSWER_KEY.md").write_text(ANSWER_KEY)
    return out


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_package_large")
    for p in write_package(target):
        print(p.name)


# ---------------------------------------------------------------------------------------------
# Small single-PDF test packet (~20 pages) for quick end-to-end tests
# ---------------------------------------------------------------------------------------------

SMALL_CLAIM_NUMBER = "WC-2025-PA-114220"


def build_small() -> bytes:
    T = DOI
    surg = T + timedelta(days=175)
    pages: list[list[str]] = []
    pages += fax_cover("Lodestar WC Intake (combined packet)", T + timedelta(days=430), 21, "medical records for review")
    pages += paginate(H_ED, "EMERGENCY DEPARTMENT VISIT - MEDICAL RECORD", [
        f"Date/Time of Arrival: {d(DOI)} 10:20    MRN: UPM-88310452",
        "Employer: Allegheny Freight & Logistics Inc.",
        f"Date/Time of Injury: {d(DOI)} 08:45    Place of Injury: Allegheny Freight dock 3, Pittsburgh, PA",
        "Mechanism of Injury: Twisted while lifting a 70 lb freight box from a pallet onto a conveyor; immediate low back pain.",
        "Chief Complaint: Low back pain radiating to the right buttock and thigh.",
        "Physical Examination: Paraspinal spasm L3-S1. Flexion limited to 20 degrees. Straight leg raise positive on the right at 50 degrees.",
        "Diagnostic Testing: X-ray lumbar spine 3 views: no fracture; mild loss of disc height at L5-S1.",
        "Diagnosis: Strain of muscle and tendon of lower back (S39.012A); Low back pain (M54.50).",
        "Medications Prescribed: Cyclobenzaprine 10 mg three times daily as needed x 10 days; Naproxen 500 mg twice daily.",
        f"Work Status: Off work {d(DOI)} through {d(DOI + timedelta(days=4))}; follow up with primary care.",
        "Provider: Amanda Ruiz, MD - Emergency Medicine"])
    pages += froi()
    consult = ortho_note(T + timedelta(days=27), "ORTHOPEDIC SPINE CONSULTATION", [
        "Reason for Consultation: Low back pain with right leg radiculopathy after work injury on 01/06/2025.",
        "Symptoms: Low back pain 7/10 radiating to the right posterior thigh and lateral foot.",
        "Physical Exam: Straight leg raise positive on the right at 40 degrees. Diminished right Achilles reflex.",
        "Assessment: Lumbar radiculopathy, right S1 distribution (M54.16); suspected L5-S1 disc herniation.",
        "Causation: Within a reasonable degree of medical certainty the condition is causally related to the 01/06/2025 work injury.",
        "Plan: MRI lumbar spine without contrast. Physical therapy 2 times per week for 6 weeks (12 visits).",
        "Medications: Hydrocodone-acetaminophen 5-325 mg every 6 hours as needed #30.",
        "Work Status: Modified duty - no lifting over 15 lb, no repetitive bending."], pages=1)
    pages += consult
    pages += imaging(T + timedelta(days=34), "MRI LUMBAR SPINE WITHOUT CONTRAST - RADIOLOGY REPORT",
                     ["L5-S1: Right paracentral disc protrusion contacting the descending right S1 nerve root."],
                     "Right paracentral L5-S1 disc protrusion contacting the right S1 nerve root.")[:1]
    pages += consult  # same consultation faxed twice (duplicate)
    pages += [[""]]   # blank separator page
    pages += pt_eval(H_PT, T + timedelta(days=31), "Physical therapy 2 times per week for 6 weeks (12 visits).", 7, 56, "Brian Walsh, PT, DPT")[:1]
    for v, days, pain, resp in [(12, 72, 5, "Minimal change since last week."), (24, 115, 5, "Pain unchanged; progress has plateaued."),
                                (36, 150, 5, "Pain unchanged; progress has plateaued.")]:
        pages += pt_note(H_PT, T + timedelta(days=days), v, 36, pain, 44, 60, "Brian Walsh, PT, DPT", resp)
    pages += paginate("UPMC MERCY | Department of Surgery | Pittsburgh, PA", "OPERATIVE REPORT", [
        f"Date of Surgery: {d(surg)}    Location: UPMC Mercy, OR 4",
        "Preoperative Diagnosis: Right L5-S1 disc herniation with S1 radiculopathy (M51.17).",
        "Procedure Performed: Right L5-S1 hemilaminotomy and microdiscectomy (CPT 63030).",
        "Indication for Surgery: Progressive right S1 motor deficit with concordant MRI despite conservative care.",
        "Intraoperative Findings: Sequestered disc fragment compressing the right S1 nerve root.",
        "Estimated Blood Loss: 40 mL.    Complications: None.", f"Surgeon Signature: Victoria Chen, MD    Date: {d(surg)}"])
    pages += ortho_note(surg + timedelta(days=245), "POST-OPERATIVE FOLLOW-UP NOTE", [
        f"Surgery Performed: Right L5-S1 microdiscectomy on {d(surg)}.",
        "Interval History: Repeat MRI lumbar spine performed 02/02/2026 at Allegheny Diagnostic Imaging was reviewed.",
        "Symptoms: Back pain 5/10, unchanged over the last 3 months.",
        "Assessment: Persistent mechanical low back pain after microdiscectomy; functional plateau.",
        "MMI: Patient has not yet reached maximum medical improvement. Anticipate MMI in approximately 4 months (08/2026).",
        "Medications: Oxycodone 5 mg every 8 hours as needed #45 refilled.",
        "Work Status: Modified duty per FCE - light duty, lifting up to 20 lb occasionally and 10 lb frequently."], pages=1)
    pages += paginate(H_FCE, "FUNCTIONAL CAPACITY EVALUATION (FCE) REPORT", [
        f"Evaluation Date: {d(surg + timedelta(days=230))}    Evaluator: Carla Jensen, OTR/L, CEAS",
        "Job Requirements: Dock Loader - Heavy physical demand level (lift 75 lb occasionally, 35 lb frequently).",
        "Consistency of Effort: Valid effort - 20 of 22 consistency measures within expected limits.",
        "Work Capacity Classification: LIGHT physical demand level.",
        "Can the patient meet job demands: No - the job requires the heavy physical demand level.",
        "Functional Limitations/Restrictions: Lift/carry maximum 20 lb occasionally and 10 lb frequently; no repetitive bending.",
        "RTW Recommendations: Return to work at light duty; vocational assessment recommended."])
    pages += paginate(H_IME, "INDEPENDENT MEDICAL EXAMINATION (IME) REPORT", [
        f"Date of Service: {d(surg + timedelta(days=262))}    Provider: Robert Feldman, MD - Orthopedic Surgery (Independent Examiner)",
        "Physical Exam: Lumbar flexion 60 degrees, strength 5/5, straight leg raise negative.",
        "Assessment: Status post L5-S1 microdiscectomy (M51.17) with residual mechanical low back pain.",
        "MMI: In my opinion the claimant has reached maximum medical improvement as of this examination.",
        "Impairment Rating: 8% whole person impairment per AMA Guides 6th edition.",
        "Work Status: Light duty per FCE restrictions.", "Signed: Robert Feldman, MD"], min_pages=2)
    rows = [f"Rx {8100400 + i * 37} | {drug} | Qty {q} | 1 tab every 6 hours as needed | Prescriber: {who} | Rx Date {d(T + timedelta(days=x))} | "
            f"Filled {d(T + timedelta(days=x))} | Refills 0 | Status: Completed"
            for i, (x, drug, q, who) in enumerate([(27, "Hydrocodone-Acetaminophen 5-325 mg tablet", 30, "Victoria Chen, MD"),
                                                   (70, "Hydrocodone-Acetaminophen 7.5-325 mg tablet", 60, "Rahul Iyer, MD"),
                                                   (155, "Oxycodone HCl 5 mg tablet", 60, "Victoria Chen, MD"),
                                                   (262, "Oxycodone HCl 5 mg tablet", 45, "Victoria Chen, MD"),
                                                   (336, "Oxycodone HCl 5 mg tablet", 45, "Victoria Chen, MD")])]
    pages += [["CVS PHARMACY #2291 | Pharmacy Prescription History", "PHARMACY / PRESCRIPTION RECORDS", PATIENT, ""] + rows + ["", "Page 1 of 1"]]
    pages += [["HEALTH INSURANCE CLAIM FORM - CMS-1500 (02/12)", "Billing Provider: Allegheny Diagnostic Imaging", PATIENT,
               "Insured: Allegheny Freight & Logistics / Lodestar Claims Management    Condition related to employment: YES",
               "21. Diagnosis or nature of illness or injury: A. M51.17", "24. Dates of Service | Place of Service | CPT/HCPCS | Units | Charges",
               "02/02/2026 | 22 | 72148 MRI lumbar spine without contrast | 1 | $1,320.00", "", "Page 1 of 1"]]
    pages += [[H_ORTHO, "UTILIZATION REVIEW REQUEST - REQUEST FOR AUTHORIZATION", PATIENT, "",
               f"Request Date: {d(surg + timedelta(days=247))}    Requesting Provider: {ORTHO_MD}",
               "Requested Treatment: L5-S1 posterior lumbar fusion (CPT 22612) with instrumentation.",
               "Diagnosis: Status post microdiscectomy with discogenic low back pain (M51.17).",
               f"Response Requested By: {d(surg + timedelta(days=261))}", "", "Page 1 of 1"]]
    pages = [[ln.replace(CLAIM["claim_number"], SMALL_CLAIM_NUMBER) for ln in p] for p in pages]
    return render_pdf(pages)
