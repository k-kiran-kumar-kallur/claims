import { Alert, Snackbar, Typography } from "@mui/material";
import { useEffect, useState } from "react";

export type ToastSeverity = "success" | "error" | "info" | "warning";
interface ToastMsg { id: number; message: string; severity: ToastSeverity; detail?: string }

type Listener = (t: ToastMsg) => void;
let listener: Listener | null = null;
let seq = 0;

/** Fire-and-forget toast usable outside React (e.g. from the QueryClient's MutationCache). */
export const toast = {
  show: (message: string, severity: ToastSeverity = "info", detail?: string) => listener?.({ id: ++seq, message, severity, detail }),
  success: (message: string) => toast.show(message, "success"),
  error: (message: string, detail?: string) => toast.show(message, "error", detail),
};

export function ToastHost() {
  const [queue, setQueue] = useState<ToastMsg[]>([]);
  const [open, setOpen] = useState(false);
  const current = queue[0];

  useEffect(() => {
    listener = (t) => setQueue((q) => (q.some((x) => x.message === t.message) ? q : [...q, t]));
    return () => { listener = null; };
  }, []);
  useEffect(() => { if (current) setOpen(true); }, [current]);

  if (!current) return null;
  return (
    <Snackbar key={current.id} open={open} autoHideDuration={current.severity === "error" ? 8000 : 4000}
      onClose={(_, reason) => reason !== "clickaway" && setOpen(false)}
      TransitionProps={{ onExited: () => setQueue((q) => q.slice(1)) }}
      anchorOrigin={{ vertical: "bottom", horizontal: "right" }}>
      <Alert severity={current.severity} variant="filled" onClose={() => setOpen(false)} sx={{ minWidth: 300, maxWidth: 480, boxShadow: 6 }}>
        {current.message}
        {current.detail && <Typography variant="caption" display="block" sx={{ opacity: 0.85 }}>{current.detail}</Typography>}
      </Alert>
    </Snackbar>
  );
}
