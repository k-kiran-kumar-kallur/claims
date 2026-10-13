import { Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid, LinearProgress, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CitationList } from "../components/CitationViewer";
import { asList, ErrorAlert, fmtDate, fmtDateTime, Section, SeverityChip, StatusChip } from "../components/common";

const LEVEL: Record<string, number> = { ttd: 0, off_work: 0, tpd: 1, modified_duty: 2, full_duty: 3 };

export default function RtwPage() {
  const { claimId } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const rtw = useQuery({ queryKey: ["rtw", claimId], queryFn: () => api.get<any>(`/claims/${claimId}/rtw-status`) });
  const gaps = useQuery({ queryKey: ["timeline", claimId], queryFn: () => api.get<any>(`/claims/${claimId}/timeline`) });
  const providers = useQuery({ queryKey: ["providers", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/providers`) });
  const contacts = useQuery({ queryKey: ["contacts", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/provider-contacts`) });
  const followUps = useQuery({ queryKey: ["follow-ups", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/follow-ups`) });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({ contact_type: "call", purpose: "treatment coordination" });
  const add = useMutation({ mutationFn: () => api.post(`/claims/${claimId}/provider-contacts`, { ...form, follow_up_date: form.follow_up_date || undefined }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["contacts", claimId] }); } });
  const done = useMutation({ mutationFn: (id: string) => api.patch(`/follow-ups/${id}`, { status: "done" }), onSuccess: () => followUps.refetch() });
  if (rtw.isLoading) return <LinearProgress />;
  const history = rtw.data?.history ?? [];
  const chart = history.map((h: any) => ({ date: h.effective_date, level: LEVEL[h.work_status] ?? 0, status: h.work_status }));
  const delays = (gaps.data?.gaps ?? []).filter((g: any) => g.status === "open");
  return (
    <Box>
      <ErrorAlert error={rtw.error || add.error} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Return-to-work trajectory">
            {chart.length > 1 && (
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={chart} margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={fmtDate} fontSize={11} />
                  <YAxis domain={[0, 3]} ticks={[0, 1, 2, 3]} tickFormatter={(v) => ["Off work", "TPD", "Modified", "Full duty"][v]} width={80} fontSize={11} />
                  <Tooltip labelFormatter={fmtDate} formatter={(_, __, p: any) => [p.payload.status.replace("_", " "), "Work status"]} />
                  <Line type="stepAfter" dataKey="level" stroke="#0f766e" strokeWidth={2} dot />
                </LineChart>
              </ResponsiveContainer>
            )}
            <Table size="small">
              <TableHead><TableRow><TableCell>Effective</TableCell><TableCell>Status</TableCell><TableCell>Restrictions</TableCell><TableCell>Employer accommodation</TableCell><TableCell>Source</TableCell></TableRow></TableHead>
              <TableBody>
                {history.map((h: any) => (
                  <TableRow key={h.id}>
                    <TableCell>{fmtDate(h.effective_date)}</TableCell>
                    <TableCell><StatusChip status={h.work_status} /></TableCell>
                    <TableCell>{asList(h.restrictions).map((r: any, i: number) => <Chip key={i} size="small" variant="outlined" sx={{ m: 0.25 }} label={r.limit_lb ? `lift ${r.limit_lb} lb ${r.frequency ?? ""}` : r.max_hours_per_day ? `${r.max_hours_per_day} h/day` : r.alternate_every_minutes ? `sit/stand q${r.alternate_every_minutes}min` : r.limit ?? r.type} />)}</TableCell>
                    <TableCell><Typography variant="caption">{h.employer_accommodation ?? "-"}</Typography></TableCell>
                    <TableCell><CitationList citations={h.citations} claimId={claimId} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {(rtw.data?.work_capacity ?? []).map((w: any) => <Typography key={w.id} variant="body2" sx={{ mt: 1 }}><b>{w.label}</b> ({fmtDate(w.effective_date)}) <StatusChip status={w.validation_status} /></Typography>)}
          </Section>
          <Section title="Care delays and gaps">
            {delays.length === 0 && <Typography variant="body2" color="text.secondary">No open gaps or delays in care.</Typography>}
            {delays.map((g: any) => <Stack key={g.id} direction="row" spacing={1} sx={{ mb: 0.75 }}><SeverityChip severity={g.severity} /><Typography variant="body2">{g.description}</Typography></Stack>)}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title="Provider directory">
            {(providers.data ?? []).map((p) => (
              <Box key={p.id} sx={{ mb: 1 }}>
                <Typography variant="body2" fontWeight={600}>{p.name}</Typography>
                <Typography variant="caption" color="text.secondary">{[p.specialty, p.facility, p.phone, p.fax].filter(Boolean).join(" - ")} - seen {fmtDate(p.first_seen)} to {fmtDate(p.last_seen)}</Typography>
              </Box>
            ))}
          </Section>
          <Section title="Provider contact log" actions={can("care:coordinate") && <Button onClick={() => setOpen(true)}>Log contact</Button>}>
            {(contacts.data ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No contacts logged.</Typography>}
            {(contacts.data ?? []).map((c) => (
              <Box key={c.id} sx={{ mb: 1 }}>
                <Typography variant="body2"><b>{c.provider_name}</b> - {c.contact_type} - {c.purpose}</Typography>
                <Typography variant="caption" color="text.secondary">{fmtDateTime(c.contacted_at)} by {c.contacted_by_name}{c.follow_up_date ? ` - follow up ${fmtDate(c.follow_up_date)}` : ""}</Typography>
                {c.notes && <Typography variant="body2">{c.notes}</Typography>}
              </Box>
            ))}
          </Section>
          <Section title="Follow-ups (diary)">
            {(followUps.data ?? []).length === 0 && <Typography variant="body2" color="text.secondary">No follow-ups.</Typography>}
            {(followUps.data ?? []).map((f) => (
              <Stack key={f.id} direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
                <StatusChip status={f.status} /><Typography variant="body2" sx={{ flex: 1 }}>{f.action} <Typography component="span" variant="caption" color="text.secondary">due {fmtDate(f.due_date)} - {f.owner_name ?? ""}</Typography></Typography>
                {f.status === "open" && can("care:coordinate", "decision:make") && <Button size="small" onClick={() => done.mutate(f.id)}>Done</Button>}
              </Stack>
            ))}
          </Section>
        </Grid>
      </Grid>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Log provider contact</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField select label="Provider" value={form.provider_id ?? ""} onChange={(e) => setForm({ ...form, provider_id: e.target.value })}>
              {(providers.data ?? []).map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
            </TextField>
            <TextField select label="Contact type" value={form.contact_type} onChange={(e) => setForm({ ...form, contact_type: e.target.value })}>
              {["call", "fax", "email", "meeting"].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
            </TextField>
            <TextField select label="Purpose" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })}>
              {["records request", "treatment coordination", "RTW discussion"].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
            </TextField>
            <TextField multiline minRows={2} label="Notes" value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <TextField type="date" label="Follow-up date" InputLabelProps={{ shrink: true }} value={form.follow_up_date ?? ""} onChange={(e) => setForm({ ...form, follow_up_date: e.target.value })} />
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="contained" disabled={!form.provider_id} onClick={() => add.mutate()}>Save</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
