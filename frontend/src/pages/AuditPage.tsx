import { Alert, Box, Chip, Collapse, IconButton, LinearProgress, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { useParams } from "react-router-dom";
import { api, qs } from "../api/client";
import { ErrorAlert, fmtDateTime } from "../components/common";

function Diff({ before, after }: { before: any; after: any }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 1 }}>
      {[["Before", before, "#fef3f2"], ["After", after, "#ecfdf3"]].map(([label, v, bg]) => (
        <Box key={label as string}><Typography variant="caption">{label as string}</Typography>
          <Box component="pre" sx={{ m: 0, p: 1, bgcolor: bg as string, borderRadius: 1, fontSize: 11, maxHeight: 220, overflow: "auto", whiteSpace: "pre-wrap" }}>{v ? JSON.stringify(v, null, 2) : "-"}</Box></Box>
      ))}
    </Box>
  );
}

export function AuditTable({ rows, total, page, setPage, pageSize, setPageSize, showClaim }: any) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <TableContainer component={Paper}>
      <Table size="small">
        <TableHead><TableRow><TableCell /><TableCell>When</TableCell><TableCell>Actor</TableCell><TableCell>Action</TableCell><TableCell>Entity</TableCell>{showClaim && <TableCell>Claim</TableCell>}<TableCell>Hash</TableCell></TableRow></TableHead>
        <TableBody>
          {rows.map((a: any) => (
            <Fragment key={a.id}>
              <TableRow hover>
                <TableCell padding="checkbox">{(a.before || a.after) && <IconButton size="small" aria-label="Show details" onClick={() => setOpen(open === a.id ? null : a.id)}><ExpandMoreIcon fontSize="small" /></IconButton>}</TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDateTime(a.ts)}</TableCell>
                <TableCell><Chip size="small" label={a.actor_type} variant="outlined" sx={{ mr: 0.5 }} />{a.actor_name}</TableCell>
                <TableCell><Typography variant="body2" fontFamily="monospace">{a.action}</Typography></TableCell>
                <TableCell>{a.entity_type}</TableCell>
                {showClaim && <TableCell><Typography variant="caption">{a.claim_id?.slice(0, 8)}</Typography></TableCell>}
                <TableCell><Typography variant="caption" fontFamily="monospace">{a.hash}</Typography></TableCell>
              </TableRow>
              {open === a.id && <TableRow><TableCell colSpan={7}><Collapse in><Diff before={a.before} after={a.after} /></Collapse></TableCell></TableRow>}
            </Fragment>
          ))}
        </TableBody>
      </Table>
      <TablePagination component="div" count={total} page={page} onPageChange={(_: any, p: number) => setPage(p)} rowsPerPage={pageSize}
        onRowsPerPageChange={(e: any) => { setPageSize(Number(e.target.value)); setPage(0); }} rowsPerPageOptions={[50, 100, 250]} />
    </TableContainer>
  );
}

export default function AuditPage() {
  const { claimId } = useParams();
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const q = useQuery({ queryKey: ["audit", claimId, page, pageSize], queryFn: () => api.getEnv<any[]>(`/claims/${claimId}/audit${qs({ page: page + 1, page_size: pageSize })}`) });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: () => api.get<any>("/audit/verify") });
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }} alignItems="center">
        <Typography variant="body2" color="text.secondary">Append-only, hash-chained audit trail: who did what, when, with before/after values.</Typography>
        {verify.data && <Chip color={verify.data.valid ? "success" : "error"} label={verify.data.valid ? `Chain verified (${verify.data.checked} entries)` : `Chain broken at ${verify.data.broken_at_id}`} />}
      </Stack>
      {verify.data && !verify.data.valid && <Alert severity="error" sx={{ mb: 2 }}>Audit chain integrity check failed: {verify.data.reason}</Alert>}
      <ErrorAlert error={q.error} />
      {q.isLoading ? <LinearProgress /> : <AuditTable rows={q.data?.data ?? []} total={Number(q.data?.meta?.total ?? 0)} page={page} setPage={setPage} pageSize={pageSize} setPageSize={setPageSize} />}
    </Box>
  );
}
