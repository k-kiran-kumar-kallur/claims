import { Alert, Box, Button, Chip, LinearProgress, Stack, Step, StepLabel, Stepper, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { CHECKPOINTS, STAGES } from "../api/types";
import { useRunEvents } from "../hooks/useRunEvents";
import { StatusChip } from "./common";

const NODE_LABELS: Record<string, string> = {
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

/** Live stage stepper driven by SSE (spec §13.3 'Live progress'). */
export function RunProgress({ claimId, run }: { claimId: string; run: any }) {
  const active = run && ["queued", "running", "retrying", "awaiting_human", "awaiting_documents"].includes(run.status);
  const { events, connected } = useRunEvents(active ? run.id : null, claimId);
  if (!run) return null;
  const status: Record<string, string> = run.stage_status || {};
  const activeIdx = STAGES.findIndex((s) => status[s.key] === "in_progress" || status[s.key] === "awaiting_review");
  const last = [...events].reverse().find((e) => e.event === "retrying" || e.event === "node_started");
  const review = run.pending_review;
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle2">Workflow run</Typography>
        <StatusChip status={run.status} />
        {run.mode === "incremental" && <Chip label="incremental" size="small" />}
        {active && <Chip size="small" variant="outlined" color={connected ? "success" : "default"} label={connected ? "live" : "connecting"} />}
        {run.current_node && run.status === "running" && <Typography variant="caption" color="text.secondary">{NODE_LABELS[run.current_node] ?? run.current_node}</Typography>}
      </Stack>
      <Stepper activeStep={activeIdx === -1 ? (run.status === "completed" ? STAGES.length : 0) : activeIdx} alternativeLabel sx={{ "& .MuiStepLabel-label": { fontSize: 12 } }}>
        {STAGES.map((s) => (
          <Step key={s.key} completed={status[s.key] === "completed" || run.status === "completed"}>
            <StepLabel error={run.status === "failed" && run.current_stage === s.key}
              optional={status[s.key] === "awaiting_review" ? <Typography variant="caption" color="warning.main">human review</Typography> : undefined}>
              {s.label}
            </StepLabel>
          </Step>
        ))}
      </Stepper>
      {run.status === "running" && <LinearProgress sx={{ mt: 1.5 }} />}
      {last?.event === "retrying" && run.status !== "completed" && (
        <Alert severity="warning" sx={{ mt: 1.5 }}>Retrying after a transient error ({String(last.data.error ?? last.data.reason ?? "").slice(0, 140)}). Progress is checkpointed and will resume automatically.</Alert>
      )}
      {run.status === "failed" && <Alert severity="error" sx={{ mt: 1.5 }}>Run failed: {run.error}. A supervisor can retry from the last checkpoint.</Alert>}
      {review && (
        <Alert severity="info" sx={{ mt: 1.5 }} action={
          <Button component={RouterLink} to={`/claims/${claimId}/${CHECKPOINTS[review.checkpoint]?.path ?? ""}`} size="small" variant="contained">Open</Button>}>
          Paused for <b>{review.checkpoint}</b> - {review.title} (role: {review.assigned_role.replace(/_/g, " ")})
        </Alert>
      )}
    </Box>
  );
}
