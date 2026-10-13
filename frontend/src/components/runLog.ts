/** Human-readable labels and formatting for workflow run events (shared by RunProgress and ActivityLog). */
import type { RunEvent } from "../hooks/useRunEvents";

export const NODE_LABELS: Record<string, string> = {
  intake_agent: "Ingesting, OCR, packet splitting, baseline", hitl_baseline: "Waiting: baseline confirmation",
  classification_agent: "Dispatching classification", classify_document: "Classifying documents",
  organization_agent: "Building timeline, episodes, gaps", hitl_timeline_check: "Waiting: NCM timeline check",
  clinical_summary_agent: "Writing clinical summary", utilization_agent: "Utilization assessment drafts",
  extraction_agent: "Starting parallel extractors", mmi_extractor: "MMI extraction", rtw_extractor: "RTW extraction",
  treatment_plan_extractor: "Treatment-plan extraction", clinical_fact_extractor: "Clinical fact extraction", ime_extractor: "IME analysis",
  validation_agent: "Grounding validation", hitl_fact_validation: "Waiting: clinical fact validation",
  turning_point_detector: "Detecting turning points", guideline_agent: "Guideline & deviation review",
  chronology_agent: "Building chronology", report_agent: "Writing reports", hitl_summary_review: "Waiting: NCM summary review",
  decision_support_agent: "Preparing decision workspace", routing_agent: "Risk scoring & routing", hitl_decision: "Waiting: claims decision",
  ur_gate: "Waiting: UR determination", hitl_signoff: "Waiting: supervisor sign-off", record_keeping: "Sealing decision record",
  cms_sync: "Logging to CMS", await_documents: "Waiting for requested records",
};

const ACRONYMS: Record<string, string> = { rtw: "RTW", mmi: "MMI", ime: "IME", ur: "UR", cms: "CMS", ncm: "NCM", ocr: "OCR", llm: "LLM" };

/** intake_agent -> "Intake agent", hitl_signoff -> "Human review: signoff", rtw_extractor -> "RTW extractor". */
export function nodeName(node?: string | null): string {
  if (!node) return "Workflow";
  const human = node.startsWith("hitl_");
  const words = node.replace(/^hitl_/, "").split("_").map((w) => ACRONYMS[w] ?? w);
  const s = words.join(" ");
  return human ? `Human review: ${s}` : s.charAt(0).toUpperCase() + s.slice(1);
}

export type LogLevel = "debug" | "info" | "success" | "warning" | "error" | "review";

export interface LogLine {
  id: number;
  ts?: string;
  level: LogLevel;
  node?: string;
  message: string;
  detail?: string;
  /** milliseconds since the matching node_started (node_completed only) */
  durationMs?: number;
  raw: RunEvent;
}

function humanKey(k: string) {
  return k.replace(/_/g, " ");
}

/** Compact "key: value" text for the primitive fields of an event payload. */
export function describeFields(data: Record<string, any> | undefined, skip: string[] = []): string {
  if (!data) return "";
  return Object.entries(data)
    .filter(([k, v]) => !skip.includes(k) && v !== null && v !== undefined && v !== "" && typeof v !== "object")
    .map(([k, v]) => `${humanKey(k)}: ${typeof v === "boolean" ? (v ? "yes" : "no") : v}`)
    .join(" · ");
}

const SKIP = ["node", "ts", "stage", "attempt"];

export function formatEvent(ev: RunEvent): Omit<LogLine, "id" | "raw" | "durationMs"> {
  const d = ev.data ?? {};
  const node = d.node as string | undefined;
  const ts = d.ts as string | undefined;
  const base = { ts, node };
  switch (ev.event) {
    case "run_queued":
      return { ...base, level: "info", message: d.retry ? "Retry queued from the last checkpoint" : `Run queued (${d.mode ?? "full"} mode)` };
    case "run_started":
      return { ...base, level: "info", message: `Run started (${d.mode ?? "full"} mode)` };
    case "run_resumed":
      return { ...base, level: "info", message: "Run resumed after human input" };
    case "node_started":
      return { ...base, level: "debug", message: `${NODE_LABELS[node ?? ""] ?? nodeName(node)}${d.attempt > 1 ? ` (attempt ${d.attempt})` : ""}` };
    case "node_completed":
      return { ...base, level: "success", message: `${nodeName(node)} finished`, detail: describeFields(d.output) || undefined };
    case "tool_called":
      return { ...base, level: "debug", message: `Tool: ${humanKey(String(d.tool ?? "call"))}`, detail: describeFields(d, [...SKIP, "tool"]) || undefined };
    case "retrying":
      return {
        ...base, level: "warning",
        message: node ? `${nodeName(node)} failed, retrying${d.delay_s != null ? ` in ${d.delay_s}s` : ""} (attempt ${d.attempt ?? "?"})`
          : `Run paused, retrying${d.retry_in_s != null ? ` in ${d.retry_in_s}s` : ""}`,
        detail: String(d.error ?? d.reason ?? "") || undefined,
      };
    case "awaiting_review":
      return { ...base, level: "review", message: `Waiting for review at ${d.checkpoint ?? "a human checkpoint"}${d.title ? ` - ${d.title}` : ""}`, detail: "The workflow resumes automatically once the reviewer submits" };
    case "awaiting_documents":
      return { ...base, level: "review", message: `Waiting for requested records${d.title ? ` - ${d.title}` : ""}` };
    case "run_completed":
      return {
        ...base, level: "success", message: "Run completed",
        detail: [d.total_tokens ? `${Number(d.total_tokens).toLocaleString()} tokens` : null, d.cost_usd ? `$${Number(d.cost_usd).toFixed(4)}` : null].filter(Boolean).join(" · ") || undefined,
      };
    case "run_failed":
      return { ...base, level: "error", message: "Run failed", detail: String(d.error ?? "") || undefined };
    case "run_cancelled":
      return { ...base, level: "warning", message: "Run cancelled", detail: String(d.reason ?? d.error ?? "") || undefined };
    default:
      return { ...base, level: "info", message: humanKey(ev.event), detail: describeFields(d, SKIP) || undefined };
  }
}

/** Formats events and attaches node durations by pairing node_completed with its node_started. */
export function toLogLines(events: RunEvent[]): LogLine[] {
  const started: Record<string, number> = {};
  return events.map((ev) => {
    const f = formatEvent(ev);
    const t = f.ts ? new Date(f.ts).getTime() : NaN;
    let durationMs: number | undefined;
    if (ev.event === "node_started" && f.node && !Number.isNaN(t)) started[f.node] = t;
    if (ev.event === "node_completed" && f.node && started[f.node] != null && !Number.isNaN(t)) durationMs = t - started[f.node];
    return { ...f, id: ev.id, raw: ev, durationMs };
  });
}

export function fmtClock(iso?: string): string {
  if (!iso) return "--:--:--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function logToText(lines: LogLine[]): string {
  return lines
    .map((l) => `${l.ts ?? ""}\t${l.level.toUpperCase().padEnd(7)}\t${l.node ?? "-"}\t${l.message}${l.detail ? ` | ${l.detail}` : ""}`)
    .join("\n");
}
