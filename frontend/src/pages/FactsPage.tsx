import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid, LinearProgress, MenuItem, Paper, Stack,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Tooltip, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Fact } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { CitationList, PageWithHighlights } from "../components/CitationViewer";
import { ErrorAlert, fmtDate, ReasonDialog, Section, StatusChip } from "../components/common";
import { useFacts, usePendingReview, useSubmitReview } from "../hooks/queries";

const TYPES = ["", "mmi", "rtw", "work_status", "restriction", "diagnosis", "procedure", "imaging", "exam_finding", "symptom", "response", "treatment_plan", "medication", "mechanism", "causation", "recommendation", "impairment_rating"];

function EditDialog({ fact, onClose, onSave }: { fact: Fact | null; onClose: () => void; onSave: (value: any, label: string, reason: string) => void }) {
  const [json, setJson] = useState("");
  const [label, setLabel] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (fact) { setJson(JSON.stringify(fact.value, null, 2)); setLabel(fact.label); setReason(""); setErr(null); } }, [fact]);
  return (
    <Dialog open={!!fact} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Edit fact (creates a new version; citation retained)</DialogTitle>
      <DialogContent>
        {err && <Alert severity="error" sx={{ mb: 1 }}>{err}</Alert>}
        <TextField fullWidth label="Label" value={label} onChange={(e) => setLabel(e.target.value)} sx={{ my: 1 }} />
        <TextField fullWidth multiline minRows={6} label="Value (JSON)" value={json} onChange={(e) => setJson(e.target.value)} InputProps={{ sx: { fontFamily: "monospace", fontSize: 12 } }} />
        <TextField fullWidth multiline minRows={2} label="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} sx={{ mt: 2 }} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={reason.length < 3} onClick={() => { try { onSave(JSON.parse(json), label, reason); } catch { setErr("Value must be valid JSON"); } }}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function FactsPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const { review } = usePendingReview(claimId, "HITL-2");
  const submit = useSubmitReview(claimId);
  const [type, setType] = useState("");
  const [status, setStatus] = useState(review ? "" : "");
  const [onlyReview, setOnlyReview] = useState(true);
  const facts = useFacts(claimId, { ...(type ? { fact_type: type } : {}), ...(status ? { validation_status: status } : {}) });
  const discrepancies = useQuery({ queryKey: ["discrepancies", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/discrepancies`) });
  const [selected, setSelected] = useState<Fact | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [editing, setEditing] = useState<Fact | null>(null);
  const [rejecting, setRejecting] = useState<Fact | null>(null);
  const [resolving, setResolving] = useState<any>(null);
  const reviewIds = useMemo(() => new Set<string>(review?.payload?.fact_ids ?? []), [review]);
  const rows = useMemo(() => (facts.data ?? []).filter((f) => !review || !onlyReview || reviewIds.has(f.id) || (f.supersedes_fact_id && reviewIds.has(f.supersedes_fact_id))), [facts.data, review, onlyReview, reviewIds]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["facts", claimId] }); qc.invalidateQueries({ queryKey: ["discrepancies", claimId] }); };
  const act = useMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) => api.patch<Fact>(`/facts/${id}`, body),
    onSuccess: (f) => { refresh(); setSelected(f); },
  });
  const bulk = useMutation({ mutationFn: (ids: string[]) => api.post("/facts/bulk-action", { fact_ids: ids, action: "accept" }), onSuccess: () => { setChecked([]); refresh(); } });
  const resolve = useMutation({ mutationFn: ({ id, resolution }: { id: string; resolution: string }) => api.patch(`/discrepancies/${id}`, { resolution }), onSuccess: refresh });
  const canValidate = can("fact:validate");
  const pending = rows.filter((f) => ["needs_review", "pending"].includes(f.validation_status) || (reviewIds.has(f.id) && f.validation_status === "auto_verified"));
  const openDisc = (discrepancies.data ?? []).filter((d) => d.status === "open");

  const move = useCallback((dir: number) => {
    if (!rows.length) return;
    const i = selected ? rows.findIndex((r) => r.id === selected.id) : -1;
    setSelected(rows[Math.min(Math.max(i + dir, 0), rows.length - 1)]);
  }, [rows, selected]);

  // keyboard-first review: A accept, E edit, R reject, J/K next/previous (spec §13.1)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!canValidate || editing || rejecting || (e.target as HTMLElement)?.closest("input, textarea")) return;
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (selected && e.key.toLowerCase() === "a") act.mutate({ id: selected.id, body: { action: "accept" } }, { onSuccess: () => move(1) });
      else if (selected && e.key.toLowerCase() === "e") setEditing(selected);
      else if (selected && e.key.toLowerCase() === "r") setRejecting(selected);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [selected, canValidate, editing, rejecting, move, act]);

  const cite = selected?.citations?.[0];
  return (
    <Box>
      {review && <Alert severity="warning" sx={{ mb: 2 }}><b>HITL-2 Clinical fact validation.</b> Validate each milestone and low-confidence fact against the source (zero extrapolation). {pending.length} fact(s) and {openDisc.length} discrepancy(ies) remaining. Shortcuts: <b>J/K</b> move, <b>A</b> accept, <b>E</b> edit, <b>R</b> reject.</Alert>}
      <ErrorAlert error={act.error || bulk.error || submit.error || resolve.error} />
      <Paper sx={{ p: 1.5, mb: 2, display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <TextField select label="Fact type" value={type} onChange={(e) => setType(e.target.value)} sx={{ minWidth: 170 }}>
          {TYPES.map((t) => <MenuItem key={t} value={t}>{t ? t.replace(/_/g, " ") : "All types"}</MenuItem>)}
        </TextField>
        <TextField select label="Validation status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 170 }}>
          {["", "needs_review", "auto_verified", "validated", "edited", "rejected"].map((t) => <MenuItem key={t} value={t}>{t ? t.replace(/_/g, " ") : "Any"}</MenuItem>)}
        </TextField>
        {review && <Button onClick={() => setOnlyReview(!onlyReview)}>{onlyReview ? "Show all facts" : "Show review set only"}</Button>}
        {canValidate && checked.length > 0 && <Button variant="outlined" onClick={() => bulk.mutate(checked)}>Accept selected ({checked.length})</Button>}
        <Typography variant="body2" color="text.secondary">{rows.length} facts</Typography>
      </Paper>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 6 }}>
          <TableContainer component={Paper} sx={{ maxHeight: "70vh" }}>
            {facts.isFetching && <LinearProgress />}
            <Table size="small" stickyHeader>
              <TableHead><TableRow>
                {canValidate && <TableCell padding="checkbox"><Checkbox size="small" checked={checked.length > 0 && checked.length === pending.length} onChange={(e) => setChecked(e.target.checked ? pending.map((f) => f.id) : [])} inputProps={{ "aria-label": "Select all pending" }} /></TableCell>}
                <TableCell>Date</TableCell><TableCell>Fact</TableCell><TableCell>Conf.</TableCell><TableCell>Status</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {rows.map((f) => (
                  <TableRow key={f.id} hover selected={selected?.id === f.id} onClick={() => setSelected(f)} sx={{ cursor: "pointer" }}>
                    {canValidate && <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}><Checkbox size="small" checked={checked.includes(f.id)} onChange={(e) => setChecked(e.target.checked ? [...checked, f.id] : checked.filter((x) => x !== f.id))} /></TableCell>}
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDate(f.effective_date)}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} alignItems="center">{f.is_milestone && <Chip label="milestone" size="small" color="secondary" variant="outlined" />}<Chip label={f.fact_type.replace(/_/g, " ")} size="small" variant="outlined" /></Stack>
                      <Typography variant="body2" sx={{ mt: 0.25 }}>{f.label}</Typography>
                    </TableCell>
                    <TableCell>{Math.round(f.confidence * 100)}%</TableCell>
                    <TableCell><StatusChip status={f.validation_status} />{f.validated_by_name && <Typography variant="caption" display="block" color="text.secondary">{f.validated_by_name}</Typography>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Grid>
        <Grid size={{ xs: 12, lg: 6 }}>
          <Paper sx={{ p: 1.5, position: { lg: "sticky" }, top: 72 }}>
            {!selected ? <Typography color="text.secondary" sx={{ p: 2 }}>Select a fact to compare it side by side with its source page.</Typography> : (
              <Stack spacing={1}>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                  <Box>
                    <Typography variant="subtitle1" fontWeight={650}>{selected.label}</Typography>
                    <Typography variant="caption" color="text.secondary">{selected.extractor} v{selected.extractor_version} - effective {fmtDate(selected.effective_date)}</Typography>
                  </Box>
                  <StatusChip status={selected.validation_status} />
                </Stack>
                <Box component="pre" sx={{ m: 0, p: 1, bgcolor: "#f7f9fc", borderRadius: 1, fontSize: 12, overflow: "auto", maxHeight: 140 }}>{JSON.stringify(selected.value, null, 2)}</Box>
                {selected.validation_notes?.length > 0 && <Alert severity="info" sx={{ py: 0 }}>{selected.validation_notes.join("; ")}</Alert>}
                <Box>Source: <CitationList citations={selected.citations} claimId={claimId} /></Box>
                {canValidate && (
                  <Stack direction="row" spacing={1}>
                    <Tooltip title="A"><Button variant="contained" color="success" onClick={() => act.mutate({ id: selected.id, body: { action: "accept" } }, { onSuccess: () => move(1) })}>Accept</Button></Tooltip>
                    <Tooltip title="E"><Button variant="outlined" onClick={() => setEditing(selected)}>Edit</Button></Tooltip>
                    <Tooltip title="R"><Button variant="outlined" color="error" onClick={() => setRejecting(selected)}>Reject</Button></Tooltip>
                  </Stack>
                )}
                {cite && <PageWithHighlights docId={cite.document_id} page={cite.page_number} lineStart={cite.line_start} lineEnd={cite.line_end} />}
              </Stack>
            )}
          </Paper>
        </Grid>
      </Grid>
      <Section title={`Discrepancies (${openDisc.length} open)`}>
        {(discrepancies.data ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No cross-document discrepancies detected.</Typography>}
        {(discrepancies.data ?? []).map((d) => (
          <Stack key={d.id} direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <StatusChip status={d.status} /><Typography variant="body2" sx={{ flex: 1 }}>{d.description}{d.resolution && <Typography variant="caption" display="block" color="text.secondary">Resolution: {d.resolution}</Typography>}</Typography>
            {canValidate && d.status === "open" && <Button size="small" onClick={() => setResolving(d)}>Resolve</Button>}
          </Stack>
        ))}
      </Section>
      {review?.can_act && (
        <Stack direction="row" justifyContent="flex-end">
          <Button variant="contained" size="large" disabled={submit.isPending} onClick={() => submit.mutate({ id: review.id, body: {} })}>Submit validation ({pending.length} remaining)</Button>
        </Stack>
      )}
      <EditDialog fact={editing} onClose={() => setEditing(null)} onSave={(value, label, reason) => { act.mutate({ id: editing!.id, body: { action: "edit", value, label, reason } }); setEditing(null); }} />
      <ReasonDialog open={!!rejecting} title="Reject fact (excluded from all outputs)" onClose={() => setRejecting(null)}
        onConfirm={(reason) => { act.mutate({ id: rejecting!.id, body: { action: "reject", reason } }); setRejecting(null); }} confirmText="Reject" />
      <ReasonDialog open={!!resolving} title="Resolve discrepancy" label="Resolution" onClose={() => setResolving(null)}
        onConfirm={(resolution) => { resolve.mutate({ id: resolving.id, resolution }); setResolving(null); }} confirmText="Resolve" />
    </Box>
  );
}
