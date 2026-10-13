import { Alert, Box, Chip, Collapse, IconButton, InputAdornment, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PersonIcon from "@mui/icons-material/Person";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import SettingsIcon from "@mui/icons-material/Settings";
import SearchIcon from "@mui/icons-material/Search";
import VerifiedIcon from "@mui/icons-material/Verified";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { useParams } from "react-router-dom";
import { api, qs } from "../api/client";
import { EmptyState, ErrorAlert, fmtDateTime, fmtRelative, LoadingRows } from "../components/common";

const ACTOR_ICON: Record<string, JSX.Element> = { user: <PersonIcon />, agent: <SmartToyIcon />, system: <SettingsIcon /> };

/** Colour an audit action by its verb so failures, approvals and PHI access stand out. */
function actionColor(action: string): "error" | "warning" | "success" | "info" | "default" {
  if (/fail|reject|breach|broken|cancel|delete/.test(action)) return "error";
  if (/phi\.view|export|override|role\.|config|reassign/.test(action)) return "warning";
  if (/approve|complete|validate|confirm|seal|sign|accept|create|grant/.test(action)) return "success";
  if (/run\.|review\.|login|logout/.test(action)) return "info";
  return "default";
}

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

export function AuditTable({ rows: allRows, total, page, setPage, pageSize, setPageSize, showClaim }: any) {
  const [open, setOpen] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [actor, setActor] = useState("");
  const term = search.trim().toLowerCase();
  const rows = (allRows as any[]).filter((a) => (!actor || a.actor_type === actor)
    && (!term || `${a.action} ${a.actor_name ?? ""} ${a.entity_type ?? ""} ${a.entity_id ?? ""}`.toLowerCase().includes(term)));
  return (
    <TableContainer component={Paper}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ p: 1.5, borderBottom: "1px solid", borderColor: "divider" }}>
        <TextField placeholder="Filter this page by action, actor or entity" value={search} onChange={(e) => setSearch(e.target.value)} sx={{ flex: 1, maxWidth: 420 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} inputProps={{ "aria-label": "Filter audit entries" }} />
        <TextField select label="Actor" value={actor} onChange={(e) => setActor(e.target.value)} sx={{ minWidth: 150 }} SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }}>
          <MenuItem value="">Everyone</MenuItem><MenuItem value="user">People</MenuItem><MenuItem value="agent">AI agents</MenuItem><MenuItem value="system">System</MenuItem>
        </TextField>
      </Stack>
      <Table size="small">
        <TableHead><TableRow><TableCell padding="checkbox" /><TableCell>When</TableCell><TableCell>Actor</TableCell><TableCell>Action</TableCell><TableCell>Entity</TableCell>{showClaim && <TableCell>Claim</TableCell>}<TableCell>Hash</TableCell></TableRow></TableHead>
        <TableBody>
          {rows.map((a: any) => (
            <Fragment key={a.id}>
              <TableRow hover sx={{ cursor: a.before || a.after ? "pointer" : undefined }} onClick={() => (a.before || a.after) && setOpen(open === a.id ? null : a.id)}>
                <TableCell padding="checkbox">{(a.before || a.after) && <IconButton size="small" aria-label="Show details" onClick={(e) => { e.stopPropagation(); setOpen(open === a.id ? null : a.id); }}
                  sx={{ transform: open === a.id ? "rotate(180deg)" : undefined, transition: "transform .15s" }}><ExpandMoreIcon fontSize="small" /></IconButton>}</TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  <Typography variant="body2">{fmtRelative(a.ts)}</Typography>
                  <Typography variant="caption" color="text.secondary">{fmtDateTime(a.ts)}</Typography>
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.75} alignItems="center">
                    <Tooltip title={a.actor_type}><Box sx={{ display: "flex", color: "text.secondary", "& svg": { fontSize: 18 } }}>{ACTOR_ICON[a.actor_type] ?? <PersonIcon />}</Box></Tooltip>
                    <Typography variant="body2">{a.actor_name ?? a.actor_type}</Typography>
                  </Stack>
                </TableCell>
                <TableCell><Chip label={a.action} color={actionColor(a.action)} variant="outlined" sx={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11.5 }} /></TableCell>
                <TableCell>{a.entity_type?.replace(/_/g, " ")}</TableCell>
                {showClaim && <TableCell><Typography variant="caption">{a.claim_id?.slice(0, 8)}</Typography></TableCell>}
                <TableCell><Tooltip title={a.hash ?? ""}><Typography variant="caption" fontFamily="monospace" color="text.secondary">{a.hash?.slice(0, 12)}{a.hash?.length > 12 ? "..." : ""}</Typography></Tooltip></TableCell>
              </TableRow>
              {open === a.id && <TableRow><TableCell colSpan={7}><Collapse in><Diff before={a.before} after={a.after} /></Collapse></TableCell></TableRow>}
            </Fragment>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && <EmptyState icon={<SearchIcon />} title={allRows.length ? "No entries on this page match the filter" : "No audit entries yet"} />}
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
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }} alignItems={{ sm: "center" }}>
        <Typography variant="body2" color="text.secondary">Append-only, hash-chained audit trail: who did what, when, with before/after values. Click a row to see what changed.</Typography>
        {verify.data && <Chip icon={verify.data.valid ? <VerifiedIcon /> : undefined} color={verify.data.valid ? "success" : "error"} label={verify.data.valid ? `Chain verified (${verify.data.checked} entries)` : `Chain broken at ${verify.data.broken_at_id}`} />}
      </Stack>
      {verify.data && !verify.data.valid && <Alert severity="error" sx={{ mb: 2 }}>Audit chain integrity check failed: {verify.data.reason}</Alert>}
      <ErrorAlert error={q.error} />
      {q.isLoading ? <Paper><LoadingRows rows={8} /></Paper> : <AuditTable rows={q.data?.data ?? []} total={Number(q.data?.meta?.total ?? 0)} page={page} setPage={setPage} pageSize={pageSize} setPageSize={setPageSize} />}
    </Box>
  );
}
