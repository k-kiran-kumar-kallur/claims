import { Box, Button, Chip, InputAdornment, LinearProgress, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import FolderSharedIcon from "@mui/icons-material/FolderShared";
import SearchIcon from "@mui/icons-material/Search";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { api, qs } from "../api/client";
import { STAGES, type Claim } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { riskColor } from "../theme/theme";
import { EmptyState, ErrorAlert, fmtDate, LoadingRows, PageHeader, StatusChip } from "../components/common";

function StageCell({ c }: { c: Claim }) {
  const done = c.current_stage === "done";
  const idx = STAGES.findIndex((s) => s.key === c.current_stage);
  if (!done && idx < 0) return <Typography variant="body2" color="text.secondary">Not started</Typography>;
  const step = done ? STAGES.length : idx + 1;
  return (
    <Tooltip title={done ? "All 7 stages complete" : `Stage ${step} of ${STAGES.length}`}>
      <Box sx={{ minWidth: 130 }}>
        <Typography variant="body2">{done ? "Complete" : STAGES[idx].label}</Typography>
        <LinearProgress variant="determinate" value={(step / STAGES.length) * 100} color={done ? "success" : "primary"} sx={{ mt: 0.5, height: 4 }} />
      </Box>
    </Tooltip>
  );
}

export default function ClaimsListPage() {
  const { can } = useAuth();
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [complexity, setComplexity] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const navigate = useNavigate();
  useEffect(() => { const id = window.setTimeout(() => { setQ(input.trim()); setPage(0); }, 300); return () => window.clearTimeout(id); }, [input]);
  const query = useQuery({
    queryKey: ["claims", q, status, complexity, page, pageSize],
    queryFn: () => api.getEnv<Claim[]>(`/claims${qs({ q, status, complexity, page: page + 1, page_size: pageSize })}`),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.data ?? [];
  const filtered = !!(q || status || complexity);
  return (
    <Box>
      <PageHeader icon={<FolderSharedIcon />} title="Claims" subtitle="Status, risk, complexity, workflow stage and pending reviews"
        actions={can("claim:create") && <Button component={RouterLink} to="/claims/new" variant="contained" startIcon={<AddIcon />}>New claim</Button>} />
      <Paper sx={{ p: 1.5, mb: 2, display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <TextField label="Search claim # or employer" value={input} onChange={(e) => setInput(e.target.value)} sx={{ minWidth: 280, flex: { xs: 1, md: "0 1 340px" } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
        <TextField select label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} sx={{ minWidth: 150 }} SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }}>
          <MenuItem value="">Any</MenuItem>{["open", "in_review", "decided", "closed"].map((s) => <MenuItem key={s} value={s}>{s.replace("_", " ")}</MenuItem>)}
        </TextField>
        <TextField select label="Complexity" value={complexity} onChange={(e) => { setComplexity(e.target.value); setPage(0); }} sx={{ minWidth: 150 }} SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }}>
          <MenuItem value="">Any</MenuItem>{["routine", "complex", "exceptional"].map((s) => <MenuItem key={s} value={s} sx={{ textTransform: "capitalize" }}>{s}</MenuItem>)}
        </TextField>
        {filtered && <Button onClick={() => { setInput(""); setStatus(""); setComplexity(""); }}>Clear filters</Button>}
        <Box sx={{ flex: 1 }} />
        {query.data && <Typography variant="body2" color="text.secondary">{Number(query.data.meta?.total ?? 0)} claim{Number(query.data.meta?.total) === 1 ? "" : "s"}</Typography>}
      </Paper>
      <ErrorAlert error={query.error} />
      <TableContainer component={Paper}>
        {query.isFetching && !query.isLoading && <LinearProgress sx={{ height: 2 }} />}
        {query.isLoading ? <LoadingRows rows={8} /> : (
          <Table size="small" aria-label="Claims">
            <TableHead>
              <TableRow>
                <TableCell>Claim #</TableCell><TableCell>Claimant</TableCell><TableCell>DOI</TableCell><TableCell>Employer</TableCell>
                <TableCell>Stage</TableCell><TableCell>Run</TableCell><TableCell>Risk</TableCell><TableCell>Pending reviews</TableCell><TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id} hover sx={{ cursor: "pointer" }} onClick={() => navigate(`/claims/${c.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/claims/${c.id}`)}>
                  <TableCell>
                    <Stack direction="row" spacing={0.75} alignItems="center">
                      <Typography variant="body2" fontWeight={650} color="primary.main">{c.claim_number}</Typography>
                      {c.is_synthetic && <Chip label="synthetic" size="small" variant="outlined" sx={{ height: 18, fontSize: 10.5 }} />}
                    </Stack>
                  </TableCell>
                  <TableCell>{c.claimant}</TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDate(c.date_of_injury)}</TableCell>
                  <TableCell>{c.employer_name ?? "-"}</TableCell>
                  <TableCell><StageCell c={c} /></TableCell>
                  <TableCell>{c.latest_run ? <StatusChip status={c.latest_run.status} /> : <Typography variant="body2" color="text.secondary">-</Typography>}</TableCell>
                  <TableCell>{c.risk_score != null ? <Chip label={`${c.risk_score.toFixed(2)} ${c.complexity ?? ""}`} color={riskColor(c.risk_score)} variant="outlined" /> : "-"}</TableCell>
                  <TableCell>{c.pending_reviews ? <Chip label={c.pending_reviews} color="warning" /> : <Typography variant="body2" color="text.secondary">-</Typography>}</TableCell>
                  <TableCell><StatusChip status={c.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {!query.isLoading && rows.length === 0 && (filtered
          ? <EmptyState icon={<SearchIcon />} title="No claims match your filters" action={<Button onClick={() => { setInput(""); setStatus(""); setComplexity(""); }}>Clear filters</Button>} />
          : <EmptyState icon={<FolderSharedIcon />} title="No claims yet" hint="Create a claim and upload its medical-record package to begin."
              action={can("claim:create") && <Button component={RouterLink} to="/claims/new" variant="contained" startIcon={<AddIcon />}>New claim</Button>} />)}
        <TablePagination component="div" count={Number(query.data?.meta?.total ?? 0)} page={page} onPageChange={(_, p) => setPage(p)}
          rowsPerPage={pageSize} onRowsPerPageChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }} rowsPerPageOptions={[25, 50, 100]} />
      </TableContainer>
    </Box>
  );
}
