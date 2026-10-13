import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Skeleton, Stack, TextField, Tooltip, Typography } from "@mui/material";
import InboxOutlinedIcon from "@mui/icons-material/InboxOutlined";
import { ReactNode, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { severityColor } from "../theme/theme";

export function PageHeader({ title, subtitle, actions, icon }: { title: string; subtitle?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1.5} sx={{ mb: 2.5 }}>
      <Stack direction="row" spacing={1.5} alignItems="center">
        {icon && <Box sx={{ width: 40, height: 40, borderRadius: 2, display: "grid", placeItems: "center", bgcolor: "primary.light", color: "primary.main", flexShrink: 0 }}>{icon}</Box>}
        <Box>
          <Typography variant="h5" component="h1">{title}</Typography>
          {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
        </Box>
      </Stack>
      {actions && <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>{actions}</Stack>}
    </Stack>
  );
}

export function Section({ title, actions, children, dense }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; dense?: boolean }) {
  return (
    <Paper sx={{ p: dense ? 1.5 : 2, mb: 2 }}>
      {(title || actions) && (
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
          <Typography variant="subtitle1" component="h2" fontWeight={650}>{title}</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent="flex-end">{actions}</Stack>
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

export function EmptyState({ title, hint, icon, action }: { title: string; hint?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <Box sx={{ py: 5, px: 2, textAlign: "center", color: "text.secondary" }}>
      <Box sx={{ width: 52, height: 52, mx: "auto", mb: 1.5, borderRadius: "50%", display: "grid", placeItems: "center", bgcolor: "#eef2f7", color: "#8a94a6" }}>
        {icon ?? <InboxOutlinedIcon />}
      </Box>
      <Typography variant="subtitle1" color="text.primary">{title}</Typography>
      {hint && <Typography variant="body2" sx={{ mt: 0.5, maxWidth: 440, mx: "auto" }}>{hint}</Typography>}
      {action && <Box sx={{ mt: 2 }}>{action}</Box>}
    </Box>
  );
}

/** Placeholder rows while a table or list loads. */
export function LoadingRows({ rows = 5, height = 36 }: { rows?: number; height?: number }) {
  return (
    <Stack spacing={1} sx={{ p: 1.5 }} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} variant="rounded" height={height} sx={{ opacity: 1 - i * 0.12 }} />)}
    </Stack>
  );
}

export function StatTile({ label, value, hint, color, icon, onClick, active }: {
  label: string; value: ReactNode; hint?: ReactNode; color?: string; icon?: ReactNode; onClick?: () => void; active?: boolean;
}) {
  return (
    <Paper onClick={onClick} role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => onClick && e.key === "Enter" && onClick()}
      sx={{ p: 2, height: "100%", cursor: onClick ? "pointer" : undefined, borderColor: active ? "primary.main" : undefined,
        boxShadow: active ? (t) => `0 0 0 1px ${t.palette.primary.main}` : undefined, transition: "border-color .15s",
        "&:hover": onClick ? { borderColor: "primary.main" } : undefined }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Typography variant="overline" color="text.secondary">{label}</Typography>
        {icon && <Box sx={{ color: color ?? "text.secondary", display: "flex", "& svg": { fontSize: 20 } }}>{icon}</Box>}
      </Stack>
      <Typography variant="h5" sx={{ color: color, lineHeight: 1.2 }}>{value}</Typography>
      {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
    </Paper>
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

/** "just now", "5 min ago", "3 h ago", "2 d ago"; falls back to the date after a week. */
export function fmtRelative(iso?: string | null, now = Date.now()): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((now - t) / 1000);
  const future = s < 0;
  const a = Math.abs(s);
  const v = a < 45 ? null : a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 ? `${Math.round(a / 3600)} h` : a < 604800 ? `${Math.round(a / 86400)} d` : undefined;
  if (v === null) return "just now";
  if (v === undefined) return new Date(t).toLocaleDateString();
  return future ? `in ${v}` : `${v} ago`;
}

/** Relative time that re-renders every 30 s, with the exact timestamp on hover. */
export function RelativeTime({ iso, variant = "body2" }: { iso?: string | null; variant?: "body2" | "caption" }) {
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(id); }, []);
  if (!iso) return <Typography variant={variant} component="span">-</Typography>;
  return (
    <Tooltip title={fmtDateTime(iso)}>
      <Typography variant={variant} component="span" sx={{ whiteSpace: "nowrap" }}>{fmtRelative(iso)}</Typography>
    </Tooltip>
  );
}

export function fmtDuration(ms?: number | null): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ${Math.round(s % 60)}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
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
