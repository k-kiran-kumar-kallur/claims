import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, LinearProgress, MenuItem, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CitationList } from "../components/CitationViewer";
import { EmptyState, ErrorAlert, fmtDate, Section, SeverityChip, StatusChip } from "../components/common";
import { usePendingReview, useSubmitReview } from "../hooks/queries";

const day = (iso?: string | null) => (iso ? new Date(iso + "T00:00:00Z").getTime() / 864e5 : null);

function TimelineChart({ episodes }: { episodes: any[] }) {
  const data = episodes.filter((e) => e.start_date).map((e) => {
    const s = day(e.start_date)!, en = day(e.end_date ?? e.start_date)!;
    return { label: e.label.replace(/\s*\(.*\)$/, ""), offset: s, span: Math.max(en - s, 3), docs: e.documents.length, start: e.start_date, end: e.end_date };
  });
  if (!data.length) return null;
  const min = Math.min(...data.map((d) => d.offset)) - 5, max = Math.max(...data.map((d) => d.offset + d.span)) + 5;
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 34 + 40)}>
      <BarChart layout="vertical" data={data} margin={{ left: 10, right: 20 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" domain={[min, max]} allowDataOverflow scale="linear" tickFormatter={(v) => new Date(v * 864e5).toLocaleDateString(undefined, { month: "short", year: "2-digit" })} fontSize={11} />
        <YAxis type="category" dataKey="label" width={210} fontSize={11} />
        <RTooltip formatter={(_, __, p: any) => [`${fmtDate(p.payload.start)} - ${fmtDate(p.payload.end)} (${p.payload.docs} docs)`, "Episode"]} />
        <Bar dataKey="offset" stackId="a" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="span" stackId="a" fill="#2f6bc0" radius={[3, 3, 3, 3]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function TimelinePage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const tl = useQuery({ queryKey: ["timeline", claimId], queryFn: () => api.get<any>(`/claims/${claimId}/timeline`) });
  const { review } = usePendingReview(claimId, "HITL-1");
  const submit = useSubmitReview(claimId);
  const [editEp, setEditEp] = useState<any>(null);
  const [epLabel, setEpLabel] = useState("");
  const [mergeInto, setMergeInto] = useState("");
  const [gap, setGap] = useState<any>(null);
  const [gapStatus, setGapStatus] = useState("explained");
  const [gapNote, setGapNote] = useState("");
  const [reclassify, setReclassify] = useState<string[]>([]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["timeline", claimId] });
  const epMut = useMutation({ mutationFn: () => api.patch(`/claims/${claimId}/episodes/${editEp.id}`, { label: epLabel || undefined, merge_into: mergeInto || undefined }), onSuccess: () => { setEditEp(null); refresh(); } });
  const gapMut = useMutation({ mutationFn: () => api.patch(`/claims/${claimId}/gaps/${gap.id}`, { status: gapStatus, resolution_note: gapNote }), onSuccess: () => { setGap(null); setGapNote(""); refresh(); } });
  const flagged = useMemo(() => (tl.data?.episodes ?? []).flatMap((e: any) => e.documents.filter((d: any) => d.needs_attention)), [tl.data]);
  if (tl.isLoading) return <LinearProgress />;
  if (tl.error) return <ErrorAlert error={tl.error} />;
  const t = tl.data;
  if (!t.timeline_version) return <EmptyState title="Timeline not built yet" hint="The Organization Agent builds it after classification (Stage 2)." />;
  const canEdit = can("timeline:approve", "classification:edit");
  return (
    <Box>
      {review && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <b>HITL-1 Timeline check.</b> Verify every required record is present and the sequence captures the clinical timeline. Correct document types on the Documents tab (then submit "Corrections"), merge or rename episodes, explain gaps, or wait for requested records.
        </Alert>
      )}
      <ErrorAlert error={submit.error || epMut.error || gapMut.error} />
      <Section title={`Clinical timeline (version ${t.timeline_version})`} actions={<Chip label={`${t.episodes.length} episodes`} />}>
        <TimelineChart episodes={t.episodes} />
      </Section>
      {t.episodes.map((e: any) => (
        <Section key={e.id} dense title={<Stack direction="row" spacing={1} alignItems="center"><span>{e.label}</span><Chip size="small" label={e.episode_type} variant="outlined" />{e.edited_by && <Chip size="small" label="edited" color="primary" variant="outlined" />}</Stack>}
          actions={canEdit && <Tooltip title="Rename or merge episode"><IconButton size="small" onClick={() => { setEditEp(e); setEpLabel(e.label); setMergeInto(""); }}><EditIcon fontSize="small" /></IconButton></Tooltip>}>
          <Table size="small">
            <TableBody>
              {e.documents.map((d: any) => (
                <TableRow key={d.document_id} hover sx={{ cursor: "pointer", bgcolor: d.needs_attention ? "#fffaeb" : undefined }}>
                  <TableCell sx={{ width: 100 }}>{fmtDate(d.date)}</TableCell>
                  <TableCell onClick={() => navigate(`/claims/${claimId}/viewer/${d.document_id}`)}>{d.doc_type}<Typography variant="caption" display="block" color="text.secondary">{d.title}</Typography></TableCell>
                  <TableCell>{d.provider ?? "-"}</TableCell>
                  <TableCell>{d.confidence != null && <Chip size="small" variant="outlined" color={d.needs_attention ? "warning" : "default"} label={`${Math.round(d.confidence * 100)}%`} />}</TableCell>
                  <TableCell sx={{ width: 160 }}>
                    {review && <Button size="small" color={reclassify.includes(d.document_id) ? "warning" : "inherit"}
                      onClick={() => setReclassify(reclassify.includes(d.document_id) ? reclassify.filter((x) => x !== d.document_id) : [...reclassify, d.document_id])}>
                      {reclassify.includes(d.document_id) ? "Marked for re-check" : "Mark for re-check"}</Button>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      ))}
      <Section title="Gaps, delays and missing records">
        {t.gaps.length === 0 ? <Typography variant="body2" color="text.secondary">No gaps detected - chronological integrity confirmed.</Typography> : (
          <Table size="small">
            <TableHead><TableRow><TableCell>Type</TableCell><TableCell>Description</TableCell><TableCell>Severity</TableCell><TableCell>Status</TableCell><TableCell>Evidence</TableCell><TableCell /></TableRow></TableHead>
            <TableBody>
              {t.gaps.map((g: any) => (
                <TableRow key={g.id}>
                  <TableCell>{g.gap_type.replace(/_/g, " ")}</TableCell>
                  <TableCell>{g.description}{g.resolution_note && <Typography variant="caption" display="block" color="text.secondary">Note: {g.resolution_note}</Typography>}</TableCell>
                  <TableCell><SeverityChip severity={g.severity} /></TableCell>
                  <TableCell><StatusChip status={g.status} /></TableCell>
                  <TableCell><CitationList citations={g.evidence} claimId={claimId} /></TableCell>
                  <TableCell>{can("timeline:approve", "care:coordinate") && <Button size="small" onClick={() => { setGap(g); setGapStatus(g.status === "open" ? "explained" : g.status); }}>Update</Button>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
      <Section title="Removed from the timeline (duplicates and administrative noise)" dense>
        {t.removed_documents.map((d: any) => <Typography key={d.document_id} variant="body2">- {d.title} <StatusChip status={d.status} /> <Typography component="span" variant="caption" color="text.secondary">{d.reason}</Typography></Typography>)}
      </Section>
      {review?.can_act && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="flex-end">
          {flagged.length > 0 && <Typography variant="body2" color="warning.main" sx={{ alignSelf: "center" }}>{flagged.length} low-confidence classification(s) highlighted</Typography>}
          <Button onClick={() => submit.mutate({ id: review.id, body: { decision: "await_documents" } })}>Wait for requested records</Button>
          <Button color="warning" variant="outlined" disabled={!reclassify.length} onClick={() => submit.mutate({ id: review.id, body: { decision: "corrections", reclassify_document_ids: reclassify } })}>Submit corrections ({reclassify.length})</Button>
          <Button variant="contained" onClick={() => submit.mutate({ id: review.id, body: { decision: "approve" } })} disabled={submit.isPending}>Approve timeline</Button>
        </Stack>
      )}
      <Dialog open={!!editEp} onClose={() => setEditEp(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit episode</DialogTitle>
        <DialogContent>
          <TextField fullWidth label="Label" value={epLabel} onChange={(e) => setEpLabel(e.target.value)} sx={{ my: 1 }} />
          <TextField select fullWidth label="Merge into another episode (optional)" value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}>
            <MenuItem value="">Do not merge</MenuItem>
            {t.episodes.filter((x: any) => x.id !== editEp?.id).map((x: any) => <MenuItem key={x.id} value={x.id}>{x.label}</MenuItem>)}
          </TextField>
        </DialogContent>
        <DialogActions><Button onClick={() => setEditEp(null)}>Cancel</Button><Button variant="contained" onClick={() => epMut.mutate()}>Save</Button></DialogActions>
      </Dialog>
      <Dialog open={!!gap} onClose={() => setGap(null)} fullWidth maxWidth="sm">
        <DialogTitle>Resolve gap</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>{gap?.description}</Typography>
          <TextField select fullWidth label="Status" value={gapStatus} onChange={(e) => setGapStatus(e.target.value)} sx={{ mb: 2 }}>
            {["open", "explained", "requested", "resolved"].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
          </TextField>
          <TextField fullWidth multiline minRows={2} label="Resolution note" value={gapNote} onChange={(e) => setGapNote(e.target.value)} />
        </DialogContent>
        <DialogActions><Button onClick={() => setGap(null)}>Cancel</Button><Button variant="contained" onClick={() => gapMut.mutate()}>Save</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
