import { Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, downloadFile } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CitationList } from "../components/CitationViewer";
import { EmptyState, ErrorAlert, fmtDate, StatusChip } from "../components/common";
import { useClaim, useReports } from "../hooks/queries";

export function ExportBar({ claimId, types }: { claimId: string; types: { type: string; label: string }[] }) {
  const { can, hasRole } = useAuth();
  const reports = useReports(claimId);
  const claim = useClaim(claimId);
  const qc = useQueryClient();
  const [fmt, setFmt] = useState("pdf");
  const create = useMutation({ mutationFn: (type: string) => api.post(`/claims/${claimId}/reports`, { report_type: type, format: fmt }), onSuccess: () => qc.invalidateQueries({ queryKey: ["reports", claimId] }) });
  const attorney = hasRole("attorney") && !can("decision:make", "summary:edit", "fact:validate");
  if (!can("report:export")) return null;
  return (
    <Paper sx={{ p: 1.5, mb: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle2">Export</Typography>
        {!attorney && (
          <>
            <TextField select size="small" value={fmt} onChange={(e) => setFmt(e.target.value)} sx={{ width: 100 }}>
              {["pdf", "docx", "json", "html"].map((f) => <MenuItem key={f} value={f}>{f.toUpperCase()}</MenuItem>)}
            </TextField>
            {types.map((t) => <Button key={t.type} size="small" variant="outlined" onClick={() => create.mutate(t.type)}>{t.label}</Button>)}
          </>
        )}
      </Stack>
      <ErrorAlert error={create.error} />
      <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
        {(reports.data ?? []).filter((r) => types.some((t) => t.type === r.report_type)).slice(0, 8).map((r) => (
          <Chip key={r.id} icon={r.available ? <DownloadIcon /> : undefined} clickable={r.available} variant="outlined" color={r.is_approved_content ? "success" : "default"}
            label={`${r.report_type.replace(/_/g, " ")} .${r.format} ${r.is_approved_content ? "(approved)" : ""} ${r.status !== "ready" && r.status !== "approved" ? `- ${r.status}` : ""}`}
            onClick={() => r.available && downloadFile(`/reports/${r.id}/download`, `${claim.data?.claim_number}_${r.report_type}.${r.format}`)} />
        ))}
      </Stack>
    </Paper>
  );
}

export default function ChronologyPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["chronology", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/chronology`) });
  const [edit, setEdit] = useState<any>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const m = useMutation({ mutationFn: () => api.patch(`/chronology-events/${edit.id}`, form), onSuccess: () => { setEdit(null); qc.invalidateQueries({ queryKey: ["chronology", claimId] }); } });
  if (q.isLoading) return <LinearProgress />;
  const rows = q.data ?? [];
  return (
    <Box>
      <ExportBar claimId={claimId!} types={[{ type: "medical_chronology", label: "Medical chronology" }, { type: "case_progress", label: "Case progress" }, { type: "decision_provenance", label: "Decision provenance" }]} />
      <ErrorAlert error={q.error || m.error} />
      {rows.length === 0 ? <EmptyState title="Chronology not built yet" hint="Generated in Stage 6 from validated facts." /> : (
        <TableContainer component={Paper}>
          <Table size="small" aria-label="Structured medical chronology">
            <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Provider</TableCell><TableCell>Event</TableCell><TableCell>Description</TableCell><TableCell>Key findings</TableCell><TableCell>Work status</TableCell><TableCell>Source</TableCell>{can("chronology:edit") && <TableCell />}</TableRow></TableHead>
            <TableBody>
              {rows.map((e) => (
                <TableRow key={e.id} sx={{ bgcolor: e.is_turning_point ? "#f0f6ff" : undefined }}>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDate(e.event_date)}</TableCell>
                  <TableCell>{e.provider}</TableCell>
                  <TableCell>{e.event_type}{e.is_turning_point && <Chip label="turning point" size="small" color="primary" sx={{ ml: 0.5 }} />}</TableCell>
                  <TableCell>{e.description}{e.edited_by_name && <Typography variant="caption" display="block" color="primary">Edited by {e.edited_by_name}</Typography>}</TableCell>
                  <TableCell><Typography variant="caption">{e.key_findings}</Typography></TableCell>
                  <TableCell>{e.work_status ? <StatusChip status={e.work_status.replace(/ /g, "_")} label={e.work_status} /> : "-"}</TableCell>
                  <TableCell><CitationList citations={e.citations} claimId={can("document:view_phi") && can("decision:make", "fact:validate", "summary:edit", "timeline:approve", "classification:edit") ? claimId : undefined} /></TableCell>
                  {can("chronology:edit") && <TableCell><Button size="small" startIcon={<EditIcon />} onClick={() => { setEdit(e); setForm({ description: e.description, key_findings: e.key_findings ?? "", reason: "" }); }}>Edit</Button></TableCell>}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      <Dialog open={!!edit} onClose={() => setEdit(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit chronology event (versioned)</DialogTitle>
        <DialogContent>
          <TextField fullWidth multiline minRows={2} label="Description" value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })} sx={{ my: 1 }} />
          <TextField fullWidth multiline minRows={2} label="Key findings" value={form.key_findings ?? ""} onChange={(e) => setForm({ ...form, key_findings: e.target.value })} sx={{ mb: 1 }} />
          <TextField fullWidth label="Reason" value={form.reason ?? ""} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        </DialogContent>
        <DialogActions><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="contained" disabled={(form.reason ?? "").length < 3} onClick={() => m.mutate()}>Save</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
