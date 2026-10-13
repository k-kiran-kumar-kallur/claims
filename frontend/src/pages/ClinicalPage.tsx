import { Box, Button, Chip, Grid2 as Grid, LinearProgress, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CitationList, CitedMarkdown } from "../components/CitationViewer";
import { AiDraftBadge, EmptyState, ErrorAlert, Section, SeverityChip, StatusChip } from "../components/common";
import { useSummaries } from "../hooks/queries";

export default function ClinicalPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const summaries = useSummaries(claimId);
  const issues = useQuery({ queryKey: ["issues", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/clinical-issues`) });
  const ua = useQuery({ queryKey: ["ua", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/utilization-assessments`), enabled: can("ur:determine", "decision:make", "decision:signoff", "timeline:approve") });
  const updateIssue = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => api.patch(`/clinical-issues/${id}`, { status }), onSuccess: () => qc.invalidateQueries({ queryKey: ["issues", claimId] }) });
  const clinical = summaries.data?.find((s) => s.summary_type === "clinical");
  const facts = summaries.data?.find((s) => s.summary_type === "case_facts");
  if (summaries.isLoading) return <LinearProgress />;
  return (
    <Box>
      <ErrorAlert error={summaries.error || issues.error || updateIssue.error} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Clinical summary (Stage 3)" actions={clinical && <AiDraftBadge label={clinical.status === "approved" ? "Approved" : "AI draft"} />}>
            {clinical ? (
              <>
                <CitedMarkdown md={clinical.content_md} citations={clinical.citations} claimId={claimId} />
                {clinical.content_json?.subjective_only?.length > 0 && (
                  <Typography variant="caption" color="warning.main" display="block" sx={{ mt: 1 }}>{clinical.content_json.subjective_only.length} statement(s) rest on subjective report only (no objective corroboration).</Typography>
                )}
              </>
            ) : <EmptyState title="Clinical summary not generated yet" />}
          </Section>
          {facts && (
            <Section title="Case-fact narrative arc (Stage 5, PW-5.1)">
              <CitedMarkdown md={facts.content_md} citations={facts.citations} claimId={claimId} />
            </Section>
          )}
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title="Clinical issues (PW-3.3)">
            {(issues.data ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No issues identified.</Typography>}
            {(issues.data ?? []).map((i) => (
              <Box key={i.id} sx={{ mb: 1.5, pb: 1.5, borderBottom: "1px solid", borderColor: "divider" }}>
                <Stack direction="row" spacing={1} alignItems="center"><SeverityChip severity={i.severity} /><Chip label={i.issue_type.replace(/_/g, " ")} size="small" variant="outlined" /><StatusChip status={i.status} /></Stack>
                <Typography variant="body2" sx={{ mt: 0.5 }}>{i.description}</Typography>
                <Typography variant="caption" color="text.secondary" display="block">Suggested: {i.suggested_action}</Typography>
                <CitationList citations={i.citations} claimId={claimId} />
                {can("fact:validate", "care:coordinate", "timeline:approve") && (
                  <TextField select size="small" value={i.status} onChange={(e) => updateIssue.mutate({ id: i.id, status: e.target.value })} sx={{ mt: 0.5, minWidth: 140 }}>
                    {["open", "in_progress", "resolved", "dismissed"].map((s) => <MenuItem key={s} value={s}>{s.replace("_", " ")}</MenuItem>)}
                  </TextField>
                )}
              </Box>
            ))}
          </Section>
          {ua.data && (
            <Section title="Utilization assessments" actions={<AiDraftBadge />}>
              {ua.data.length === 0 && <Typography variant="body2" color="text.secondary">No provider requests found.</Typography>}
              {ua.data.map((u) => (
                <Box key={u.id} sx={{ mb: 2 }}>
                  <Typography variant="subtitle2">{u.request_description}</Typography>
                  <Typography variant="caption" color="text.secondary">{u.request_type} - {u.requesting_provider}</Typography>
                  {(u.necessity_indicators ?? []).map((n: any, k: number) => (
                    <Stack key={k} direction="row" spacing={1} alignItems="flex-start" sx={{ mt: 0.5 }}>
                      <Chip size="small" label={n.supports_necessity ? "supports" : "against"} color={n.supports_necessity ? "success" : "error"} variant="outlined" />
                      <Typography variant="body2" sx={{ flex: 1 }}>{n.indicator} {n.guideline_rule_code && <Chip size="small" label={n.guideline_rule_code} />}</Typography>
                      <CitationList citations={n.citations} claimId={claimId} />
                    </Stack>
                  ))}
                  <Typography variant="body2" sx={{ mt: 1 }}><b>Appropriateness:</b> {u.appropriateness}</Typography>
                  <Typography variant="body2"><b>Progression:</b> {u.progression}</Typography>
                  {u.barriers?.length > 0 && <Typography variant="body2"><b>Barriers:</b> {u.barriers.join("; ")}</Typography>}
                  {u.unresolved_questions?.length > 0 && <Typography variant="body2"><b>Open questions:</b> {u.unresolved_questions.join("; ")}</Typography>}
                  <Typography variant="body2" sx={{ mt: 0.5, p: 1, bgcolor: "#fff8e6", borderRadius: 1 }}>{u.ai_recommendation}</Typography>
                  {u.determination && <Typography variant="body2" sx={{ mt: 0.5 }}><StatusChip status={u.determination.determination} /> by {u.determination.reviewer_name}: {u.determination.clinical_rationale}</Typography>}
                </Box>
              ))}
            </Section>
          )}
        </Grid>
      </Grid>
      {can("ur:determine") && <Button href={`/claims/${claimId}/decision`}>Go to UR determination</Button>}
    </Box>
  );
}
