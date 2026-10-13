import { Box, Button, Card, CardActions, CardContent, Chip, LinearProgress, Stack, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CitationList } from "../components/CitationViewer";
import { EmptyState, ErrorAlert, ReasonDialog, SeverityChip, StatusChip } from "../components/common";

export default function GuidelinesPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["findings", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/guideline-findings`) });
  const [dismiss, setDismiss] = useState<any>(null);
  const m = useMutation({ mutationFn: ({ id, status, reason }: { id: string; status: string; reason?: string }) => api.patch(`/guideline-findings/${id}`, { status, reason }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["findings", claimId] }); qc.invalidateQueries({ queryKey: ["flags", claimId] }); } });
  if (q.isLoading) return <LinearProgress />;
  const rows = q.data ?? [];
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Treatment and guideline review (Stage 5). Every finding cites a rule from the loaded guideline store; the AI never relies on model memory for guideline criteria.
      </Typography>
      <ErrorAlert error={q.error || m.error} />
      {rows.length === 0 && <EmptyState title="No guideline findings yet" />}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
        {rows.map((f) => (
          <Card key={f.id} variant="outlined" sx={{ borderLeft: 4, borderLeftColor: f.finding_type === "compliant" ? "success.main" : f.severity === "high" ? "error.main" : f.severity === "medium" ? "warning.main" : "info.main" }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
                <Chip label={f.finding_type.replace(/_/g, " ")} color={f.finding_type === "compliant" ? "success" : "default"} />
                <SeverityChip severity={f.severity} /><StatusChip status={f.status} />
              </Stack>
              <Typography variant="subtitle1" fontWeight={650}>{f.title}</Typography>
              <Typography variant="body2" sx={{ mt: 0.5 }}>{f.explanation}</Typography>
              {f.recommendation && <Typography variant="body2" sx={{ mt: 0.5 }}><b>Recommendation:</b> {f.recommendation}</Typography>}
              {f.metrics && Object.keys(f.metrics).length > 0 && (
                <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                  {Object.entries(f.metrics).filter(([, v]) => v !== null && v !== false && !Array.isArray(v)).map(([k, v]) => <Chip key={k} size="small" variant="outlined" label={`${k.replace(/_/g, " ")}: ${v}`} />)}
                </Stack>
              )}
              {f.rule_excerpt && <Box sx={{ mt: 1, p: 1, bgcolor: "#f7f9fc", borderRadius: 1 }}><Typography variant="caption" color="text.secondary">Guideline rule {f.rule?.recommendation ? `(${f.rule.recommendation})` : ""}</Typography><Typography variant="body2">{f.rule_excerpt}</Typography></Box>}
              <Box sx={{ mt: 1 }}>Evidence: <CitationList citations={f.citations} claimId={claimId} /></Box>
              {f.review_reason && <Typography variant="caption" color="text.secondary">Reviewer note: {f.review_reason}</Typography>}
            </CardContent>
            {can("flag:act", "fact:validate") && f.status === "open" && !["compliant", "no_applicable_guideline"].includes(f.finding_type) && (
              <CardActions>
                <Button size="small" variant="contained" onClick={() => m.mutate({ id: f.id, status: "accepted" })}>Accept</Button>
                <Button size="small" onClick={() => setDismiss(f)}>Dismiss</Button>
              </CardActions>
            )}
          </Card>
        ))}
      </Box>
      <ReasonDialog open={!!dismiss} title="Dismiss guideline finding" onClose={() => setDismiss(null)} confirmText="Dismiss"
        onConfirm={(reason) => { m.mutate({ id: dismiss.id, status: "dismissed", reason }); setDismiss(null); }} />
    </Box>
  );
}
