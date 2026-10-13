import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid, LinearProgress, MenuItem, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Summary } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { CitedMarkdown } from "../components/CitationViewer";
import { AiDraftBadge, EmptyState, ErrorAlert, fmtDateTime, Section, StatusChip } from "../components/common";
import { usePendingReview, useSubmitReview, useSummaries } from "../hooks/queries";
import { ExportBar } from "./ChronologyPage";

const TYPES = [
  { key: "one_page", label: "One-page summary" }, { key: "narrative", label: "Clinical narrative" }, { key: "mmi_status", label: "MMI status report" },
  { key: "case_progress", label: "Case progress" },
];

/** Line-level diff between two versions (LCS), for the VersionDiff view. */
function diffLines(a: string, b: string) {
  const x = a.split("\n"), y = b.split("\n");
  const dp = Array.from({ length: x.length + 1 }, () => Array(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { t: " " | "-" | "+"; s: string }[] = [];
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { out.push({ t: " ", s: x[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: "-", s: x[i++] });
    else out.push({ t: "+", s: y[j++] });
  }
  while (i < x.length) out.push({ t: "-", s: x[i++] });
  while (j < y.length) out.push({ t: "+", s: y[j++] });
  return out;
}

const strip = (s: string) => s.replace(/\s*\[\[cite:[0-9a-f-]{36}\]\]/g, "");

export default function SummaryPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const summaries = useSummaries(claimId);
  const { review } = usePendingReview(claimId, "HITL-3");
  const submit = useSubmitReview(claimId);
  const [type, setType] = useState("one_page");
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [regen, setRegen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [compareTo, setCompareTo] = useState("");
  const current = summaries.data?.find((s) => s.summary_type === type);
  const detail = useQuery({ queryKey: ["summary", current?.id], queryFn: () => api.get<Summary>(`/summaries/${current!.id}`), enabled: !!current });
  const save = useMutation({ mutationFn: () => api.put(`/summaries/${current!.id}`, { content_md: text, reason }),
    onSuccess: () => { setEditing(false); setReason(""); qc.invalidateQueries({ queryKey: ["summaries", claimId] }); } });
  if (summaries.isLoading) return <LinearProgress />;
  const s = detail.data;
  const other = s?.history?.find((h) => h.id === compareTo);
  return (
    <Box>
      {review && <Alert severity="warning" sx={{ mb: 2 }}><b>HITL-3 NCM summary review.</b> Confirm the summary answers the claim question and highlights the evidence for the next decision. Edit inline (new version), request regeneration with instructions, or approve to lock all report versions.<br /><b>Review question:</b> {review.payload?.review_question}</Alert>}
      <ExportBar claimId={claimId!} types={[{ type: "one_page_summary", label: "One-page summary" }, { type: "mmi_status", label: "MMI status" }, { type: "narrative", label: "Narrative" }]} />
      <ErrorAlert error={summaries.error || save.error || submit.error} />
      <Tabs value={type} onChange={(_, v) => { setType(v); setEditing(false); setCompareTo(""); }} sx={{ mb: 2 }}>
        {TYPES.map((t) => <Tab key={t.key} value={t.key} label={t.label} />)}
      </Tabs>
      {!current ? <EmptyState title="Not generated yet" hint="Reports are produced in Stage 6." /> : !s ? <LinearProgress /> : (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: compareTo ? 6 : 12 }}>
            <Section title={<>Version {s.version} <StatusChip status={s.status} /> {s.word_count != null && <Chip size="small" label={`${s.word_count} words`} color={type === "one_page" && s.word_count > 600 ? "error" : "default"} />}</>}
              actions={<>
                {s.status !== "approved" && <AiDraftBadge label={s.author_type === "user" ? `Edited by ${s.edited_by_name}` : "AI draft"} />}
                {s.status === "approved" && <Chip color="success" label={`Approved by ${s.approved_by_name}`} />}
                {(s.history?.length ?? 0) > 1 && (
                  <TextField select size="small" label="Compare with" value={compareTo} onChange={(e) => setCompareTo(e.target.value)} sx={{ minWidth: 160 }}>
                    <MenuItem value="">No comparison</MenuItem>
                    {s.history!.filter((h) => h.id !== s.id).map((h) => <MenuItem key={h.id} value={h.id}>v{h.version} ({h.author_type}) {fmtDateTime(h.created_at)}</MenuItem>)}
                  </TextField>
                )}
                {can("summary:edit") && s.status !== "approved" && !editing && <Button onClick={() => { setText(s.content_md); setEditing(true); }}>Edit inline</Button>}
              </>}>
              {editing ? (
                <Stack spacing={1}>
                  <Typography variant="caption" color="text.secondary">Markdown: "### Heading" and "- bullet". Keep the [[cite:...]] tokens to preserve evidence links.</Typography>
                  <TextField multiline minRows={18} fullWidth value={text} onChange={(e) => setText(e.target.value)} InputProps={{ sx: { fontFamily: "monospace", fontSize: 12 } }} />
                  <TextField label="Reason for edit" value={reason} onChange={(e) => setReason(e.target.value)} />
                  <Stack direction="row" spacing={1}><Button variant="contained" disabled={reason.length < 3} onClick={() => save.mutate()}>Save new version</Button><Button onClick={() => setEditing(false)}>Cancel</Button></Stack>
                </Stack>
              ) : <CitedMarkdown md={s.content_md} citations={s.citations} claimId={claimId} />}
            </Section>
          </Grid>
          {other && (
            <Grid size={{ xs: 12, lg: 6 }}>
              <Section title={`Changes from v${other.version} to v${s.version}`}>
                <Box component="pre" sx={{ m: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>
                  {diffLines(strip(other.content_md), strip(s.content_md)).map((d, i) => (
                    <Box key={i} component="div" sx={{ bgcolor: d.t === "+" ? "#ecfdf3" : d.t === "-" ? "#fef3f2" : undefined, color: d.t === "-" ? "#b42318" : undefined }}>{d.t} {d.s}</Box>
                  ))}
                </Box>
              </Section>
            </Grid>
          )}
        </Grid>
      )}
      {review?.can_act && (
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button onClick={() => setRegen(true)}>Request regeneration</Button>
          <Button variant="contained" size="large" onClick={() => submit.mutate({ id: review.id, body: { action: "approve" } })} disabled={submit.isPending}>Approve and lock summaries</Button>
        </Stack>
      )}
      <Dialog open={regen} onClose={() => setRegen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Regenerate reports</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1 }}>The Report Agent regenerates the narrative, one-page summary, MMI status and case-progress reports with your instructions.</Typography>
          <TextField autoFocus fullWidth multiline minRows={3} label="Instructions" placeholder="e.g. Emphasize the employer's inability to accommodate light duty" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRegen(false)}>Cancel</Button>
          <Button variant="contained" disabled={instructions.trim().length < 5} onClick={() => { submit.mutate({ id: review!.id, body: { action: "revise", regenerate_instructions: instructions } }); setRegen(false); }}>Regenerate</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
