import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, InputAdornment, LinearProgress, List, ListItemButton, ListItemText,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, qs } from "../api/client";
import { DOC_TYPES, type DocumentItem } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ErrorAlert, fmtDate, Section, StatusChip } from "../components/common";
import { useDocuments, usePendingReview, useSubmitReview } from "../hooks/queries";
import { FileDropzone, uploadFiles } from "./NewClaimPage";

const STREAM_LABELS: Record<string, string> = { clinical_provider_notes: "Provider notes", rehab_notes: "Rehab notes", billing: "Billing", pharmacy: "Pharmacy", employer_reports: "Employer reports", legal_admin: "Legal / admin" };

function ReclassifyDialog({ doc, onClose }: { doc: DocumentItem | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [type, setType] = useState("");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.patch(`/documents/${doc!.id}/classification`, { doc_type: type, reason }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["documents"] }); onClose(); },
  });
  return (
    <Dialog open={!!doc} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Correct classification</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 2 }}>{doc?.title} - currently <b>{doc?.classification?.doc_type}</b> ({Math.round((doc?.classification?.confidence ?? 0) * 100)}%)</Typography>
        <ErrorAlert error={m.error} />
        <TextField select fullWidth label="Document type" value={type} onChange={(e) => setType(e.target.value)} sx={{ mb: 2 }}>
          {DOC_TYPES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
        <TextField fullWidth multiline minRows={2} label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" disabled={!type || reason.length < 3} onClick={() => m.mutate()}>Save new version</Button></DialogActions>
    </Dialog>
  );
}

function SplitDialog({ doc, onClose }: { doc: DocumentItem | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [ranges, setRanges] = useState("");
  const m = useMutation({
    mutationFn: () => api.post(`/documents/${doc!.id}/split`, { page_ranges: ranges.split(",").map((r) => r.trim().split("-").map(Number)).map(([a, b]) => [a, b ?? a]), reason: "Manual split" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["documents"] }); onClose(); },
  });
  return (
    <Dialog open={!!doc} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Split document</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 2 }}>{doc?.title} ({doc?.page_count} pages). Enter page ranges covering every page, e.g. <code>1-2, 3-{doc?.page_count}</code>.</Typography>
        <ErrorAlert error={m.error} />
        <TextField fullWidth label="Page ranges" value={ranges} onChange={(e) => setRanges(e.target.value)} />
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={() => m.mutate()} disabled={!ranges}>Split</Button></DialogActions>
    </Dialog>
  );
}

