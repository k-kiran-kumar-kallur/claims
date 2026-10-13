import { Alert, Box, Button, Chip, Grid2 as Grid, LinearProgress, List, ListItem, ListItemText, MenuItem, Stack, TextField, Tooltip, Typography } from "@mui/material";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import FlagIcon from "@mui/icons-material/OutlinedFlag";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ReplayIcon from "@mui/icons-material/Replay";
import StopIcon from "@mui/icons-material/Stop";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Summary } from "../api/types";
import { useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CitationList, CitedMarkdown } from "../components/CitationViewer";
import { AiDraftBadge, asList, EmptyState, ErrorAlert, fmtDate, LoadingRows, ReasonDialog, Section, SeverityChip, StatusChip } from "../components/common";
import { riskColor } from "../theme/theme";
import { RunProgress } from "../components/RunProgress";
import { useDashboard, useRuns, useUsers } from "../hooks/queries";

const MILESTONE_COLORS: Record<string, string> = { surgery: "#7c3aed", mmi: "#0f766e", fce: "#b54708", rtw: "#067647", work_capacity_change: "#067647", diagnosis_change: "#1f4f8f", ime: "#6b7280", treatment_change: "#9a3412" };

export default function DashboardPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const dash = useDashboard(claimId);
  const runs = useRuns(claimId);
  const qc = useQueryClient();
  const [cancelOpen, setCancelOpen] = useState(false);
  const run = runs.data?.[0];
  const refresh = () => { qc.invalidateQueries({ queryKey: ["runs", claimId] }); qc.invalidateQueries({ queryKey: ["claim", claimId] }); qc.invalidateQueries({ queryKey: ["dashboard", claimId] }); };
  const start = useMutation({ mutationFn: (mode: string) => api.post(`/claims/${claimId}/runs`, { mode }), onSuccess: refresh, meta: { success: "Processing started - progress updates live below" } });
  const cancel = useMutation({ mutationFn: (reason: string) => api.post(`/runs/${run!.id}/cancel`, { reason }), onSuccess: refresh, meta: { success: "Run cancelled" } });
  const retry = useMutation({ mutationFn: () => api.post(`/runs/${run!.id}/retry`), onSuccess: refresh, meta: { success: "Retrying from the last checkpoint" } });
  if (dash.isLoading) return <LoadingRows rows={4} height={64} />;
  if (dash.error) return <ErrorAlert error={dash.error} />;
  const d = dash.data;
  const exp = d.exposure;
  const active = run && ["queued", "running", "retrying", "awaiting_human", "awaiting_documents"].includes(run.status);
  const openFlags = d.flags.filter((f: any) => !f.human_action);
  const one = d.one_page_summary;
  return (
    <Box>
      <ErrorAlert error={start.error || cancel.error || retry.error} />
      <Section title="Processing" actions={
        <>
          {can("run:start") && !active && <Button startIcon={<PlayArrowIcon />} variant="contained" onClick={() => start.mutate(run ? "incremental" : "full")} disabled={start.isPending}>{run ? "Process new documents" : "Start processing"}</Button>}
          {can("run:start") && !active && run && <Button onClick={() => start.mutate("full")} disabled={start.isPending}>Full re-run</Button>}
          {active && <Button color="error" startIcon={<StopIcon />} onClick={() => setCancelOpen(true)}>Cancel run</Button>}
          {run?.status === "failed" && can("run:manage") && <Button startIcon={<ReplayIcon />} onClick={() => retry.mutate()}>Retry from checkpoint</Button>}
        </>}>
        {run ? <RunProgress claimId={claimId!} run={run} /> : <EmptyState icon={<AccountTreeIcon />} title="No workflow run yet" hint="Upload the medical-record package on the Documents tab, then start processing. Each of the 7 stages will appear here as it runs."
          action={<Button component={RouterLink} to="documents">Go to documents</Button>} />}
      </Section>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Section title={<>One-page actionable summary {one && <Typography component="span" variant="caption" color="text.secondary">v{one.version} - {one.word_count} words</Typography>}</>}
            actions={one && (one.status === "approved" ? <Chip label={`Approved ${fmtDate(one.approved_at)}`} color="success" /> : <AiDraftBadge label="AI draft - pending NCM review" />)}>
            {one ? <OnePage summaryId={one.id} claimId={claimId!} md={one.content_md} /> : <EmptyState title="Summary not generated yet" hint="It appears after Stage 6 (chronology and summary preparation)." />}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Section title="Exposure indicators">
            <Box sx={{ mb: 2 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="baseline">
                <Typography variant="body2" color="text.secondary">Risk score</Typography>
                <Typography variant="h5" sx={{ color: exp.risk_score != null ? `${riskColor(exp.risk_score)}.main` : "text.secondary" }}>
                  {exp.risk_score != null ? exp.risk_score.toFixed(2) : "-"}
                  {exp.complexity && <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 0.75, textTransform: "capitalize" }}>{exp.complexity}</Typography>}
                </Typography>
              </Stack>
              <LinearProgress variant="determinate" value={Math.min(100, (exp.risk_score ?? 0) * 100)} color={exp.risk_score != null ? riskColor(exp.risk_score) as any : "inherit"} sx={{ height: 8, mt: 0.75, bgcolor: "#eef2f7" }} />
              <Stack direction="row" justifyContent="space-between"><Typography variant="caption" color="text.secondary">Low</Typography><Typography variant="caption" color="text.secondary">High</Typography></Stack>
            </Box>
            <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 1, mb: 1.5 }}>
              {[["TTD days", exp.ttd_days ?? "-", "Days of temporary total disability"], ["Deviations", exp.open_guideline_deviations, "Open guideline deviations"], ["Gaps", exp.open_gaps, "Open timeline gaps"]].map(([k, v, t]) => (
                <Tooltip key={k as string} title={t as string}>
                  <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#f5f7fb", textAlign: "center" }}>
                    <Typography variant="h6">{v as any}</Typography>
                    <Typography variant="caption" color="text.secondary">{k as string}</Typography>
                  </Box>
                </Tooltip>
              ))}
            </Box>
            <Stack spacing={1}>
              {exp.routing_rationale && <Typography variant="caption" color="text.secondary">{exp.routing_rationale}</Typography>}
              {exp.risk_factors?.length > 0 && <Stack direction="row" flexWrap="wrap" gap={0.5}>{exp.risk_factors.map((f: any) => <Tooltip key={f.factor} title={f.detail}><Chip size="small" variant="outlined" label={`${f.factor.replace(/_/g, " ")} +${f.weight}`} /></Tooltip>)}</Stack>}
            </Stack>
          </Section>
          <Section title={`AI flags (${openFlags.length} open)`} actions={can("decision:make") && <Button component={RouterLink} to="decision" size="small">Decision workspace</Button>}>
            {d.flags.length === 0 && <Stack direction="row" spacing={1} alignItems="center" sx={{ color: "text.secondary" }}><FlagIcon fontSize="small" /><Typography variant="body2">No flags yet. They are raised during guideline review.</Typography></Stack>}
            <List dense disablePadding>
              {d.flags.slice(0, 10).map((f: any) => (
                <ListItem key={f.id} disableGutters sx={{ alignItems: "flex-start" }}>
                  <ListItemText primary={<Stack direction="row" spacing={0.75} alignItems="center"><SeverityChip severity={f.severity} /><Typography variant="body2">{f.title}</Typography></Stack>}
                    secondary={f.human_action ? `${f.human_action}${f.is_override ? " (override)" : ""}` : f.ai_recommendation} />
                </ListItem>
              ))}
            </List>
          </Section>
        </Grid>
        <Grid size={12}>
          <Section title="Milestones and turning points">
            {d.milestones.length === 0 ? <Typography variant="body2" color="text.secondary">Detected after fact validation (Stage 4).</Typography> : (
              <Box sx={{ display: "flex", gap: 1.5, overflowX: "auto", pb: 1 }}>
                {d.milestones.map((m: any) => (
                  <Box key={m.id} sx={{ minWidth: 220, maxWidth: 260, p: 1.25, borderRadius: 1.5, border: "1px solid", borderColor: "divider", borderTop: `4px solid ${MILESTONE_COLORS[m.milestone_type] ?? "#1f4f8f"}` }}>
                    <Typography variant="caption" color="text.secondary">{fmtDate(m.milestone_date)} - {m.milestone_type.replace(/_/g, " ")}</Typography>
                    <Typography variant="body2" fontWeight={600} sx={{ mt: 0.25 }}>{m.description}</Typography>
                    {m.impact_narrative && <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>{m.impact_narrative}</Typography>}
                  </Box>
                ))}
              </Box>
            )}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Work status (RTW)">
            {d.rtw_status.length === 0 ? <Typography variant="body2" color="text.secondary">No validated work-status facts yet.</Typography> :
              d.rtw_status.map((r: any) => (
                <Stack key={r.id} direction="row" spacing={1} sx={{ mb: 0.75 }} alignItems="center">
                  <Typography variant="body2" sx={{ width: 90 }}>{fmtDate(r.effective_date)}</Typography>
                  <StatusChip status={r.work_status} />
                  <Typography variant="caption" color="text.secondary">{asList(r.restrictions).map((x: any) => x.limit_lb ? `${x.limit_lb} lb ${x.frequency ?? ""}` : x.limit ?? (x.max_hours_per_day ? `${x.max_hours_per_day} h/day` : x.type)).join("; ")}</Typography>
                </Stack>
              ))}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Gaps and missing records">
            {d.gaps.length === 0 ? <Typography variant="body2" color="text.secondary">No gaps detected.</Typography> :
              d.gaps.map((g: any) => (
                <Stack key={g.id} direction="row" spacing={1} sx={{ mb: 0.75 }} alignItems="flex-start">
                  <SeverityChip severity={g.severity} /><StatusChip status={g.status} />
                  <Box><Typography variant="body2">{g.description}</Typography><CitationList citations={g.evidence} claimId={claimId} /></Box>
                </Stack>
              ))}
          </Section>
        </Grid>
      </Grid>
      {can("decision:signoff") && <AccessPanel claimId={claimId!} />}
      {run?.status === "completed" && <Alert severity="success">Workflow complete - the decision record is sealed and logged to the CMS. Approved reports are available on the Chronology and Reports screens.</Alert>}
      <ReasonDialog open={cancelOpen} title="Cancel workflow run" onClose={() => setCancelOpen(false)} onConfirm={(r) => { setCancelOpen(false); cancel.mutate(r); }} confirmText="Cancel run" />
    </Box>
  );
}

