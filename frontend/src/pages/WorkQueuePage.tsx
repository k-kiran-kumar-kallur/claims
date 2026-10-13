import { Box, Chip, FormControlLabel, Grid2 as Grid, InputAdornment, LinearProgress, MenuItem, Paper, Switch, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Tooltip, Typography } from "@mui/material";
import InboxIcon from "@mui/icons-material/Inbox";
import SearchIcon from "@mui/icons-material/Search";
import AlarmIcon from "@mui/icons-material/Alarm";
import ScheduleIcon from "@mui/icons-material/Schedule";
import PriorityHighIcon from "@mui/icons-material/PriorityHigh";
import AssignmentIcon from "@mui/icons-material/Assignment";
import TaskAltIcon from "@mui/icons-material/TaskAlt";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, qs } from "../api/client";
import { CHECKPOINTS, type Review } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { riskColor } from "../theme/theme";
import { EmptyState, ErrorAlert, LoadingRows, PageHeader, RelativeTime, StatTile, StatusChip } from "../components/common";

type Urgency = "overdue" | "soon" | "ok" | "none";

function due(r: Review): { label: string; color: "error" | "warning" | "default"; urgency: Urgency } {
  if (!r.due_at) return { label: "No SLA", color: "default", urgency: "none" };
  const ms = new Date(r.due_at).getTime() - Date.now();
  const h = Math.round(ms / 36e5);
  if (ms < 0) return { label: -h >= 24 ? `Overdue ${Math.round(-h / 24)}d` : `Overdue ${-h}h`, color: "error", urgency: "overdue" };
  if (h < 8) return { label: h < 1 ? "Due < 1h" : `Due in ${h}h`, color: "warning", urgency: "soon" };
  return { label: h >= 24 ? `Due in ${Math.round(h / 24)}d` : `Due in ${h}h`, color: "default", urgency: "ok" };
}

type Quick = "all" | "overdue" | "soon" | "escalated";

