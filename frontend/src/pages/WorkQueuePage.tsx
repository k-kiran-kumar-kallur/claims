import { Box, Chip, FormControlLabel, MenuItem, Paper, Switch, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Tooltip, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, qs } from "../api/client";
import { CHECKPOINTS, type Review } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorAlert, fmtDateTime, PageHeader, StatusChip } from "../components/common";

function due(r: Review) {
  if (!r.due_at) return { label: "-", color: "default" as const };
  const ms = new Date(r.due_at).getTime() - Date.now();
  const h = Math.round(ms / 36e5);
  if (ms < 0) return { label: `Overdue ${-h}h`, color: "error" as const };
  if (h < 8) return { label: `Due in ${h}h`, color: "warning" as const };
  return { label: `Due in ${Math.round(h / 24) || h}${h >= 24 ? "d" : "h"}`, color: "default" as const };
}

export default function WorkQueuePage() {
  const { user } = useAuth();
  const [checkpoint, setCheckpoint] = useState("");
  const [mine, setMine] = useState(false);
  const [status, setStatus] = useState("open");
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["reviews", "queue", checkpoint, mine, status],
    queryFn: () => api.get<Review[]>(`/reviews${qs({ checkpoint, assigned_to: mine ? "me" : undefined, status })}`),
    refetchInterval: 15000,
  });
  const rows = q.data ?? [];
  return (
    <Box>
      <PageHeader title="My work queue" subtitle={`Human-in-the-loop checkpoints for ${user?.full_name}. Urgent and SLA-due items first.`} />
      <Paper sx={{ p: 1.5, mb: 2, display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <TextField select label="Checkpoint" value={checkpoint} onChange={(e) => setCheckpoint(e.target.value)} sx={{ minWidth: 220 }}>
          <MenuItem value="">All checkpoints</MenuItem>
          {Object.entries(CHECKPOINTS).map(([k, v]) => <MenuItem key={k} value={k}>{k} - {v.label}</MenuItem>)}
        </TextField>
        <TextField select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 160 }}>
          <MenuItem value="open">Open</MenuItem><MenuItem value="submitted">Submitted</MenuItem><MenuItem value="cancelled">Cancelled</MenuItem>
        </TextField>
        <FormControlLabel control={<Switch checked={mine} onChange={(e) => setMine(e.target.checked)} />} label="Assigned to me" />
      </Paper>
      <ErrorAlert error={q.error} />
      <TableContainer component={Paper}>
        <Table size="small" aria-label="Review work queue">
          <TableHead>
            <TableRow>
              <TableCell>Checkpoint</TableCell><TableCell>Claim</TableCell><TableCell>Task</TableCell><TableCell>Assigned</TableCell>
              <TableCell>SLA</TableCell><TableCell>Risk</TableCell><TableCell>Status</TableCell><TableCell>Created</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => {
              const d = due(r);
              return (
                <TableRow key={r.id} hover sx={{ cursor: "pointer" }} tabIndex={0}
                  onClick={() => navigate(`/claims/${r.claim_id}/${CHECKPOINTS[r.checkpoint]?.path ?? ""}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/claims/${r.claim_id}/${CHECKPOINTS[r.checkpoint]?.path ?? ""}`)}>
                  <TableCell><Tooltip title={CHECKPOINTS[r.checkpoint]?.label ?? ""}><Chip label={r.checkpoint} color={r.priority <= 1 ? "error" : "primary"} variant={r.priority <= 2 ? "filled" : "outlined"} /></Tooltip></TableCell>
                  <TableCell><Typography variant="body2" fontWeight={600}>{r.claim_number}</Typography></TableCell>
                  <TableCell>{r.title}{r.escalated && <Chip label="escalated" color="error" size="small" sx={{ ml: 1 }} />}</TableCell>
                  <TableCell>{r.assigned_user_name ?? <Typography variant="caption" color="text.secondary">{r.assigned_role.replace(/_/g, " ")}</Typography>}{r.claimed_by_name && <Typography variant="caption" display="block" color="text.secondary">in progress: {r.claimed_by_name}</Typography>}</TableCell>
                  <TableCell><Chip label={d.label} color={d.color} variant="outlined" /></TableCell>
                  <TableCell>{r.risk_score != null ? r.risk_score.toFixed(2) : "-"}</TableCell>
                  <TableCell><StatusChip status={r.status} /></TableCell>
                  <TableCell>{fmtDateTime(r.created_at)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {!q.isLoading && rows.length === 0 && <EmptyState title="Nothing waiting for you" hint="New review tasks appear here when a workflow pauses at your checkpoint." />}
      </TableContainer>
    </Box>
  );
}
