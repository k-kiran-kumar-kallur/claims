import {
  Alert, Box, Button, ButtonGroup, Chip, Grid2 as Grid, IconButton, LinearProgress, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Tooltip, Typography, FormControlLabel, Checkbox,
} from "@mui/material";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import EditIcon from "@mui/icons-material/Edit";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Flag } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { CitationList } from "../components/CitationViewer";
import { AiDraftBadge, ErrorAlert, fmtDateTime, ReasonDialog, Section, SeverityChip, StatusChip } from "../components/common";
import { useFlags, usePendingReview, useSubmitReview } from "../hooks/queries";

const DECISION_TYPES = ["treatment_authorization", "disability_status", "claim_trajectory", "reserve_change", "referral", "escalation"];
const ACTIONABLE = ["mmi_status", "rtw_limit", "guideline_deviation"];

function FlagRow({ f, claimId, canAct }: { f: Flag; claimId: string; canAct: boolean }) {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<"reject" | "modify" | null>(null);
  const [value, setValue] = useState("");
  const m = useMutation({ mutationFn: (body: any) => api.post(`/flags/${f.id}/action`, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["flags", claimId] }) });
  return (
    <TableRow sx={{ bgcolor: f.human_action ? "#fafbfc" : undefined }}>
      <TableCell><SeverityChip severity={f.severity} /></TableCell>
      <TableCell><Chip size="small" variant="outlined" label={f.flag_type.replace(/_/g, " ")} /></TableCell>
      <TableCell>
        <Typography variant="body2" fontWeight={600}>{f.title}</Typography>
        {f.detail && <Typography variant="caption" color="text.secondary" display="block">{f.detail}</Typography>}
        <CitationList citations={f.evidence} claimId={claimId} />
      </TableCell>
      <TableCell><Typography variant="body2">{f.ai_recommendation}</Typography></TableCell>
      <TableCell sx={{ whiteSpace: "nowrap" }}>
        {m.error && <Typography color="error" variant="caption">{(m.error as Error).message}</Typography>}
        {f.human_action ? (
          <Box><StatusChip status={f.human_action} />{f.is_override && <Chip label="override" color="warning" size="small" sx={{ ml: 0.5 }} />}
            <Typography variant="caption" display="block" color="text.secondary">{f.acted_by_name}{f.reason ? `: ${f.reason}` : ""}</Typography></Box>
        ) : canAct ? (
          <ButtonGroup size="small">
            <Tooltip title="One-click approve"><Button color="success" variant="contained" onClick={() => m.mutate({ action: "approve" })} aria-label="Approve"><CheckIcon fontSize="small" /></Button></Tooltip>
            <Tooltip title="Modify (reason required)"><Button onClick={() => setDialog("modify")} aria-label="Modify"><EditIcon fontSize="small" /></Button></Tooltip>
            <Tooltip title="Reject / override (reason required)"><Button color="error" onClick={() => setDialog("reject")} aria-label="Reject"><CloseIcon fontSize="small" /></Button></Tooltip>
          </ButtonGroup>
        ) : <Typography variant="caption" color="text.secondary">pending</Typography>}
        <ReasonDialog open={!!dialog} title={dialog === "modify" ? "Modify AI flag" : "Override AI flag"} onClose={() => setDialog(null)}
          extra={dialog === "modify" ? <TextField fullWidth label="Modified value" value={value} onChange={(e) => setValue(e.target.value)} sx={{ mt: 1 }} /> : undefined}
          onConfirm={(reason) => { m.mutate({ action: dialog, reason, value: dialog === "modify" ? value : undefined }); setDialog(null); }} />
      </TableCell>
    </TableRow>
  );
}