function OnePage({ summaryId, claimId, md }: { summaryId: string; claimId: string; md: string }) {
  const q = useQuery({ queryKey: ["summary", summaryId], queryFn: () => api.get<Summary>(`/summaries/${summaryId}`) });
  return <CitedMarkdown md={md} citations={q.data?.citations ?? {}} claimId={claimId} />;
}

function AccessPanel({ claimId }: { claimId: string }) {
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/members`) });
  const attorneys = useUsers("attorney");
  const [uid, setUid] = useState("");
  const add = useMutation({ mutationFn: () => api.post(`/claims/${claimId}/members`, { user_id: uid, role_key: "attorney" }),
    onSuccess: () => { setUid(""); qc.invalidateQueries({ queryKey: ["members", claimId] }); } });
  return (
    <Section title="Claim access" dense>
      <ErrorAlert error={add.error} />
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
        {(members.data ?? []).map((m) => <Chip key={m.user_id} label={`${m.full_name} (${m.role_key.replace(/_/g, " ")})`} variant="outlined" />)}
      </Stack>
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField select size="small" label="Grant defence counsel access" value={uid} onChange={(e) => setUid(e.target.value)} sx={{ minWidth: 280 }}>
          {(attorneys.data ?? []).map((u) => <MenuItem key={u.id} value={u.id}>{u.full_name}</MenuItem>)}
        </TextField>
        <Button disabled={!uid || add.isPending} onClick={() => add.mutate()}>Grant</Button>
        <Typography variant="caption" color="text.secondary">Counsel sees approved reports and the chronology only.</Typography>
      </Stack>
    </Section>
  );
}
