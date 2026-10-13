import { Alert, Box, Button, Chip, Grid2 as Grid, IconButton, LinearProgress, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import WarningIcon from "@mui/icons-material/Warning";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { CitationChip } from "../components/CitationViewer";
import { EmptyState, ErrorAlert, fmtDate, Section } from "../components/common";
import { useClaim, usePendingReview, useSubmitReview } from "../hooks/queries";

const LABELS: Record<string, string> = {
  claim_number: "Claim number", claimant_name: "Injured worker", employer_name: "Employer", insurer: "Insurer", tpa: "TPA",
  date_of_injury: "Date of injury", body_parts: "Body part(s)", mechanism_of_injury: "Mechanism", assigned_adjuster: "Assigned adjuster",
  jurisdiction_state: "Jurisdiction",
};

function ListEditor({ label, items, onChange }: { label: string; items: string[]; onChange: (v: string[]) => void }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{label}</Typography>
      {items.map((it, i) => (
        <Stack key={i} direction="row" spacing={1} sx={{ mb: 0.75 }}>
          <TextField fullWidth value={it} onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))} />
          <IconButton aria-label="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
        </Stack>
      ))}
      <Button size="small" startIcon={<AddIcon />} onClick={() => onChange([...items, ""])}>Add</Button>
    </Box>
  );
}