function URForm({ claimId, review }: { claimId: string; review: any }) {
  const submit = useSubmitReview(claimId);
  const items: any[] = review.payload?.utilization_assessments ?? [];
  const [dets, setDets] = useState<Record<string, { determination: string; clinical_rationale: string; criteria_refs: string }>>({});
  const set = (id: string, k: string, v: string) => setDets({ ...dets, [id]: { ...(dets[id] ?? { determination: "", clinical_rationale: "", criteria_refs: "" }), [k]: v } });
  return (
    <Section title="UR determination (HITL-4 UR, PW-7.2)" actions={<AiDraftBadge />}>
      <ErrorAlert error={submit.error} />
      {items.map((u) => (
        <Box key={u.id} sx={{ mb: 2, p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
          <Typography variant="subtitle2">{u.request}</Typography>
          <Typography variant="caption" color="text.secondary">{u.requesting_provider} - requested {u.request_date}</Typography>
          <Typography variant="body2" sx={{ my: 1, p: 1, bgcolor: "#fff8e6", borderRadius: 1 }}>{u.ai_recommendation}</Typography>
          {(u.necessity_indicators ?? []).map((n: any, i: number) => <Typography key={i} variant="body2">{n.supports_necessity ? "+" : "-"} {n.indicator} {n.guideline_rule_code && <Chip size="small" label={n.guideline_rule_code} />} <CitationList citations={n.citations} claimId={claimId} /></Typography>)}
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mt: 1.5 }}>
            <TextField select label="Determination" value={dets[u.id]?.determination ?? ""} onChange={(e) => set(u.id, "determination", e.target.value)} sx={{ minWidth: 180 }}>
              {["certified", "modified", "non_certified", "pended"].map((d) => <MenuItem key={d} value={d}>{d.replace("_", " ")}</MenuItem>)}
            </TextField>
            <TextField label="Criteria (rule codes, comma separated)" value={dets[u.id]?.criteria_refs ?? ""} onChange={(e) => set(u.id, "criteria_refs", e.target.value)} sx={{ minWidth: 240 }} />
          </Stack>
          <TextField fullWidth multiline minRows={3} label="Clinical rationale connecting evidence and criteria to the conclusion" value={dets[u.id]?.clinical_rationale ?? ""}
            onChange={(e) => set(u.id, "clinical_rationale", e.target.value)} sx={{ mt: 1 }} />
        </Box>
      ))}
      {review.can_act && (
        <Button variant="contained" disabled={items.some((u) => !dets[u.id]?.determination || (dets[u.id]?.clinical_rationale ?? "").length < 20) || submit.isPending}
          onClick={() => submit.mutate({ id: review.id, body: { determinations: items.map((u) => ({ utilization_assessment_id: u.id, determination: dets[u.id].determination,
            clinical_rationale: dets[u.id].clinical_rationale, criteria_refs: dets[u.id].criteria_refs.split(",").map((s) => s.trim()).filter(Boolean) })) } })}>
          Record UR determination(s)
        </Button>
      )}
    </Section>
  );
}

function SignoffPanel({ claimId, review }: { claimId: string; review: any }) {
  const submit = useSubmitReview(claimId);
  const [comments, setComments] = useState("");
  const p = review.payload;
  return (
    <Section title="Supervisor sign-off (HITL-5, PW-7.3)">
      <Alert severity="info" sx={{ mb: 2 }}>Required because: risk {p.risk_score?.toFixed?.(2)} ({p.complexity}){p.overridden_flags?.length ? `, ${p.overridden_flags.length} AI flag override(s)` : ""}. The user who made the decision cannot sign off.</Alert>
      <ErrorAlert error={submit.error} />
      {p.decisions.map((d: any) => (
        <Box key={d.id} sx={{ mb: 1.5 }}>
          <Typography variant="subtitle2">{d.decision_type.replace(/_/g, " ")}: {d.outcome}</Typography>
          <Typography variant="body2">{d.rationale}</Typography>
          {d.next_steps?.length > 0 && <Typography variant="caption" color="text.secondary">Next steps: {d.next_steps.map((s: any) => (typeof s === "string" ? s : s.action)).join("; ")}</Typography>}
        </Box>
      ))}
      {p.overridden_flags?.map((f: any) => <Alert key={f.id} severity="warning" sx={{ mb: 1 }}>Override: {f.title} - {f.human_action}: {f.reason}</Alert>)}
      {p.routing?.rationale && <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>{p.routing.rationale}</Typography>}
      {review.can_act && (
        <>
          <TextField fullWidth multiline minRows={2} label="Comments" value={comments} onChange={(e) => setComments(e.target.value)} sx={{ mb: 1 }} />
          <Stack direction="row" spacing={1}>
            <Button variant="contained" disabled={comments.length < 3} onClick={() => submit.mutate({ id: review.id, body: { action: "signoff", comments } })}>Sign off and seal</Button>
            <Button color="warning" disabled={comments.length < 3} onClick={() => submit.mutate({ id: review.id, body: { action: "return", comments } })}>Return to examiner</Button>
          </Stack>
        </>
      )}
    </Section>
  );
}

