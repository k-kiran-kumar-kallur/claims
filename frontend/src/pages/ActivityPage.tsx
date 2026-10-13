import { Alert, Box, Chip, Collapse, Grid2 as Grid, IconButton, LinearProgress, List, ListItemButton, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import HistoryIcon from "@mui/icons-material/History";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { ActivityLog } from "../components/ActivityLog";
import { EmptyState, ErrorAlert, fmtDateTime, fmtDuration, LoadingRows, RelativeTime, Section, StatusChip } from "../components/common";
import { nodeName } from "../components/runLog";
import { useRuns } from "../hooks/queries";
import { useRunEvents } from "../hooks/useRunEvents";

const ACTIVE = ["queued", "running", "retrying", "awaiting_human", "awaiting_documents"];

function runDuration(r: any): number | null {
  const start = r.started_at ?? r.created_at;
  if (!start) return null;
  const end = r.completed_at ? new Date(r.completed_at).getTime() : ACTIVE.includes(r.status) ? Date.now() : null;
  return end ? end - new Date(start).getTime() : null;
}

function StepsTable({ runId }: { runId: string }) {
  const q = useQuery({ queryKey: ["steps", runId], queryFn: () => api.get<any[]>(`/runs/${runId}/steps`), refetchInterval: 10_000 });
  const [open, setOpen] = useState<string | null>(null);
  const rows = q.data ?? [];
  const max = Math.max(1, ...rows.map((s) => s.duration_ms ?? 0));
  const totals = useMemo(() => rows.reduce((t, s) => ({
    ms: t.ms + (s.duration_ms ?? 0), llm: t.llm + (s.llm_calls?.count ?? 0), tokens: t.tokens + (s.llm_calls?.tokens ?? 0),
    cost: t.cost + (s.llm_calls?.cost_usd ?? 0), failed: t.failed + (s.status === "failed" ? 1 : 0),
  }), { ms: 0, llm: 0, tokens: 0, cost: 0, failed: 0 }), [rows]);
  if (q.isLoading) return <LoadingRows rows={6} height={30} />;
  if (q.error) return <ErrorAlert error={q.error} />;
  if (rows.length === 0) return <Typography variant="body2" color="text.secondary">No agent steps recorded yet.</Typography>;
  return (
    <>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        <Chip label={`${rows.length} steps`} />
        <Chip label={`Compute time ${fmtDuration(totals.ms)}`} variant="outlined" />
        <Chip label={`${totals.llm} LLM calls · ${totals.tokens.toLocaleString()} tokens`} variant="outlined" />
        <Chip label={`Cost $${totals.cost.toFixed(4)}`} variant="outlined" />
        {totals.failed > 0 && <Chip color="error" label={`${totals.failed} failed attempt${totals.failed > 1 ? "s" : ""}`} />}
      </Stack>
      <TableContainer sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, maxHeight: 520 }}>
        <Table size="small" stickyHeader aria-label="Agent steps">
          <TableHead>
            <TableRow><TableCell padding="checkbox" /><TableCell>Started</TableCell><TableCell>Agent</TableCell><TableCell>Status</TableCell><TableCell sx={{ minWidth: 180 }}>Duration</TableCell><TableCell>LLM</TableCell><TableCell>Tools</TableCell></TableRow>
          </TableHead>
          <TableBody>
            {rows.map((s) => {
              const hasDetail = !!s.error_message || (!!s.output && Object.keys(s.output).length > 0);
              return (
                <Fragment key={s.id}>
                  <TableRow hover sx={{ bgcolor: s.status === "failed" ? "error.light" : undefined }}>
                    <TableCell padding="checkbox">
                      {hasDetail && <IconButton size="small" aria-label="Show step details" onClick={() => setOpen(open === s.id ? null : s.id)}
                        sx={{ transform: open === s.id ? "rotate(180deg)" : undefined, transition: "transform .15s" }}><ExpandMoreIcon fontSize="small" /></IconButton>}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}><Tooltip title={fmtDateTime(s.started_at)}><span>{s.started_at ? new Date(s.started_at).toLocaleTimeString() : "-"}</span></Tooltip></TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>{nodeName(s.node)}</Typography>
                      <Typography variant="caption" color="text.secondary">{s.stage?.replace(/_/g, " ")}{s.attempt > 1 ? ` · attempt ${s.attempt}` : ""}</Typography>
                    </TableCell>
                    <TableCell><StatusChip status={s.status === "started" ? "running" : s.status} label={s.status === "interrupted" ? "paused for review" : undefined} /></TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Box sx={{ flex: 1, height: 6, bgcolor: "#eef2f7", borderRadius: 3, overflow: "hidden" }}>
                          <Box sx={{ width: `${((s.duration_ms ?? 0) / max) * 100}%`, height: "100%", bgcolor: s.status === "failed" ? "error.main" : "primary.main" }} />
                        </Box>
                        <Typography variant="caption" sx={{ width: 60, textAlign: "right" }}>{fmtDuration(s.duration_ms)}</Typography>
                      </Stack>
                    </TableCell>
                    <TableCell>{s.llm_calls ? <Tooltip title={`${s.llm_calls.tokens?.toLocaleString() ?? 0} tokens · $${s.llm_calls.cost_usd}`}><span>{s.llm_calls.count} call{s.llm_calls.count > 1 ? "s" : ""}</span></Tooltip> : "-"}</TableCell>
                    <TableCell>{s.tool_calls ? `${s.tool_calls.count}` : "-"}</TableCell>
                  </TableRow>
                  {open === s.id && (
                    <TableRow>
                      <TableCell colSpan={7} sx={{ bgcolor: "#fafbfd" }}>
                        <Collapse in>
                          {s.error_message && <Alert severity="error" sx={{ mb: 1 }}><b>{s.error_type}</b>: {s.error_message}</Alert>}
                          {s.output && Object.keys(s.output).length > 0 && (
                            <Box component="pre" sx={{ m: 0, p: 1.25, fontSize: 11.5, bgcolor: "#0f172a", color: "#e2e8f0", borderRadius: 1.5, overflow: "auto", maxHeight: 240 }}>
                              {JSON.stringify(s.output, null, 2)}
                            </Box>
                          )}
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </>
  );
}

export default function ActivityPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const runs = useRuns(claimId);
  const [selected, setSelected] = useState<string | null>(null);
  const list = runs.data ?? [];
  useEffect(() => { if (!selected && list.length) setSelected(list[0].id); }, [list, selected]);
  const run = list.find((r) => r.id === selected);
  const live = !!run && ACTIVE.includes(run.status);
  const { events, connected, ended } = useRunEvents(run?.id, claimId, live);

  if (runs.isLoading) return <LoadingRows rows={4} height={48} />;
  if (runs.error) return <ErrorAlert error={runs.error} />;
  if (list.length === 0) return <Section><EmptyState icon={<HistoryIcon />} title="No workflow runs yet" hint="Start processing from the Dashboard tab. Every agent step, tool call, retry and human checkpoint will be logged here." /></Section>;

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 4, lg: 3 }}>
        <Section title={`Runs (${list.length})`} dense>
          <List dense disablePadding aria-label="Workflow runs">
            {list.map((r, i) => (
              <ListItemButton key={r.id} selected={r.id === selected} onClick={() => setSelected(r.id)}
                sx={{ borderRadius: 1.5, mb: 0.5, display: "block", border: "1px solid", borderColor: r.id === selected ? "primary.main" : "transparent" }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                  <Typography variant="body2" fontWeight={650}>Run #{list.length - i}{r.mode === "incremental" ? " · incremental" : ""}</Typography>
                  <StatusChip status={r.status} />
                </Stack>
                <Typography variant="caption" color="text.secondary" component="div">
                  <RelativeTime iso={r.started_at ?? r.created_at} variant="caption" /> · {fmtDuration(runDuration(r))}
                  {r.total_tokens ? ` · ${Number(r.total_tokens).toLocaleString()} tokens` : ""}
                </Typography>
              </ListItemButton>
            ))}
          </List>
        </Section>
      </Grid>
      <Grid size={{ xs: 12, md: 8, lg: 9 }}>
        {run && (
          <>
            {run.status === "failed" && <Alert severity="error" sx={{ mb: 2 }}><b>This run failed.</b> {run.error}</Alert>}
            <Section title="Activity log" actions={
              <Stack direction="row" spacing={1} alignItems="center">
                {run.llm_mode && <Chip variant="outlined" label={run.llm_mode === "rules" ? "Offline rules mode" : `LLM: ${run.llm_mode}`} />}
                <Typography variant="caption" color="text.secondary">Started {fmtDateTime(run.started_at ?? run.created_at)}</Typography>
              </Stack>}>
              {!ended && !connected && events.length === 0 && <LinearProgress sx={{ mb: 1 }} />}
              <ActivityLog events={events} live={live && connected} loading={!ended && events.length === 0} fileName={`run-${run.id.slice(0, 8)}`} />
            </Section>
            {can("audit:view", "run:manage") && (
              <Section title="Agent steps" actions={<Typography variant="caption" color="text.secondary">Timing, retries, LLM usage and errors per agent</Typography>}>
                <StepsTable runId={run.id} />
              </Section>
            )}
          </>
        )}
      </Grid>
    </Grid>
  );
}
