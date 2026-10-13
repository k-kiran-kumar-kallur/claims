import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, TextField, Typography } from "@mui/material";
import { ReactNode, useState } from "react";
import { ApiError } from "../api/client";
import { severityColor } from "../theme/theme";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1} sx={{ mb: 2 }}>
      <Box>
        <Typography variant="h5" component="h1">{title}</Typography>
        {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
      </Box>
      {actions && <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>{actions}</Stack>}
    </Stack>
  );
}

export function Section({ title, actions, children, dense }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; dense?: boolean }) {
  return (
    <Paper sx={{ p: dense ? 1.5 : 2, mb: 2 }}>
      {(title || actions) && (
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.25 }}>
          <Typography variant="subtitle1" fontWeight={650}>{title}</Typography>
          <Stack direction="row" spacing={1}>{actions}</Stack>
        </Stack>
      )}
      {children}
    </Paper>
  );
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  return (
    <Alert severity="error" sx={{ mb: 2 }}>
      {e.message || "Something went wrong"}
      {e.correlationId && <Typography variant="caption" display="block">Reference: {e.correlationId}</Typography>}
    </Alert>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <Box sx={{ py: 5, textAlign: "center", color: "text.secondary" }}>
      <Typography variant="subtitle1" color="text.primary">{title}</Typography>
      {hint && <Typography variant="body2" sx={{ mt: 0.5 }}>{hint}</Typography>}
    </Box>
  );
}

export function SeverityChip({ severity }: { severity?: string | null }) {
  if (!severity) return null;
  return <Chip label={severity} color={severityColor(severity)} variant={severity === "low" ? "outlined" : "filled"} sx={{ textTransform: "capitalize", fontWeight: 600 }} />;
}

const STATUS_COLORS: Record<string, "default" | "success" | "warning" | "error" | "info" | "primary"> = {
  completed: "success", approved: "success", validated: "success", auto_verified: "success", sealed: "success", final: "primary",
  submitted: "success", accepted: "success", resolved: "success", ready: "success", decided: "success", certified: "success",
  running: "info", queued: "info", in_review: "info", in_progress: "info", open: "warning", pending: "warning", draft: "default",
  awaiting_human: "warning", awaiting_documents: "warning", needs_review: "warning", retrying: "warning", edited: "info",
  failed: "error", rejected: "error", cancelled: "default", dismissed: "default", duplicate: "default", noise: "default",
  non_certified: "error", explained: "success", requested: "info",
};

export function StatusChip({ status, label }: { status?: string | null; label?: string }) {
  if (!status) return null;
  return <Chip label={label ?? status.replace(/_/g, " ")} color={STATUS_COLORS[status] ?? "default"} variant="outlined" sx={{ textTransform: "capitalize" }} />;
}

export function AiDraftBadge({ label = "AI draft - not a determination" }: { label?: string }) {
  return <Chip label={label} size="small" sx={{ bgcolor: "#fff3cd", color: "#7a5300", fontWeight: 600, border: "1px solid #f0d58c" }} />;
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return d ? `${m}/${d}/${y}` : iso;
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function ReasonDialog({ open, title, label = "Reason", required = true, confirmText = "Confirm", extra, onClose, onConfirm }: {
  open: boolean; title: string; label?: string; required?: boolean; confirmText?: string; extra?: ReactNode;
  onClose: () => void; onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {extra}
        <TextField autoFocus fullWidth multiline minRows={3} label={label} value={reason} onChange={(e) => setReason(e.target.value)} sx={{ mt: 1 }}
          helperText={required ? "Required - stored in the audit trail" : "Optional"} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={required && reason.trim().length < 3} onClick={() => { onConfirm(reason.trim()); setReason(""); }}>
          {confirmText}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "160px 1fr" }, rowGap: 0.75, columnGap: 2 }}>
      {items.map(([k, v]) => (
        <Box key={k} sx={{ display: "contents" }}>
          <Typography variant="body2" color="text.secondary">{k}</Typography>
          <Typography variant="body2" component="div">{v ?? "-"}</Typography>
        </Box>
      ))}
    </Box>
  );
}

/** Normalise model-produced values that should be lists (a string or object becomes a one-item list). */
export function asList(v: unknown): any[] {
  if (Array.isArray(v)) return v;
  if (v === null || v === undefined || v === "") return [];
  return typeof v === "string" ? [{ type: "note", limit: v }] : [v];
}