export default function DocumentsPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [group, setGroup] = useState<"episode" | "stream" | "type">("episode");
  const [status, setStatus] = useState("processed");
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [submittedQ, setSubmittedQ] = useState("");
  const [reclassify, setReclassify] = useState<DocumentItem | null>(null);
  const [split, setSplit] = useState<DocumentItem | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<number | null>(null);
  const docs = useDocuments(claimId, status ? { status } : {});
  const search = useQuery({ queryKey: ["search", claimId, submittedQ, mode], queryFn: () => api.get<any[]>(`/claims/${claimId}/search${qs({ q: submittedQ, mode })}`), enabled: submittedQ.length > 1 });
  const requests = useQuery({ queryKey: ["doc-requests", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/document-requests`) });
  const awaiting = usePendingReview(claimId, "AWAIT-DOCS");
  const submit = useSubmitReview(claimId);
  const upload = useMutation({
    mutationFn: async () => { setProgress(0); await uploadFiles(claimId!, files, "upload", setProgress); },
    onSuccess: () => { setFiles([]); setProgress(null); qc.invalidateQueries({ queryKey: ["documents"] }); },
  });
  const updateReq = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => api.patch(`/document-requests/${id}`, { status }), onSuccess: () => requests.refetch() });

  const groups = useMemo(() => {
    const out: Record<string, DocumentItem[]> = {};
    (docs.data ?? []).forEach((d) => {
      const key = group === "episode" ? d.episode?.label ?? "Not in timeline" : group === "stream" ? STREAM_LABELS[d.stream ?? ""] ?? "Unrouted" : d.classification?.doc_type ?? "Unclassified";
      (out[key] ??= []).push(d);
    });
    return out;
  }, [docs.data, group]);

  return (
    <Box>
      {awaiting.review && (
        <Alert severity="warning" sx={{ mb: 2 }} action={awaiting.review.can_act && <Button variant="contained" size="small" onClick={() => submit.mutate({ id: awaiting.review!.id, body: { resume: true } })}>Resume run</Button>}>
          The workflow is waiting for requested records. Upload them below, then resume the run.
        </Alert>
      )}
      <ErrorAlert error={submit.error || upload.error} />
      <Section title="Search the medical record" dense>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} component="form" onSubmit={(e) => { e.preventDefault(); setSubmittedQ(q); }}>
          <TextField fullWidth placeholder='e.g. "MRI herniation", "lifting restriction", "oxycodone"' value={q} onChange={(e) => setQ(e.target.value)}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> }} />
          <ToggleButtonGroup size="small" exclusive value={mode} onChange={(_, v) => v && setMode(v)}>
            <ToggleButton value="keyword">Keyword</ToggleButton><ToggleButton value="semantic">Semantic</ToggleButton><ToggleButton value="hybrid">Hybrid</ToggleButton>
          </ToggleButtonGroup>
          <Button type="submit" variant="contained">Search</Button>
        </Stack>
        {search.isFetching && <LinearProgress sx={{ mt: 1 }} />}
        {search.data && (
          <List dense sx={{ maxHeight: 300, overflow: "auto" }}>
            {search.data.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>No matches.</Typography>}
            {search.data.map((h, i) => (
              <ListItemButton key={i} onClick={() => navigate(`/claims/${claimId}/viewer/${h.document_id}?page=${h.page_number}&ls=${h.line_number}&le=${h.line_number}`)}>
                <ListItemText primary={<>{h.document_title} <Typography component="span" variant="caption" color="text.secondary">p{h.page_number} L{h.line_number} - {h.sources?.join("+")}</Typography></>} secondary={h.line_text || h.snippet} />
              </ListItemButton>
            ))}
          </List>
        )}
      </Section>
      <Paper sx={{ p: 1.5, mb: 2, display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <ToggleButtonGroup size="small" exclusive value={group} onChange={(_, v) => v && setGroup(v)}>
          <ToggleButton value="episode">By episode</ToggleButton><ToggleButton value="stream">By stream</ToggleButton><ToggleButton value="type">By type</ToggleButton>
        </ToggleButtonGroup>
        <TextField select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 170 }}>
          <MenuItem value="">All (incl. containers)</MenuItem>
          {["processed", "duplicate", "noise", "failed", "split", "received"].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
        </TextField>
        <Typography variant="body2" color="text.secondary">{docs.data?.length ?? 0} documents</Typography>
      </Paper>
      <ErrorAlert error={docs.error} />
      {docs.isLoading && <LinearProgress />}
      {Object.entries(groups).map(([g, items]) => (
        <TableContainer component={Paper} key={g} sx={{ mb: 2 }}>
          <Typography variant="subtitle2" sx={{ px: 1.5, pt: 1.25 }}>{g} <Chip label={items.length} size="small" sx={{ ml: 0.5 }} /></Typography>
          <Table size="small">
            <TableHead><TableRow><TableCell>#</TableCell><TableCell>Document</TableCell><TableCell>Type</TableCell><TableCell>Date</TableCell><TableCell>Provider</TableCell><TableCell>Codes</TableCell><TableCell>Pages</TableCell><TableCell>Status</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
            <TableBody>
              {items.map((d) => (
                <TableRow key={d.id} hover>
                  <TableCell>{d.alias}</TableCell>
                  <TableCell sx={{ maxWidth: 260 }}><Typography variant="body2" noWrap title={d.title}>{d.title}</Typography><Typography variant="caption" color="text.secondary" noWrap display="block">{d.original_filename}</Typography></TableCell>
                  <TableCell>
                    {d.classification ? <Tooltip title={d.classification.rationale ?? ""}><Chip label={`${d.classification.doc_type} ${Math.round(d.classification.confidence * 100)}%`} size="small"
                      color={d.classification.needs_attention ? "warning" : d.classification.classified_by === "agent" ? "default" : "primary"} variant="outlined" /></Tooltip> : "-"}
                    {d.classification && d.classification.classified_by !== "agent" && <Typography variant="caption" display="block" color="primary">Human corrected (v{d.classification.version})</Typography>}
                  </TableCell>
                  <TableCell>{fmtDate(d.classification?.service_date_start)}</TableCell>
                  <TableCell>{d.classification?.provider_name ?? d.classification?.facility ?? "-"}</TableCell>
                  <TableCell><Typography variant="caption">{[...(d.classification?.icd10_codes ?? []), ...(d.classification?.cpt_codes ?? [])].join(", ")}</Typography></TableCell>
                  <TableCell>{d.page_count}</TableCell>
                  <TableCell><StatusChip status={d.status} />{d.status_reason && <Typography variant="caption" display="block" color="text.secondary">{d.status_reason}</Typography>}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    {d.page_count > 0 && !d.is_container && <Button size="small" onClick={() => navigate(`/claims/${claimId}/viewer/${d.id}`)}>View</Button>}
                    {can("classification:edit") && !d.is_container && <Button size="small" onClick={() => setReclassify(d)}>Reclassify</Button>}
                    {can("classification:edit") && !d.is_container && d.page_count > 1 && d.status === "processed" && <Button size="small" onClick={() => setSplit(d)}>Split</Button>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ))}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        {can("document:upload") && (
          <Box sx={{ flex: 1 }}>
            <Section title="Upload more records">
              <FileDropzone files={files} setFiles={setFiles} />
              {progress !== null && <LinearProgress variant="determinate" value={progress} sx={{ my: 1 }} />}
              <Button variant="contained" disabled={!files.length || upload.isPending} onClick={() => upload.mutate()}>Upload</Button>
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>New documents are processed by an incremental run (Dashboard - Process new documents).</Typography>
            </Section>
          </Box>
        )}
        <Box sx={{ flex: 1 }}>
          <Section title="Document requests (proactive document chasing)">
            {(requests.data ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No requests.</Typography>}
            {(requests.data ?? []).map((r) => (
              <Stack key={r.id} direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <StatusChip status={r.status} />
                <Box sx={{ flex: 1 }}><Typography variant="body2">{r.description}</Typography><Typography variant="caption" color="text.secondary">{r.reason}{r.requested_from ? ` - from ${r.requested_from}` : ""}{r.due_date ? ` - due ${fmtDate(r.due_date)}` : ""}</Typography></Box>
                {can("care:coordinate", "document:upload") && r.status === "open" && <Button size="small" onClick={() => updateReq.mutate({ id: r.id, status: "sent" })}>Mark sent</Button>}
                {can("care:coordinate", "document:upload") && ["open", "sent"].includes(r.status) && <Button size="small" onClick={() => updateReq.mutate({ id: r.id, status: "received" })}>Received</Button>}
              </Stack>
            ))}
          </Section>
        </Box>
      </Stack>
      <ReclassifyDialog doc={reclassify} onClose={() => setReclassify(null)} />
      <SplitDialog doc={split} onClose={() => setSplit(null)} />
    </Box>
  );
}
