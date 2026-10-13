import { Alert, Box, Button, Chip, LinearProgress, Stack, Step, StepLabel, Stepper, Typography } from "@mui/material";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import { Link as RouterLink } from "react-router-dom";
import { CHECKPOINTS, STAGES } from "../api/types";
import { useRunEvents } from "../hooks/useRunEvents";
import { RecentActivity } from "./ActivityLog";
import { RelativeTime, StatusChip } from "./common";
import { NODE_LABELS } from "./runLog";

const ACTIVE = ["queued", "running", "retrying", "awaiting_human", "awaiting_documents"];

/** Live stage stepper driven by SSE (spec §13.3 'Live progress'), with the latest log lines underneath. */
export function RunProgress({ claimId, run }: { claimId: string; run: any }) {
  const active = !!run && ACTIVE.includes(run.status);
  const { events, connected } = useRunEvents(run?.id, claimId, active);
  if (!run) return null;
  const status: Record<string, string> = run.stage_status || {};
  const activeIdx = STAGES.findIndex((s) => status[s.key] === "in_progress" || status[s.key] === "awaiting_review");
  const last = [...events].reverse().find((e) => e.event === "retrying" || e.event === "node_started");
  const review = run.pending_review;
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <StatusChip status={run.status} />
        {run.mode === "incremental" && <Chip label="incremental" size="small" />}
        {active && (
          <Chip size="small" variant="outlined" color={connected ? "success" : "default"} label={connected ? "live" : "connecting"}
            icon={connected ? <Box component="span" sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: "success.main", ml: "8px !important", animation: "pulse 1.4s infinite", "@keyframes pulse": { "50%": { opacity: 0.3 } } }} /> : undefined} />
        )}
        {run.current_node && run.status === "running" && (
          <Typography variant="body2" fontWeight={600} color="primary.main">{NODE_LABELS[run.current_node] ?? run.current_node}...</Typography>
        )}
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" color="text.secondary">
          {run.completed_at ? <>Finished <RelativeTime iso={run.completed_at} variant="caption" /></> : <>Started <RelativeTime iso={run.started_at ?? run.created_at} variant="caption" /></>}
        </Typography>
      </Stack>
      <Box sx={{ overflowX: "auto", pb: 0.5 }}>
      <Stepper activeStep={activeIdx === -1 ? (run.status === "completed" ? STAGES.length : 0) : activeIdx} alternativeLabel sx={{ minWidth: 560, "& .MuiStepLabel-label": { fontSize: 12, mt: "6px !important" } }}>
        {STAGES.map((s) => (
          <Step key={s.key} completed={status[s.key] === "completed" || run.status === "completed"}>
            <StepLabel error={run.status === "failed" && run.current_stage === s.key}
              optional={status[s.key] === "awaiting_review" ? <Typography variant="caption" color="warning.main" display="block">human review</Typography> : undefined}>
              {s.label}
            </StepLabel>
          </Step>
        ))}
      </Stepper>
      </Box>
      {run.status === "running" && <LinearProgress sx={{ mt: 2 }} />}
      {last?.event === "retrying" && run.status !== "completed" && (
        <Alert severity="warning" sx={{ mt: 2 }}>Retrying after a transient error ({String(last.data.error ?? last.data.reason ?? "").slice(0, 140)}). Progress is checkpointed and will resume automatically.</Alert>
      )}
      {run.status === "failed" && <Alert severity="error" sx={{ mt: 2 }}>Run failed: {run.error}. A supervisor can retry from the last checkpoint.</Alert>}
      {review && (
        <Alert severity="info" sx={{ mt: 2 }} action={
          <Button component={RouterLink} to={`/claims/${claimId}/${CHECKPOINTS[review.checkpoint]?.path ?? ""}`} size="small" variant="contained" endIcon={<ArrowForwardIcon />}>Open</Button>}>
          Paused for <b>{review.checkpoint}</b> - {review.title} (role: {review.assigned_role.replace(/_/g, " ")})
        </Alert>
      )}
      {events.length > 0 && (
        <Box sx={{ mt: 2.5 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="overline" color="text.secondary">Recent activity</Typography>
            <Button component={RouterLink} to={`/claims/${claimId}/activity`} size="small" endIcon={<ArrowForwardIcon />}>View full log</Button>
          </Stack>
          <RecentActivity events={events} limit={5} />
        </Box>
      )}
    </Box>
  );
}
