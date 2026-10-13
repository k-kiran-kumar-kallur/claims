import { Alert, Box, Button, Chip, Grid2 as Grid, IconButton, LinearProgress, List, ListItem, ListItemText, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DeleteIcon from "@mui/icons-material/Delete";
import { useMutation } from "@tanstack/react-query";
import { DragEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getAccessToken } from "../api/client";
import { useUsers } from "../hooks/queries";
import { ErrorAlert, PageHeader, Section } from "../components/common";

const ACCEPT = ".pdf,.tif,.tiff,.png,.jpg,.jpeg,.docx,.eml,.txt";
const CHUNK_THRESHOLD = 50 * 1024 * 1024;

/** Multipart upload with progress (XHR); files over 50 MB use the chunked upload API. */
export async function uploadFiles(claimId: string, files: File[], channel: string, onProgress: (pct: number) => void) {
  const small = files.filter((f) => f.size <= CHUNK_THRESHOLD);
  const large = files.filter((f) => f.size > CHUNK_THRESHOLD);
  if (small.length) {
    await new Promise<void>((resolve, reject) => {
      const fd = new FormData();
      small.forEach((f) => fd.append("files", f));
      fd.append("source_channel", channel);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/v1/claims/${claimId}/documents`);
      xhr.setRequestHeader("Authorization", `Bearer ${getAccessToken()}`);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * (large.length ? 50 : 100)));
      xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(JSON.parse(xhr.responseText || "{}").detail || `Upload failed (${xhr.status})`)));
      xhr.onerror = () => reject(new Error("Network error during upload"));
      xhr.send(fd);
    });
  }
  for (const f of large) {
    const init = await api.post<{ upload_id: string; chunk_size: number }>(`/claims/${claimId}/documents/uploads`, { filename: f.name, total_size: f.size, source_channel: channel });
    const n = Math.ceil(f.size / init.chunk_size);
    for (let i = 0; i < n; i++) {
      const chunk = f.slice(i * init.chunk_size, (i + 1) * init.chunk_size);
      const r = await fetch(`/api/v1/claims/${claimId}/documents/uploads/${init.upload_id}/chunks/${i}`, {
        method: "PUT", body: chunk, headers: { Authorization: `Bearer ${getAccessToken()}`, "X-Requested-With": "XMLHttpRequest" } });
      if (!r.ok) throw new Error(`Chunk ${i} failed`);
      onProgress(50 + Math.round(((i + 1) / n) * 50));
    }
    await api.post(`/claims/${claimId}/documents/uploads/${init.upload_id}/complete?total_chunks=${n}`);
  }
  onProgress(100);
}

export function FileDropzone({ files, setFiles }: { files: File[]; setFiles: (f: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const add = (list: FileList | null) => list && setFiles([...files, ...Array.from(list)]);
  return (
    <Box>
      <Box role="button" tabIndex={0} onClick={() => input.current?.click()} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
        onDragOver={(e: DragEvent) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e: DragEvent) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        sx={{ border: "2px dashed", borderColor: over ? "primary.main" : "divider", borderRadius: 2, p: 4, textAlign: "center", cursor: "pointer", bgcolor: over ? "primary.light" : "#fafbfd" }}>
        <CloudUploadIcon color="primary" sx={{ fontSize: 40 }} />
        <Typography>Drop faxes, scanned mail, PDFs, images, DOCX or .eml emails here, or click to browse</Typography>
        <Typography variant="caption" color="text.secondary">Up to 200 MB per file. Multi-document fax packets are split automatically.</Typography>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => add(e.target.files)} />
      </Box>
      {files.length > 0 && (
        <List dense>
          {files.map((f, i) => (
            <ListItem key={i} secondaryAction={<IconButton edge="end" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}><DeleteIcon /></IconButton>}>
              <ListItemText primary={f.name} secondary={`${(f.size / 1024).toFixed(0)} KB`} />
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
}

export default function NewClaimPage() {
  const navigate = useNavigate();
  const examiners = useUsers("claims_examiner");
  const ncms = useUsers("nurse_case_manager");
  const reviewers = useUsers("clinical_reviewer");
  const supervisors = useUsers("claims_supervisor");
  const [form, setForm] = useState<Record<string, string>>({ jurisdiction_state: "PA" });
  const [files, setFiles] = useState<File[]>([]);
  const [channel, setChannel] = useState("upload");
  const [progress, setProgress] = useState<number | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const create = useMutation({
    mutationFn: async () => {
      const claim = await api.post<{ id: string }>("/claims", {
        claim_number: form.claim_number, claimant: { full_name: form.claimant_name, dob: form.dob || undefined, ssn_last4: form.ssn_last4 || undefined },
        employer_name: form.employer_name || undefined, insurer: form.insurer || undefined, tpa: form.tpa || undefined,
        date_of_injury: form.date_of_injury || undefined, jurisdiction_state: form.jurisdiction_state || undefined,
        body_parts: form.body_parts ? form.body_parts.split(",").map((s) => s.trim()).filter(Boolean) : [],
        mechanism_of_injury: form.mechanism || undefined, adjuster_name: form.adjuster_name || undefined,
        assigned_adjuster_id: form.adjuster || undefined, assigned_ncm_id: form.ncm || undefined,
        assigned_reviewer_id: form.reviewer || undefined, assigned_supervisor_id: form.supervisor || undefined,
      });
      if (files.length) {
        setProgress(0);
        await uploadFiles(claim.id, files, channel, setProgress);
        await api.post(`/claims/${claim.id}/runs`, { mode: "full" });
      }
      return claim;
    },
    onSuccess: (claim) => navigate(`/claims/${claim.id}`),
  });

  const picker = (key: string, label: string, list?: { id: string; full_name: string }[]) => (
    <TextField select fullWidth label={label} value={form[key] ?? ""} onChange={set(key)}>
      <MenuItem value="">Unassigned</MenuItem>
      {(list ?? []).map((u) => <MenuItem key={u.id} value={u.id}>{u.full_name}</MenuItem>)}
    </TextField>
  );

  return (
    <Box>
      <PageHeader title="New claim and upload" subtitle="Stage 1 - Medical Record Intake. Enter the claim metadata, upload the package and start AI processing." />
      <Alert severity="warning" sx={{ mb: 2 }}>Use synthetic or de-identified data unless the deployment uses a paid Gemini tier or Vertex AI under a BAA.</Alert>
      <ErrorAlert error={create.error} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Claim baseline">
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth required label="Claim number" placeholder="WC-2025-PA-000123" value={form.claim_number ?? ""} onChange={set("claim_number")} /></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth required label="Injured worker (full name)" value={form.claimant_name ?? ""} onChange={set("claimant_name")} /></Grid>
              <Grid size={{ xs: 12, sm: 4 }}><TextField fullWidth type="date" label="Date of injury" InputLabelProps={{ shrink: true }} value={form.date_of_injury ?? ""} onChange={set("date_of_injury")} /></Grid>
              <Grid size={{ xs: 12, sm: 4 }}><TextField fullWidth type="date" label="Date of birth" InputLabelProps={{ shrink: true }} value={form.dob ?? ""} onChange={set("dob")} /></Grid>
              <Grid size={{ xs: 12, sm: 4 }}><TextField fullWidth label="SSN last 4" inputProps={{ maxLength: 4, inputMode: "numeric" }} value={form.ssn_last4 ?? ""} onChange={set("ssn_last4")} /></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Employer" value={form.employer_name ?? ""} onChange={set("employer_name")} /></Grid>
              <Grid size={{ xs: 12, sm: 3 }}><TextField fullWidth label="Jurisdiction" inputProps={{ maxLength: 2 }} value={form.jurisdiction_state ?? ""} onChange={set("jurisdiction_state")} /></Grid>
              <Grid size={{ xs: 12, sm: 3 }}><TextField fullWidth label="Body part(s)" placeholder="lumbar spine" value={form.body_parts ?? ""} onChange={set("body_parts")} /></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Insurer" value={form.insurer ?? ""} onChange={set("insurer")} /></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="TPA" value={form.tpa ?? ""} onChange={set("tpa")} /></Grid>
              <Grid size={{ xs: 12 }}><TextField fullWidth multiline minRows={2} label="Mechanism of injury (if known)" value={form.mechanism ?? ""} onChange={set("mechanism")} /></Grid>
            </Grid>
          </Section>
          <Section title="Assignments">
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>{picker("adjuster", "Claims examiner", examiners.data)}</Grid>
              <Grid size={{ xs: 12, sm: 6 }}>{picker("ncm", "Nurse case manager", ncms.data)}</Grid>
              <Grid size={{ xs: 12, sm: 6 }}>{picker("reviewer", "Clinical / UR reviewer", reviewers.data)}</Grid>
              <Grid size={{ xs: 12, sm: 6 }}>{picker("supervisor", "Supervisor", supervisors.data)}</Grid>
            </Grid>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title="Medical record package">
            <TextField select fullWidth label="Source channel" value={channel} onChange={(e) => setChannel(e.target.value)} sx={{ mb: 2 }}>
              {["upload", "fax", "mail", "email", "cms"].map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
            </TextField>
            <FileDropzone files={files} setFiles={setFiles} />
            {progress !== null && <Box sx={{ mt: 2 }}><LinearProgress variant="determinate" value={progress} /><Typography variant="caption">Uploading {progress}%</Typography></Box>}
          </Section>
          <Paper sx={{ p: 2 }}>
            <Stack spacing={1}>
              <Typography variant="body2" color="text.secondary">On submit the claim is created, files are virus-scanned, encrypted and stored, and the 7-stage workflow starts. You will be notified at each human checkpoint.</Typography>
              <Stack direction="row" spacing={1}>{files.length > 0 && <Chip label={`${files.length} file(s)`} />}</Stack>
              <Button variant="contained" size="large" disabled={!form.claim_number || !form.claimant_name || create.isPending} onClick={() => create.mutate()}>
                {create.isPending ? "Working..." : files.length ? "Create claim, upload and start processing" : "Create claim"}
              </Button>
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}
