import { Box, Button, Chip, LinearProgress, MenuItem, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { api, qs } from "../api/client";
import { STAGES, type Claim } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorAlert, fmtDate, PageHeader, StatusChip } from "../components/common";

export default function ClaimsListPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [complexity, setComplexity] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["claims", q, status, complexity, page, pageSize],
    queryFn: () => api.getEnv<Claim[]>(`/claims${qs({ q, status, complexity, page: page + 1, page_size: pageSize })}`),
  });
  const rows = query.data?.data ?? [];
  return (
    <Box>
      <PageHeader title="Claims" subtitle="Status, risk, complexity, workflow stage and pending reviews"
        actions={can("claim:create") && <Button component={RouterLink} to="/claims/new" variant="contained" startIcon={<AddIcon />}>New claim</Button>} />
      <Paper sx={{ p: 1.5, mb: 2, display: "flex", gap: 2, flexWrap: "wrap" }}>
        <TextField label="Search claim # or employer" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} sx={{ minWidth: 260 }} />
        <TextField select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">Any</MenuItem>{["open", "in_review", "decided", "closed"].map((s) => <MenuItem key={s} value={s}>{s.replace("_", " ")}</MenuItem>)}
        </TextField>
        <TextField select label="Complexity" value={complexity} onChange={(e) => setComplexity(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">Any</MenuItem>{["routine", "complex", "exceptional"].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
        </TextField>
      </Paper>
      <ErrorAlert error={query.error} />
      <TableContainer component={Paper}>
        {query.isFetching && <LinearProgress />}
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
                <TableCell><Typography variant="body2" fontWeight={650}>{c.claim_number}</Typography>{c.is_synthetic && <Chip label="synthetic" size="small" variant="outlined" />}</TableCell>
                <TableCell>{c.claimant}</TableCell>
                <TableCell>{fmtDate(c.date_of_injury)}</TableCell>
                <TableCell>{c.employer_name}</TableCell>
                <TableCell>{STAGES.find((s) => s.key === c.current_stage)?.label ?? (c.current_stage === "done" ? "Complete" : "-")}</TableCell>
                <TableCell><StatusChip status={c.latest_run?.status} /></TableCell>
                <TableCell>{c.risk_score != null ? <Chip label={`${c.risk_score.toFixed(2)} ${c.complexity ?? ""}`} color={c.risk_score >= 0.7 ? "error" : c.risk_score >= 0.4 ? "warning" : "success"} variant="outlined" /> : "-"}</TableCell>
                <TableCell>{c.pending_reviews || "-"}</TableCell>
                <TableCell><StatusChip status={c.status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!query.isLoading && rows.length === 0 && <EmptyState title="No claims found" hint="Create a claim and upload its medical-record package to begin." />}
        <TablePagination component="div" count={Number(query.data?.meta?.total ?? 0)} page={page} onPageChange={(_, p) => setPage(p)}
          rowsPerPage={pageSize} onRowsPerPageChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }} rowsPerPageOptions={[25, 50, 100]} />
      </TableContainer>
    </Box>
  );
}