export default function DecisionPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const flags = useFlags(claimId);
  const hitl4 = usePendingReview(claimId, "HITL-4");
  const ur = usePendingReview(claimId, "HITL-4-UR");
  const hitl5 = usePendingReview(claimId, "HITL-5");
  const decisions = useQuery({ queryKey: ["decisions", claimId], queryFn: () => api.get<any>(`/claims/${claimId}/decisions`) });
  const submit = useSubmitReview(claimId);
  const draft = hitl4.review?.payload?.decision_draft;
  const [rows, setRows] = useState<{ decision_type: string; outcome: string; rationale: string; next_steps: string }[]>([]);
  const [escalate, setEscalate] = useState(false);
  const [escReason, setEscReason] = useState("");
  const bulk = useMutation({ mutationFn: (ids: string[]) => api.post("/flags/bulk-action", { flag_ids: ids, action: "approve" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["flags", claimId] }) });
  const canDecide = can("decision:make") && !!hitl4.review?.can_act;
  const pendingIds = (flags.data ?? []).filter((f) => !f.human_action && ACTIONABLE.includes(f.flag_type)).map((f) => f.id);
  const initFromDraft = () => draft && setRows([
    { decision_type: "treatment_authorization", outcome: "", rationale: draft.treatment_recommendation, next_steps: (draft.next_steps ?? []).join("\n") },
    { decision_type: "disability_status", outcome: "", rationale: draft.disability_recommendation, next_steps: "" },
  ]);
  if (flags.isLoading) return <LinearProgress />;
  return (
    <Box>
      {hitl4.review && <Alert severity="warning" sx={{ mb: 2 }}><b>HITL-4 Claims decision.</b> Approve or override each AI-highlighted flag (one click), then record the decision with its rationale. Overrides need a reason and trigger supervisor sign-off.</Alert>}
      {hitl5.review && <SignoffPanel claimId={claimId!} review={hitl5.review} />}
      {ur.review && can("ur:determine") && <URForm claimId={claimId!} review={ur.review} />}
      {ur.review && !can("ur:determine") && <Alert severity="info" sx={{ mb: 2 }}>UR determination pending with the clinical reviewer (in parallel).</Alert>}
      <ErrorAlert error={flags.error || submit.error || bulk.error} />
      <Section title="AI-highlighted flags" actions={canDecide && pendingIds.length > 0 && <Button variant="outlined" onClick={() => bulk.mutate(pendingIds)}>Approve all remaining ({pendingIds.length})</Button>}>
        <Table size="small">
          <TableHead><TableRow><TableCell>Severity</TableCell><TableCell>Type</TableCell><TableCell>Flag and evidence</TableCell><TableCell>AI recommendation</TableCell><TableCell>Action</TableCell></TableRow></TableHead>
          <TableBody>{(flags.data ?? []).map((f) => <FlagRow key={f.id} f={f} claimId={claimId!} canAct={can("flag:act")} />)}</TableBody>
        </Table>
      </Section>
      <Grid container spacing={2}>
        {draft && (
          <Grid size={{ xs: 12, lg: 5 }}>
            <Section title="Decision draft" actions={<AiDraftBadge />}>
              <Typography variant="subtitle2">Treatment</Typography><Typography variant="body2" sx={{ mb: 1 }}>{draft.treatment_recommendation}</Typography>
              <Typography variant="subtitle2">Disability / work status</Typography><Typography variant="body2" sx={{ mb: 1 }}>{draft.disability_recommendation}</Typography>
              <Typography variant="subtitle2">Claim trajectory</Typography><Typography variant="body2" sx={{ mb: 1 }}>{draft.claim_trajectory}</Typography>
              {draft.outstanding_questions?.length > 0 && <><Typography variant="subtitle2">Outstanding questions</Typography>{draft.outstanding_questions.map((q: string, i: number) => <Typography key={i} variant="body2">- {q}</Typography>)}</>}
              {canDecide && <Button sx={{ mt: 1 }} onClick={initFromDraft}>Start from draft</Button>}
            </Section>
          </Grid>
        )}
        {canDecide && (
          <Grid size={{ xs: 12, lg: draft ? 7 : 12 }}>
            <Section title="Record decision" actions={<Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { decision_type: "claim_trajectory", outcome: "", rationale: "", next_steps: "" }])}>Add</Button>}>
              {rows.length === 0 && <Typography variant="body2" color="text.secondary">Add at least one decision (treatment, disability status, claim trajectory...).</Typography>}
              {rows.map((r, i) => (
                <Box key={i} sx={{ mb: 2, p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1}>
                    <TextField select label="Type" value={r.decision_type} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, decision_type: e.target.value } : x)))} sx={{ minWidth: 220 }}>
                      {DECISION_TYPES.map((t) => <MenuItem key={t} value={t}>{t.replace(/_/g, " ")}</MenuItem>)}
                    </TextField>
                    <TextField fullWidth label="Outcome" value={r.outcome} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, outcome: e.target.value } : x)))} />
                    <IconButton aria-label="Remove decision" onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon /></IconButton>
                  </Stack>
                  <TextField fullWidth multiline minRows={2} label="Rationale (evidence and jurisdictional rules)" value={r.rationale} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, rationale: e.target.value } : x)))} sx={{ mt: 1 }} />
                  <TextField fullWidth multiline minRows={2} label="Next steps / follow-ups (one per line)" value={r.next_steps} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, next_steps: e.target.value } : x)))} sx={{ mt: 1 }} />
                </Box>
              ))}
              <FormControlLabel control={<Checkbox checked={escalate} onChange={(e) => setEscalate(e.target.checked)} />} label="Escalate to supervisor for sign-off" />
              {escalate && <TextField fullWidth label="Escalation reason" value={escReason} onChange={(e) => setEscReason(e.target.value)} sx={{ mb: 1 }} />}
              <Stack direction="row" justifyContent="flex-end">
                <Button variant="contained" size="large" disabled={!rows.length || rows.some((r) => r.outcome.length < 2 || r.rationale.length < 10) || pendingIds.length > 0 || submit.isPending}
                  onClick={() => submit.mutate({ id: hitl4.review!.id, body: { decisions: rows.map((r) => ({ ...r, next_steps: r.next_steps.split("\n").map((s) => s.trim()).filter(Boolean) })), escalate, escalation_reason: escalate ? escReason : undefined } })}>
                  Submit decision{pendingIds.length ? ` (${pendingIds.length} flags pending)` : ""}
                </Button>
              </Stack>
            </Section>
          </Grid>
        )}
      </Grid>
      <Section title="Decision record">
        {(decisions.data?.decisions ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No decisions recorded yet.</Typography>}
        {(decisions.data?.decisions ?? []).map((d: any) => (
          <Box key={d.id} sx={{ mb: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center"><StatusChip status={d.status} /><Typography variant="subtitle2">{d.decision_type.replace(/_/g, " ")}: {d.outcome}</Typography></Stack>
            <Typography variant="body2">{d.rationale}</Typography>
            <Typography variant="caption" color="text.secondary">Decided by {d.decided_by_name ?? "-"} {fmtDateTime(d.decided_at)}{d.signed_off_by_name ? ` - signed off by ${d.signed_off_by_name} ${fmtDateTime(d.signed_off_at)}` : ""}{d.record_hash ? ` - record hash ${d.record_hash.slice(0, 16)}...` : ""}</Typography>
          </Box>
        ))}
        {(decisions.data?.ur_determinations ?? []).map((u: any) => (
          <Typography key={u.id} variant="body2"><StatusChip status={u.determination} /> UR by {u.reviewer_name}: {u.clinical_rationale}</Typography>
        ))}
      </Section>
    </Box>
  );
}
