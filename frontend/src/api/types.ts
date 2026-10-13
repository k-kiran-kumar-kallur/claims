/** Domain types mirroring the FastAPI responses (regenerate schema.d.ts with `npm run gen:api`). */

export interface Citation {
  id?: string;
  document_id: string;
  page_number: number;
  line_start: number;
  line_end: number;
  quote: string;
  match_score?: number | null;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  permissions: string[];
  team: string;
  idle_logout_minutes?: number;
  llm_mode?: string;
  mfa_enabled?: boolean;
  is_active?: boolean;
  last_login_at?: string | null;
}

export interface RunSummary {
  id: string;
  status: string;
  current_stage: string | null;
  current_node: string | null;
  stage_status: Record<string, string>;
  pending_review_id?: string | null;
}

export interface Claim {
  id: string;
  claim_number: string;
  claimant: string | null;
  employer_name: string | null;
  insurer: string | null;
  tpa: string | null;
  date_of_injury: string | null;
  jurisdiction_state: string | null;
  body_parts: string[];
  status: string;
  risk_score: number | null;
  complexity: string | null;
  current_stage: string | null;
  baseline_locked: boolean;
  litigated: boolean;
  is_synthetic: boolean;
  pending_reviews: number;
  adjuster_name: string | null;
  assigned: Record<string, { id: string | null; name: string | null }>;
  latest_run: RunSummary | null;
  created_at: string;
  claimant_detail?: { full_name: string | null; dob: string | null; ssn_last4: string | null; contact: string | null };
  baseline?: Record<string, any>;
  review_context?: ReviewContext | null;
  time_window?: { start: string | null; end: string | null };
  mechanism_of_injury?: string | null;
  employer_contact?: string | null;
}

export interface ReviewContext {
  id: string;
  review_goals: string[];
  clinical_question: string;
  required_evidence: string[];
  applicable_guidelines: string[];
  state_rules: string[];
  source: string;
}

export interface Review {
  id: string;
  run_id: string;
  claim_id: string;
  claim_number: string | null;
  checkpoint: string;
  title: string;
  assigned_role: string;
  assigned_user_name: string | null;
  status: string;
  priority: number;
  due_at: string | null;
  claimed_by: string | null;
  claimed_by_name: string | null;
  escalated: boolean;
  blocks_run: boolean;
  created_at: string;
  risk_score: number | null;
  complexity: string | null;
  payload?: any;
  response?: any;
  can_act?: boolean;
}

export interface Flag {
  id: string;
  flag_type: string;
  severity: string;
  title: string;
  detail: string | null;
  ai_recommendation: string | null;
  evidence: Citation[];
  human_action: string | null;
  reason: string | null;
  is_override: boolean;
  acted_by_name?: string | null;
  acted_at?: string | null;
  ref_type?: string | null;
  ref_id?: string | null;
}

export interface Fact {
  id: string;
  fact_type: string;
  label: string;
  value: Record<string, any>;
  effective_date: string | null;
  confidence: number;
  validation_status: string;
  validation_notes: string[];
  is_milestone: boolean;
  citations: Citation[];
  document_id: string | null;
  validated_by_name?: string | null;
  supersedes_fact_id?: string | null;
  extractor: string;
  extractor_version: string;
}

export interface Summary {
  id: string;
  summary_type: string;
  content_md: string;
  content_json: any;
  status: string;
  version: number;
  word_count: number | null;
  citations: Record<string, Citation>;
  author_type: string;
  edited_by_name?: string | null;
  approved_by_name?: string | null;
  approved_at?: string | null;
  created_at: string;
  label?: string | null;
  history?: { id: string; version: number; status: string; author_type: string; created_at: string; content_md: string }[];
}

export interface DocumentItem {
  id: string;
  alias: string | null;
  title: string;
  original_filename: string;
  mime_type: string | null;
  source_channel: string;
  stream: string | null;
  status: string;
  status_reason: string | null;
  page_count: number;
  parent_document_id: string | null;
  is_container: boolean;
  classification: {
    doc_type: string;
    confidence: number;
    provider_name: string | null;
    provider_specialty: string | null;
    facility: string | null;
    service_date_start: string | null;
    service_date_end: string | null;
    body_parts: string[];
    tags: Record<string, any>;
    icd10_codes: string[];
    cpt_codes: string[];
    rationale: string | null;
    classified_by: string;
    version: number;
    needs_attention: boolean;
  } | null;
  episode: { id: string; label: string } | null;
}

export interface Report {
  id: string;
  claim_id: string;
  claim_number?: string;
  report_type: string;
  format: string;
  status: string;
  version: number;
  is_approved_content: boolean;
  created_at: string;
  error: string | null;
  available: boolean;
}

export const DOC_TYPES = [
  "ED Visit Record", "Orthopedic/Specialist Consultation", "Operative Report", "IME Report", "Physical Therapy Progress Note",
  "Rehab Note", "Chiropractic Note", "Pain Management Note", "Primary Care Note", "Post-Op Follow-Up Note", "Treatment Plan",
  "Imaging Report", "Lab Report", "Pharmacy/Prescription Record", "FCE Report", "Work Status Slip",
  "Utilization Review Request/Decision", "Medical Bill", "Employer's First Report of Injury (FROI)", "Employer Accident Report",
  "Policy/Coverage Information", "Legal/Correspondence", "Administrative/Fax Cover", "Other",
];

export const ROLE_LABELS: Record<string, string> = {
  summarization_team: "Summarization Team",
  claims_examiner: "Claims Examiner",
  nurse_case_manager: "Nurse Case Manager",
  clinical_reviewer: "Clinical / UR Reviewer",
  claims_supervisor: "Claims Supervisor",
  attorney: "Defence Counsel",
  admin: "Administrator",
};

export const CHECKPOINTS: Record<string, { label: string; path: string }> = {
  "HITL-0": { label: "Baseline confirmation", path: "baseline" },
  "HITL-1": { label: "Timeline check", path: "timeline" },
  "HITL-2": { label: "Fact validation", path: "facts" },
  "HITL-3": { label: "Summary review", path: "summary" },
  "HITL-4": { label: "Claims decision", path: "decision" },
  "HITL-4-UR": { label: "UR determination", path: "decision" },
  "HITL-5": { label: "Supervisor sign-off", path: "signoff" },
  "AWAIT-DOCS": { label: "Awaiting records", path: "documents" },
};

export const STAGES = [
  { key: "intake", label: "Intake" },
  { key: "classification", label: "Classification" },
  { key: "clinical_review", label: "Clinical review" },
  { key: "extraction", label: "Facts & milestones" },
  { key: "guideline_review", label: "Guidelines" },
  { key: "output", label: "Chronology & summary" },
  { key: "action", label: "Decision" },
];
