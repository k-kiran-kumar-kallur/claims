import { Box, Button, Chip, Grid2 as Grid, LinearProgress, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography, MenuItem, TextField, Dialog, DialogTitle, DialogContent, DialogActions } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, qs } from "../api/client";
import { CHECKPOINTS, type Claim, type Review } from "../api/types";
import SupervisorAccountIcon from "@mui/icons-material/SupervisorAccount";
import DescriptionIcon from "@mui/icons-material/Description";
import ScheduleIcon from "@mui/icons-material/Schedule";
import AssignmentIcon from "@mui/icons-material/Assignment";
import AlarmIcon from "@mui/icons-material/Alarm";
import RuleIcon from "@mui/icons-material/Rule";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import { ErrorAlert, LoadingRows, PageHeader, RelativeTime, Section, StatTile, StatusChip } from "../components/common";
import { useUsers } from "../hooks/queries";

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
  const re = useMutation({ mutationFn: () => api.post(`/reviews/${reassign!.id}/reassign`, { user_id: target, reason }), onSuccess: () => { setReassign(null); qc.invalidateQueries({ queryKey: ["reviews"] }); }, meta: { success: "Task reassigned" } });
  const m = metrics.data;
  const open = reviews.data ?? [];
  const escalations = open.filter((r) => r.escalated || r.checkpoint === "HITL-5");
  const workload: Record<string, number> = {};
  open.forEach((r) => { const k = r.assigned_user_name ?? r.assigned_role.replace(/_/g, " "); workload[k] = (workload[k] ?? 0) + 1; });
  const turnaround = Object.entries(m?.hitl_turnaround_hours ?? {}).map(([k, v]) => ({ checkpoint: k, hours: v }));
  return (
    <Box>
      <PageHeader icon={<SupervisorAccountIcon />} title="Supervisor console" subtitle="Escalations, sign-offs, workload, SLAs and AI quality" />
      <ErrorAlert error={metrics.error || reviews.error || re.error} />
      {metrics.isLoading ? <Paper sx={{ mb: 2 }}><LoadingRows rows={2} height={60} /></Paper> : m && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid size={{ xs: 6, md: 4, lg: 2 }}><StatTile label="Pages processed" value={m.business.pages_processed} icon={<DescriptionIcon />} /></Grid>
          <Grid size={{ xs: 6, md: 4, lg: 2 }}><StatTile label="Est. hours saved" value={m.business.estimated_hours_saved} icon={<ScheduleIcon />} color="#067647" hint="~2.5 min manual review per page" /></Grid>
          <Grid size={{ xs: 6, md: 4, lg: 2 }}><StatTile label="Open reviews" value={open.length} icon={<AssignmentIcon />} /></Grid>
          <Grid size={{ xs: 6, md: 4, lg: 2 }}><StatTile label="SLA breaches" value={m.sla_breaches} icon={<AlarmIcon />} color={m.sla_breaches ? "#c4320a" : undefined} /></Grid>
          <Grid size={{ xs: 6, md: 4, lg: 2 }}><StatTile label="Fact rejection ratio" value={`${(m.quality.validation_rejection_ratio * 100).toFixed(1)}%`} icon={<RuleIcon />}
            color={m.quality.validation_rejection_ratio > 0.15 ? "#c4320a" : undefined} hint="alert above 15%" /></Grid>
          <Grid size={{ xs: 6, md: 4, lg: 2 }}><StatTile label="Runs" value={Object.values(m.runs_by_status as Record<string, number>).reduce((a, b) => a + b, 0)} icon={<AccountTreeIcon />}
            hint={Object.entries(m.runs_by_status).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ") || "none yet"} /></Grid>
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
                <TableCell>{r.risk_score?.toFixed(2) ?? "-"}</TableCell><TableCell><RelativeTime iso={r.due_at} /></TableCell>
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
            {open.length === 0 && <Typography variant="body2" color="text.secondary">No open reviews - the team is all caught up.</Typography>}
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
            {(m?.llm ?? []).length > 0 && (
              <Table size="small" sx={{ mb: 1.5 }}>
                <TableHead><TableRow><TableCell>Model</TableCell><TableCell>Status</TableCell><TableCell align="right">Calls</TableCell><TableCell align="right">Tokens</TableCell><TableCell align="right">Cost</TableCell><TableCell align="right">Avg latency</TableCell></TableRow></TableHead>
                <TableBody>
                  {(m?.llm ?? []).map((l: any) => (
                    <TableRow key={l.model + l.status}>
                      <TableCell>{l.model}</TableCell><TableCell><StatusChip status={l.status} /></TableCell><TableCell align="right">{l.calls}</TableCell>
                      <TableCell align="right">{Number(l.tokens ?? 0).toLocaleString()}</TableCell><TableCell align="right">${l.cost_usd}</TableCell><TableCell align="right">{l.avg_latency_ms} ms</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {Object.entries(m?.quality?.human_override_ratio ?? {}).map(([k, v]) => (
              <Box key={k} sx={{ mb: 1 }}>
                <Stack direction="row" justifyContent="space-between"><Typography variant="body2">Human override ratio - {k.replace(/_/g, " ")}</Typography><Typography variant="body2" fontWeight={650}>{((v as number) * 100).toFixed(0)}%</Typography></Stack>
                <LinearProgress variant="determinate" value={Math.min(100, (v as number) * 100)} sx={{ height: 6, bgcolor: "#eef2f7" }} />
              </Box>
            ))}
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
