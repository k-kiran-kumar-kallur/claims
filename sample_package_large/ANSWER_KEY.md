# Answer key - synthetic claim WC-2025-PA-114209 (all data fictitious)

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
