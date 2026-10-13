import { Box, Button, Chip, Grid2 as Grid, LinearProgress, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography, MenuItem, TextField, Dialog, DialogTitle, DialogContent, DialogActions } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, qs } from "../api/client";
import { CHECKPOINTS, type Claim, type Review } from "../api/types";
import { ErrorAlert, fmtDateTime, PageHeader, Section, StatusChip } from "../components/common";
import { useUsers } from "../hooks/queries";

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h5" sx={{ mt: 0.5 }}>{value}</Typography>
      {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
    </Paper>
  );
}

export default function SupervisorPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api.get<any>("/metrics/summary"), refetchInterval: 30000 });
  const reviews = useQuery({ queryKey: ["reviews", "all-open"], queryFn: () => api.get<Review[]>(`/reviews${qs({ status: "open" })}`), refetchInterval: 15000 });
  const claims = useQuery({ queryKey: ["claims", "high-risk"], queryFn: () => api.get<Claim[]>(`/claims${qs({ risk_min: 0.7, page_size: 50 })}`) });
  const users = useUsers();
  const [reassign, setReassign] = useState<Review | null>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const re = useMutation({ mutationFn: () => api.post(`/reviews/${reassign!.id}/reassign`, { user_id: target, reason }), onSuccess: () => { setReassign(null); qc.invalidateQueries({ queryKey: ["reviews"] }); } });
  const m = metrics.data;
  const open = reviews.data ?? [];
  const escalations = open.filter((r) => r.escalated || r.checkpoint === "HITL-5");
  const workload: Record<string, number> = {};
  open.forEach((r) => { const k = r.assigned_user_name ?? r.assigned_role.replace(/_/g, " "); workload[k] = (workload[k] ?? 0) + 1; });
  const turnaround = Object.entries(m?.hitl_turnaround_hours ?? {}).map(([k, v]) => ({ checkpoint: k, hours: v }));
  return (
    <Box>
      <PageHeader title="Supervisor console" subtitle="Escalations, sign-offs, workload, SLAs and AI quality" />
      <ErrorAlert error={metrics.error || reviews.error || re.error} />
      {metrics.isLoading ? <LinearProgress /> : m && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid size={{ xs: 6, md: 2 }}><Stat label="Pages processed" value={m.business.pages_processed} /></Grid>
          <Grid size={{ xs: 6, md: 2 }}><Stat label="Est. hours saved" value={m.business.estimated_hours_saved} hint="~2.5 min manual review per page" /></Grid>
          <Grid size={{ xs: 6, md: 2 }}><Stat label="Open reviews" value={open.length} /></Grid>
          <Grid size={{ xs: 6, md: 2 }}><Stat label="SLA breaches" value={m.sla_breaches} /></Grid>
          <Grid size={{ xs: 6, md: 2 }}><Stat label="Fact rejection ratio" value={`${(m.quality.validation_rejection_ratio * 100).toFixed(1)}%`} hint="alert above 15%" /></Grid>
          <Grid size={{ xs: 6, md: 2 }}><Stat label="Runs" value={Object.entries(m.runs_by_status).map(([k, v]) => `${v} ${k}`).join(", ") || "0"} /></Grid>
        </Grid>
      )}
      <Section title={`Escalation queue and sign-offs (${escalations.length})`}>
        <Table size="small">
          <TableHead><TableRow><TableCell>Checkpoint</TableCell><TableCell>Claim</TableCell><TableCell>Task</TableCell><TableCell>Risk</TableCell><TableCell>Due</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>
            {escalations.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell><Chip label={r.checkpoint} color={r.checkpoint === "HITL-5" ? "primary" : "error"} /></TableCell>
                <TableCell>{r.claim_number}</TableCell><TableCell>{r.title}{r.escalated && <Chip size="small" color="error" label="SLA breach" sx={{ ml: 1 }} />}</TableCell>
                <TableCell>{r.risk_score?.toFixed(2) ?? "-"}</TableCell><TableCell>{fmtDateTime(r.due_at)}</TableCell>
                <TableCell><Button size="small" onClick={() => navigate(`/claims/${r.claim_id}/${CHECKPOINTS[r.checkpoint]?.path ?? ""}`)}>Open</Button></TableCell>
              </TableRow>
            ))}
            {escalations.length === 0 && <TableRow><TableCell colSpan={6}><Typography variant="body2" color="text.secondary">No escalations.</Typography></TableCell></TableRow>}
          </TableBody>
        </Table>
      </Section>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Team workload (open reviews)">
            {Object.entries(workload).map(([k, v]) => <Stack key={k} direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}><Typography variant="body2">{k}</Typography><Chip size="small" label={v} /></Stack>)}
            {open.length > 0 && <Typography variant="subtitle2" sx={{ mt: 2 }}>Reassign</Typography>}
            {open.slice(0, 12).map((r) => (
              <Stack key={r.id} direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                <Chip size="small" label={r.checkpoint} /><Typography variant="caption" sx={{ flex: 1 }}>{r.claim_number} - {r.title}</Typography>
                <Button size="small" onClick={() => { setReassign(r); setTarget(""); setReason(""); }}>Reassign</Button>
              </Stack>
            ))}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="HITL turnaround (hours, submitted reviews)">
            {turnaround.length === 0 ? <Typography variant="body2" color="text.secondary">No completed reviews yet.</Typography> : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={turnaround}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="checkpoint" fontSize={11} /><YAxis fontSize={11} /><Tooltip /><Bar dataKey="hours" fill="#1f4f8f" /></BarChart>
              </ResponsiveContainer>
            )}
          </Section>
          <Section title="AI quality and cost">
            {(m?.llm ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No LLM calls (rules mode or no runs yet).</Typography>}
            {(m?.llm ?? []).map((l: any) => <Typography key={l.model + l.status} variant="body2">{l.model} ({l.status}): {l.calls} calls, {l.tokens} tokens, ${l.cost_usd}, avg {l.avg_latency_ms} ms</Typography>)}
            {Object.entries(m?.quality?.human_override_ratio ?? {}).map(([k, v]) => <Typography key={k} variant="body2">Override ratio {k.replace(/_/g, " ")}: {((v as number) * 100).toFixed(0)}%</Typography>)}
          </Section>
        </Grid>
      </Grid>
      <Section title="High-risk / complex claims">
        <Table size="small">
          <TableHead><TableRow><TableCell>Claim</TableCell><TableCell>Claimant</TableCell><TableCell>Risk</TableCell><TableCell>Stage</TableCell><TableCell>Run</TableCell></TableRow></TableHead>
          <TableBody>
            {(claims.data ?? []).map((c) => (
              <TableRow key={c.id} hover sx={{ cursor: "pointer" }} onClick={() => navigate(`/claims/${c.id}`)}>
                <TableCell>{c.claim_number}</TableCell><TableCell>{c.claimant}</TableCell><TableCell>{c.risk_score?.toFixed(2)} {c.complexity}</TableCell>
                <TableCell>{c.current_stage}</TableCell><TableCell><StatusChip status={c.latest_run?.status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>
      <Dialog open={!!reassign} onClose={() => setReassign(null)} fullWidth maxWidth="sm">
        <DialogTitle>Reassign {reassign?.checkpoint}</DialogTitle>
        <DialogContent>
          <TextField select fullWidth label="Assign to" value={target} onChange={(e) => setTarget(e.target.value)} sx={{ my: 1 }}>
            {(users.data ?? []).map((u) => <MenuItem key={u.id} value={u.id}>{u.full_name} ({u.roles.join(", ")})</MenuItem>)}
          </TextField>
          <TextField fullWidth label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </DialogContent>
        <DialogActions><Button onClick={() => setReassign(null)}>Cancel</Button><Button variant="contained" disabled={!target || reason.length < 3} onClick={() => re.mutate()}>Reassign</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