export default function WorkQueuePage() {
  const { user } = useAuth();
  const [checkpoint, setCheckpoint] = useState("");
  const [mine, setMine] = useState(false);
  const [status, setStatus] = useState("open");
  const [search, setSearch] = useState("");
  const [quick, setQuick] = useState<Quick>("all");
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["reviews", "queue", checkpoint, mine, status],
    queryFn: () => api.get<Review[]>(`/reviews${qs({ checkpoint, assigned_to: mine ? "me" : undefined, status })}`),
    refetchInterval: 15000,
  });
  const all = q.data ?? [];
  const stats = useMemo(() => ({
    overdue: all.filter((r) => due(r).urgency === "overdue").length,
    soon: all.filter((r) => due(r).urgency === "soon").length,
    escalated: all.filter((r) => r.escalated).length,
  }), [all]);
  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return all.filter((r) => {
      if (quick === "overdue" && due(r).urgency !== "overdue") return false;
      if (quick === "soon" && due(r).urgency !== "soon") return false;
      if (quick === "escalated" && !r.escalated) return false;
      return !term || `${r.claim_number} ${r.title} ${r.checkpoint} ${r.assigned_user_name ?? ""}`.toLowerCase().includes(term);
    });
  }, [all, quick, search]);
  const open = (r: Review) => navigate(`/claims/${r.claim_id}/${CHECKPOINTS[r.checkpoint]?.path ?? ""}`);
  const firstName = user?.full_name.split(" ")[0];
  const toggle = (k: Quick) => setQuick(quick === k ? "all" : k);

  return (
    <Box>
      <PageHeader icon={<InboxIcon />} title="My work queue"
        subtitle={status === "open" ? `Hi ${firstName} - these human-in-the-loop checkpoints are waiting for a decision. Most urgent first.` : `Human-in-the-loop checkpoints for ${user?.full_name}.`} />
      {status === "open" && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid size={{ xs: 6, md: 3 }}><StatTile label="Open tasks" value={all.length} icon={<AssignmentIcon />} onClick={() => setQuick("all")} active={quick === "all"} hint="Click a tile to filter" /></Grid>
          <Grid size={{ xs: 6, md: 3 }}><StatTile label="Overdue" value={stats.overdue} icon={<AlarmIcon />} color={stats.overdue ? "#c4320a" : undefined} onClick={() => toggle("overdue")} active={quick === "overdue"} hint="Past the SLA due time" /></Grid>
          <Grid size={{ xs: 6, md: 3 }}><StatTile label="Due within 8h" value={stats.soon} icon={<ScheduleIcon />} color={stats.soon ? "#b54708" : undefined} onClick={() => toggle("soon")} active={quick === "soon"} hint="Act on these next" /></Grid>
          <Grid size={{ xs: 6, md: 3 }}><StatTile label="Escalated" value={stats.escalated} icon={<PriorityHighIcon />} color={stats.escalated ? "#c4320a" : undefined} onClick={() => toggle("escalated")} active={quick === "escalated"} hint="Raised to a supervisor" /></Grid>
        </Grid>
      )}
      <Paper sx={{ p: 1.5, mb: 2, display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <TextField placeholder="Search claim, task or assignee" value={search} onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 260, flex: { xs: 1, md: "0 1 320px" } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} inputProps={{ "aria-label": "Search the queue" }} />
        <TextField select label="Checkpoint" value={checkpoint} onChange={(e) => setCheckpoint(e.target.value)} sx={{ minWidth: 220 }} SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }}>
          <MenuItem value="">All checkpoints</MenuItem>
          {Object.entries(CHECKPOINTS).map(([k, v]) => <MenuItem key={k} value={k}>{k} - {v.label}</MenuItem>)}
        </TextField>
        <TextField select label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setQuick("all"); }} sx={{ minWidth: 160 }}>
          <MenuItem value="open">Open</MenuItem><MenuItem value="submitted">Submitted</MenuItem><MenuItem value="cancelled">Cancelled</MenuItem>
        </TextField>
        <FormControlLabel control={<Switch checked={mine} onChange={(e) => setMine(e.target.checked)} />} label="Assigned to me" />
      </Paper>
      <ErrorAlert error={q.error} />
      <TableContainer component={Paper}>
        {q.isFetching && !q.isLoading && <LinearProgress sx={{ height: 2 }} />}
        {q.isLoading ? <LoadingRows rows={6} /> : (
          <Table size="small" aria-label="Review work queue">
            <TableHead>
              <TableRow>
                <TableCell>Checkpoint</TableCell><TableCell>Claim</TableCell><TableCell>Task</TableCell><TableCell>Assigned</TableCell>
                <TableCell>SLA</TableCell><TableCell>Risk</TableCell><TableCell>Status</TableCell><TableCell>Created</TableCell><TableCell padding="checkbox" />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => {
                const d = due(r);
                return (
                  <TableRow key={r.id} hover sx={{ cursor: "pointer", "& td:first-of-type": { borderLeft: "3px solid", borderLeftColor: d.urgency === "overdue" ? "error.main" : d.urgency === "soon" ? "warning.main" : "transparent" } }}
                    tabIndex={0} onClick={() => open(r)} onKeyDown={(e) => e.key === "Enter" && open(r)}>
                    <TableCell>
                      <Tooltip title={CHECKPOINTS[r.checkpoint]?.label ?? ""}><Chip label={r.checkpoint} color={r.priority <= 1 ? "error" : "primary"} variant={r.priority <= 2 ? "filled" : "outlined"} /></Tooltip>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>{CHECKPOINTS[r.checkpoint]?.label}</Typography>
                    </TableCell>
                    <TableCell><Typography variant="body2" fontWeight={650}>{r.claim_number}</Typography></TableCell>
                    <TableCell>{r.title}{r.escalated && <Chip label="escalated" color="error" size="small" sx={{ ml: 1 }} />}</TableCell>
                    <TableCell>{r.assigned_user_name ?? <Typography variant="caption" color="text.secondary">Any {r.assigned_role.replace(/_/g, " ")}</Typography>}{r.claimed_by_name && <Typography variant="caption" display="block" color="text.secondary">in progress: {r.claimed_by_name}</Typography>}</TableCell>
                    <TableCell><Tooltip title={r.due_at ? new Date(r.due_at).toLocaleString() : "No due date"}><Chip label={d.label} color={d.color} variant={d.urgency === "overdue" ? "filled" : "outlined"} /></Tooltip></TableCell>
                    <TableCell>{r.risk_score != null ? <Chip label={r.risk_score.toFixed(2)} color={riskColor(r.risk_score)} variant="outlined" /> : "-"}</TableCell>
                    <TableCell><StatusChip status={r.status} /></TableCell>
                    <TableCell><RelativeTime iso={r.created_at} /></TableCell>
                    <TableCell padding="checkbox"><ChevronRightIcon color="action" /></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {!q.isLoading && rows.length === 0 && (all.length > 0
          ? <EmptyState icon={<SearchIcon />} title="No tasks match these filters" hint="Clear the search or pick another tile to see more." />
          : <EmptyState icon={<TaskAltIcon />} title="Nothing waiting for you" hint="New review tasks appear here when a workflow pauses at your checkpoint. This list refreshes automatically." />)}
      </TableContainer>
    </Box>
  );
}