export default function BaselinePage() {
  const { claimId } = useParams();
  const claim = useClaim(claimId);
  const { review, isLoading } = usePendingReview(claimId, "HITL-0");
  const submit = useSubmitReview(claimId);
  const qc = useQueryClient();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [rc, setRc] = useState<any>(null);
  const [requests, setRequests] = useState<{ description: string; requested_from: string }[]>([]);
  const baseline = review?.payload?.baseline ?? claim.data?.baseline?.fields ?? {};
  const conflicts: any[] = review?.payload?.conflicts ?? claim.data?.baseline?.conflicts ?? [];

  useEffect(() => {
    const ctx = review?.payload?.review_context ?? claim.data?.review_context;
    if (ctx && !rc) setRc({ review_goals: ctx.review_goals ?? [], clinical_question: ctx.clinical_question ?? "", required_evidence: ctx.required_evidence ?? [], applicable_guidelines: ctx.applicable_guidelines ?? [], state_rules: ctx.state_rules ?? [] });
  }, [review, claim.data, rc]);

  const saveContext = useMutation({ mutationFn: () => api.put(`/claims/${claimId}/review-context`, rc), onSuccess: () => qc.invalidateQueries({ queryKey: ["claim", claimId] }) });
  if (isLoading || claim.isLoading) return <LinearProgress />;
  if (!Object.keys(baseline).length) return <EmptyState title="Baseline not extracted yet" hint="The Intake Agent extracts the baseline from the FROI, employer report and initial medical records." />;

  const doSubmit = () => {
    const changed = Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== undefined));
    submit.mutate({ id: review!.id, body: { fields: changed, review_context: rc && rc.clinical_question.length >= 10 ? { ...rc, review_goals: rc.review_goals.filter(Boolean) } : undefined,
      document_requests: requests.filter((r) => r.description.trim()) } });
  };

  return (
    <Box>
      {review ? <Alert severity="warning" sx={{ mb: 2 }}><b>HITL-0 Baseline confirmation.</b> Confirm or correct the extracted baseline (100% accuracy required) and the review goals. Confirming locks the baseline.</Alert>
        : claim.data?.baseline_locked ? <Alert severity="success" sx={{ mb: 2 }}>Baseline locked{claim.data?.baseline?.confirmed_at ? ` on ${fmtDate(claim.data.baseline.confirmed_at)}` : ""}. Only a supervisor can change locked baseline fields.</Alert> : null}
      <ErrorAlert error={submit.error || saveContext.error} />
      {conflicts.length > 0 && (
        <Alert severity="error" icon={<WarningIcon />} sx={{ mb: 2 }}>
          {conflicts.map((c, i) => <div key={i}><b>{LABELS[c.field] ?? c.field}:</b> claim metadata "{c.claim_value}" vs document "{c.document_value}". {c.note}</div>)}
        </Alert>
      )}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Claim baseline (PW-1.1)">
            <Table size="small">
              <TableHead><TableRow><TableCell>Field</TableCell><TableCell>Value</TableCell><TableCell>Confidence</TableCell><TableCell>Source</TableCell></TableRow></TableHead>
              <TableBody>
                {Object.keys(LABELS).map((k) => {
                  const f = baseline[k] ?? {};
                  return (
                    <TableRow key={k} sx={{ bgcolor: f.conflict ? "#fef3f2" : undefined }}>
                      <TableCell sx={{ width: 150 }}>{LABELS[k]}</TableCell>
                      <TableCell>
                        {review ? <TextField fullWidth defaultValue={f.value ?? ""} onChange={(e) => setFields({ ...fields, [k]: e.target.value })} disabled={k === "claim_number"} />
                          : <Typography variant="body2">{f.value ?? "-"}</Typography>}
                        {f.claim_value && f.claim_value !== f.value && <Typography variant="caption" color="text.secondary">Claim metadata: {f.claim_value}</Typography>}
                      </TableCell>
                      <TableCell><Chip label={f.confidence != null ? `${Math.round(f.confidence * 100)}%` : "-"} color={f.confidence >= 0.95 ? "success" : f.confidence ? "warning" : "default"} variant="outlined" /></TableCell>
                      <TableCell>{f.citation ? <CitationChip citation={f.citation} claimId={claimId} /> : <Tooltip title="Not found in the source documents"><Chip label="none" size="small" /></Tooltip>}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
              Review time window: {fmtDate(review?.payload?.time_window?.start ?? claim.data?.time_window?.start)} - {fmtDate(review?.payload?.time_window?.end ?? claim.data?.time_window?.end)} (DOI minus 2 years for prior-condition history)
              {(review?.payload?.policy ?? claim.data?.baseline?.policy)?.policy_number && ` - Policy ${(review?.payload?.policy ?? claim.data?.baseline?.policy).policy_number} (${(review?.payload?.policy ?? claim.data?.baseline?.policy).status})`}
            </Typography>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title="Review context (PW-1.3)" actions={!review && rc && <Button onClick={() => saveContext.mutate()} disabled={saveContext.isPending}>Save</Button>}>
            {rc ? (
              <>
                <TextField fullWidth multiline minRows={3} label="Clinical question the review must answer" value={rc.clinical_question} onChange={(e) => setRc({ ...rc, clinical_question: e.target.value })} sx={{ mb: 2 }} />
                <ListEditor label="Review goals" items={rc.review_goals} onChange={(v) => setRc({ ...rc, review_goals: v })} />
                <ListEditor label="Required evidence" items={rc.required_evidence} onChange={(v) => setRc({ ...rc, required_evidence: v })} />
                <ListEditor label="Applicable guidelines" items={rc.applicable_guidelines} onChange={(v) => setRc({ ...rc, applicable_guidelines: v })} />
                <ListEditor label="State rules" items={rc.state_rules} onChange={(v) => setRc({ ...rc, state_rules: v })} />
              </>
            ) : <Typography variant="body2" color="text.secondary">Not drafted yet.</Typography>}
          </Section>
          {review && (
            <Section title="Priority items (PW-1.2)">
              {(review.payload.urgent_flags ?? []).map((f: any) => <Alert key={f.id} severity={f.severity === "high" ? "error" : "warning"} sx={{ mb: 1 }}>{f.title}</Alert>)}
              <Typography variant="subtitle2" sx={{ mt: 1 }}>Open document requests</Typography>
              {(review.payload.document_requests ?? []).map((r: any) => <Typography key={r.id} variant="body2">- {r.description} <Typography component="span" variant="caption" color="text.secondary">({r.reason})</Typography></Typography>)}
              <Typography variant="subtitle2" sx={{ mt: 2 }}>Request additional records</Typography>
              {requests.map((r, i) => (
                <Stack key={i} direction="row" spacing={1} sx={{ mt: 1 }}>
                  <TextField fullWidth label="Record" value={r.description} onChange={(e) => setRequests(requests.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
                  <TextField label="From" value={r.requested_from} onChange={(e) => setRequests(requests.map((x, j) => (j === i ? { ...x, requested_from: e.target.value } : x)))} />
                </Stack>
              ))}
              <Button size="small" startIcon={<AddIcon />} sx={{ mt: 1 }} onClick={() => setRequests([...requests, { description: "", requested_from: "" }])}>Add request</Button>
            </Section>
          )}
        </Grid>
      </Grid>
      {review && review.can_act && (
        <Stack direction="row" justifyContent="flex-end" spacing={1}>
          <Button variant="contained" size="large" onClick={doSubmit} disabled={submit.isPending}>Confirm and lock baseline</Button>
        </Stack>
      )}
      {review && !review.can_act && <Alert severity="info">This checkpoint is assigned to {review.assigned_role.replace(/_/g, " ")}.</Alert>}
    </Box>
  );
}
