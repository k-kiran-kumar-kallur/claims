import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid, LinearProgress, MenuItem, Paper, Stack, Switch, Tab, Table,
  TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography, Checkbox, ListItemText, Select, OutlinedInput,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../../api/client";
import { ROLE_LABELS, type User } from "../../api/types";
import { ErrorAlert, fmtDateTime, PageHeader, Section } from "../../components/common";
import { AuditTable } from "../AuditPage";

function UsersTab() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get<User[]>("/admin/users") });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{ email: string; full_name: string; password: string; roles: string[] }>({ email: "", full_name: "", password: "", roles: [] });
  const create = useMutation({ mutationFn: () => api.post("/admin/users", form), onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["admin-users"] }); } });
  const patch = useMutation({ mutationFn: ({ id, body }: { id: string; body: any }) => api.patch(`/admin/users/${id}`, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }) });
  return (
    <Section title="Users and roles" actions={<Button variant="contained" onClick={() => setOpen(true)}>Add user</Button>}>
      <ErrorAlert error={users.error || patch.error} />
      <Table size="small">
        <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Email</TableCell><TableCell>Roles</TableCell><TableCell>MFA</TableCell><TableCell>Last login</TableCell><TableCell>Active</TableCell></TableRow></TableHead>
        <TableBody>
          {(users.data ?? []).map((u) => (
            <TableRow key={u.id}>
              <TableCell>{u.full_name}</TableCell><TableCell>{u.email}</TableCell>
              <TableCell>
                <Select multiple size="small" value={u.roles} onChange={(e) => patch.mutate({ id: u.id, body: { roles: e.target.value } })} input={<OutlinedInput />}
                  renderValue={(v) => (v as string[]).map((r) => ROLE_LABELS[r] ?? r).join(", ")} sx={{ minWidth: 220 }}>
                  {Object.keys(ROLE_LABELS).map((r) => <MenuItem key={r} value={r}><Checkbox size="small" checked={u.roles.includes(r)} /><ListItemText primary={ROLE_LABELS[r]} /></MenuItem>)}
                </Select>
              </TableCell>
              <TableCell>{u.mfa_enabled ? <Chip size="small" color="success" label="on" /> : <Chip size="small" label="off" />}</TableCell>
              <TableCell>{fmtDateTime(u.last_login_at)}</TableCell>
              <TableCell><Switch checked={!!u.is_active} onChange={(e) => patch.mutate({ id: u.id, body: { is_active: e.target.checked } })} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add user</DialogTitle>
        <DialogContent>
          <ErrorAlert error={create.error} />
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            <TextField label="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <TextField label="Initial password" type="password" helperText="Min 10 chars with upper, lower case and digits" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <Select multiple value={form.roles} onChange={(e) => setForm({ ...form, roles: e.target.value as string[] })} displayEmpty renderValue={(v) => (v as string[]).length ? (v as string[]).map((r) => ROLE_LABELS[r]).join(", ") : "Select roles"}>
              {Object.keys(ROLE_LABELS).map((r) => <MenuItem key={r} value={r}><Checkbox size="small" checked={form.roles.includes(r)} /><ListItemText primary={ROLE_LABELS[r]} /></MenuItem>)}
            </Select>
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="contained" onClick={() => create.mutate()}>Create</Button></DialogActions>
      </Dialog>
    </Section>
  );
}

function GuidelinesTab() {
  const qc = useQueryClient();
  const sources = useQuery({ queryKey: ["g-sources"], queryFn: () => api.get<any[]>("/admin/guidelines/sources") });
  const [source, setSource] = useState("");
  const rules = useQuery({ queryKey: ["g-rules", source], queryFn: () => api.get<any[]>(`/admin/guidelines/rules${qs({ source_id: source })}`) });
  const [file, setFile] = useState<File | null>(null);
  const [newSource, setNewSource] = useState({ name: "", edition: "", jurisdiction: "", license_ref: "" });
  const imp = useMutation({ mutationFn: () => { const fd = new FormData(); fd.append("file", file!); return api.post<any>(`/admin/guidelines/rules/import?source_id=${source}`, fd); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["g-rules"] }); qc.invalidateQueries({ queryKey: ["g-sources"] }); } });
  const add = useMutation({ mutationFn: () => api.post("/admin/guidelines/sources", newSource), onSuccess: () => qc.invalidateQueries({ queryKey: ["g-sources"] }) });
  return (
    <Box>
      <Alert severity="info" sx={{ mb: 2 }}>Guideline criteria come only from this store. The bundled rule set is a curated sample for the PoC, not licensed ODG/ACOEM content; import licensed content here before production use.</Alert>
      <ErrorAlert error={imp.error || add.error} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Section title="Sources">
            {(sources.data ?? []).map((s) => (
              <Box key={s.id} sx={{ mb: 1, p: 1, borderRadius: 1, cursor: "pointer", bgcolor: source === s.id ? "primary.light" : undefined }} onClick={() => setSource(s.id)}>
                <Typography variant="body2" fontWeight={600}>{s.name} <Chip size="small" label={`${s.rule_count} rules`} /></Typography>
                <Typography variant="caption" color="text.secondary">{s.edition} - {s.jurisdiction} - {s.license_ref}</Typography>
              </Box>
            ))}
            <Typography variant="subtitle2" sx={{ mt: 2 }}>Add source</Typography>
            <Stack spacing={1} sx={{ mt: 1 }}>
              {(["name", "edition", "jurisdiction", "license_ref"] as const).map((k) => <TextField key={k} label={k.replace("_", " ")} value={newSource[k]} onChange={(e) => setNewSource({ ...newSource, [k]: e.target.value })} />)}
              <Button onClick={() => add.mutate()} disabled={newSource.name.length < 2}>Add source</Button>
            </Stack>
          </Section>
          {source && (
            <Section title="Import rules (CSV or JSON)">
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>Columns: rule_code, title, category, body_part, diagnosis_codes, procedure_codes, keywords, criteria_text, max_visits, max_duration_days, prerequisites, recommendation (lists ';'-separated).</Typography>
              <input type="file" accept=".csv,.json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <Button variant="contained" sx={{ ml: 1 }} disabled={!file} onClick={() => imp.mutate()}>Import</Button>
              {imp.data && <Alert severity={imp.data.errors.length ? "warning" : "success"} sx={{ mt: 1 }}>Imported {imp.data.imported}; {imp.data.errors.length} error(s){imp.data.errors.slice(0, 3).map((e: any) => ` - row ${e.row}: ${e.error}`)}</Alert>}
            </Section>
          )}
        </Grid>
        <Grid size={{ xs: 12, md: 7 }}>
          <Section title="Rules">
            <Table size="small">
              <TableHead><TableRow><TableCell>Code</TableCell><TableCell>Title</TableCell><TableCell>Limits</TableCell><TableCell>Recommendation</TableCell></TableRow></TableHead>
              <TableBody>
                {(rules.data ?? []).map((r) => (
                  <TableRow key={r.id}><TableCell><Typography variant="caption" fontFamily="monospace">{r.rule_code}</Typography></TableCell><TableCell>{r.title}<Typography variant="caption" display="block" color="text.secondary">{r.criteria_text}</Typography></TableCell>
                    <TableCell>{[r.max_visits && `${r.max_visits} visits`, r.max_duration_days && `${r.max_duration_days} days`].filter(Boolean).join(", ") || "-"}</TableCell><TableCell>{r.recommendation}</TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        </Grid>
      </Grid>
    </Box>
  );
}

function ConfigTab() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: () => api.get<any>("/admin/settings") });
  const prompts = useQuery({ queryKey: ["admin-prompts"], queryFn: () => api.get<any[]>("/admin/prompts") });
  const [thr, setThr] = useState<Record<string, string>>({});
  const [models, setModels] = useState<Record<string, string>>({});
  const [edit, setEdit] = useState<any>(null);
  const save = useMutation({ mutationFn: () => api.put("/admin/settings", {
    thresholds: Object.keys(thr).length ? Object.fromEntries(Object.entries(thr).map(([k, v]) => [k, Number(v)])) : undefined,
    models: Object.keys(models).length ? models : undefined }), onSuccess: () => { setThr({}); setModels({}); qc.invalidateQueries({ queryKey: ["admin-settings"] }); } });
  const publish = useMutation({ mutationFn: () => api.put("/admin/prompts", { name: edit.name, version: edit.version, template: edit.template, system: edit.system, model_tier: edit.model_tier, temperature: Number(edit.temperature) }),
    onSuccess: () => { setEdit(null); qc.invalidateQueries({ queryKey: ["admin-prompts"] }); } });
  const active = (prompts.data ?? []).filter((p) => p.is_active);
  return (
    <Box>
      <ErrorAlert error={save.error || publish.error} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Section title="Thresholds" actions={<Button variant="contained" onClick={() => save.mutate()} disabled={!Object.keys(thr).length && !Object.keys(models).length}>Save</Button>}>
            {Object.entries(settings.data?.thresholds ?? {}).map(([k, v]) => (
              <TextField key={k} fullWidth label={k.replace(/_/g, " ").toLowerCase()} defaultValue={String(v)} onChange={(e) => setThr({ ...thr, [k]: e.target.value })} sx={{ mb: 1.5 }} />
            ))}
            <Typography variant="subtitle2" sx={{ mt: 1 }}>Model tiers (override .env)</Typography>
            {["fast", "reasoning"].map((k) => <TextField key={k} fullWidth label={`${k} model`} placeholder={settings.data?.models?.[k] ?? "from GEMINI_CHAT_MODEL"} defaultValue={settings.data?.models?.[k] ?? ""} onChange={(e) => setModels({ ...models, [k]: e.target.value })} sx={{ mt: 1.5 }} />)}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 7 }}>
          <Section title="Prompt templates (versioned)">
            <Table size="small">
              <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Version</TableCell><TableCell>Tier</TableCell><TableCell>Temp.</TableCell><TableCell /></TableRow></TableHead>
              <TableBody>
                {active.map((p) => (
                  <TableRow key={p.id}><TableCell>{p.name}</TableCell><TableCell>{p.version}</TableCell><TableCell>{p.model_tier}</TableCell><TableCell>{p.temperature}</TableCell>
                    <TableCell><Button size="small" onClick={() => setEdit({ ...p, version: String(Number(p.version) + 1 || `${p.version}.1`) })}>New version</Button></TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        </Grid>
      </Grid>
      <Dialog open={!!edit} onClose={() => setEdit(null)} fullWidth maxWidth="md">
        <DialogTitle>Publish prompt {edit?.name}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Stack direction="row" spacing={1}>
              <TextField label="Version" value={edit?.version ?? ""} onChange={(e) => setEdit({ ...edit, version: e.target.value })} />
              <TextField select label="Tier" value={edit?.model_tier ?? "fast"} onChange={(e) => setEdit({ ...edit, model_tier: e.target.value })} sx={{ minWidth: 140 }}><MenuItem value="fast">fast</MenuItem><MenuItem value="reasoning">reasoning</MenuItem></TextField>
              <TextField label="Temperature" value={edit?.temperature ?? 0} onChange={(e) => setEdit({ ...edit, temperature: e.target.value })} />
            </Stack>
            <TextField label="System instructions" multiline minRows={4} value={edit?.system ?? ""} onChange={(e) => setEdit({ ...edit, system: e.target.value })} />
            <TextField label="Template (Jinja2)" multiline minRows={6} value={edit?.template ?? ""} onChange={(e) => setEdit({ ...edit, template: e.target.value })} InputProps={{ sx: { fontFamily: "monospace", fontSize: 12 } }} />
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="contained" onClick={() => publish.mutate()}>Publish</Button></DialogActions>
      </Dialog>
    </Box>
  );
}

function SystemTab() {
  const sys = useQuery({ queryKey: ["admin-system"], queryFn: () => api.get<any>("/admin/system"), refetchInterval: 15000 });
  const health = useQuery({ queryKey: ["health"], queryFn: () => fetch("/api/v1/health/ready").then((r) => r.json()), refetchInterval: 15000 });
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const audit = useQuery({ queryKey: ["admin-audit", page, pageSize], queryFn: () => api.getEnv<any[]>(`/audit${qs({ page: page + 1, page_size: pageSize })}`) });
  if (sys.isLoading) return <LinearProgress />;
  const s = sys.data;
  return (
    <Box>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Health">
            <Typography variant="body2">Status: <Chip size="small" color={health.data?.status === "ready" ? "success" : "warning"} label={health.data?.status ?? "-"} /></Typography>
            {Object.entries(health.data?.checks ?? {}).map(([k, v]: any) => <Typography key={k} variant="body2">{k}: {v.ok ? "OK" : "FAIL"} {v.mode ?? ""} {v.heartbeat_age_s != null ? `(heartbeat ${v.heartbeat_age_s}s)` : ""}</Typography>)}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Section title="Configuration">
            <Typography variant="body2">Environment: {s.app_env} - graph v{s.graph_version}</Typography>
            <Typography variant="body2">LLM mode: <b>{s.llm_mode}</b> - fast {s.models.fast}, reasoning {s.models.reasoning}, embeddings {s.models.embedding}</Typography>
            <Typography variant="body2">PHI to LLM: {s.allow_phi_to_llm ? "allowed" : "minimized (names, SSN, DOB, contacts masked)"} - circuit {s.circuit}</Typography>
            <Typography variant="body2">Queue: {JSON.stringify(s.queue)}</Typography>
            {s.workers.map((w: any) => <Typography key={w.worker_id} variant="caption" display="block">Worker {w.worker_id}: {fmtDateTime(w.beat_at)}</Typography>)}
          </Section>
        </Grid>
      </Grid>
      <Section title={`Tool registry (${s.tools.length})`}>
        <Table size="small"><TableHead><TableRow><TableCell>Tool</TableCell><TableCell>Description</TableCell><TableCell>Deterministic</TableCell><TableCell>Timeout</TableCell></TableRow></TableHead>
          <TableBody>{s.tools.map((t: any) => <TableRow key={t.name}><TableCell><Typography variant="caption" fontFamily="monospace">{t.name}</Typography></TableCell><TableCell>{t.description}</TableCell><TableCell>{t.deterministic ? "yes" : "LLM"}</TableCell><TableCell>{t.timeout_s}s</TableCell></TableRow>)}</TableBody>
        </Table>
      </Section>
      <Typography variant="subtitle1" sx={{ mb: 1 }}>Audit log (metadata only)</Typography>
      <AuditTable rows={audit.data?.data ?? []} total={Number(audit.data?.meta?.total ?? 0)} page={page} setPage={setPage} pageSize={pageSize} setPageSize={setPageSize} showClaim />
    </Box>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState(0);
  return (
    <Box>
      <PageHeader title="Administration" subtitle="Users and roles, guideline store, prompts and models, system health. Administrators have no access to PHI." />
      <Paper sx={{ mb: 2 }}><Tabs value={tab} onChange={(_, v) => setTab(v)}><Tab label="Users & roles" /><Tab label="Guidelines" /><Tab label="Prompts & thresholds" /><Tab label="System" /></Tabs></Paper>
      {tab === 0 && <UsersTab />}{tab === 1 && <GuidelinesTab />}{tab === 2 && <ConfigTab />}{tab === 3 && <SystemTab />}
    </Box>
  );
}
