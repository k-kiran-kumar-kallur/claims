import { Box, Chip, Collapse, FormControlLabel, IconButton, InputAdornment, Stack, Switch, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import PauseCircleIcon from "@mui/icons-material/PauseCircle";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import SearchIcon from "@mui/icons-material/Search";
import DownloadIcon from "@mui/icons-material/Download";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { RunEvent } from "../hooks/useRunEvents";
import { fmtDuration } from "./common";
import { fmtClock, logToText, nodeName, toLogLines, type LogLevel, type LogLine } from "./runLog";
import { toast } from "./Toast";

const LEVEL_STYLE: Record<LogLevel, { icon: ReactNode; color: string; bg?: string }> = {
  debug: { icon: <ChevronRightIcon />, color: "#8a94a6" },
  info: { icon: <InfoOutlinedIcon />, color: "#0e7090" },
  success: { icon: <CheckCircleIcon />, color: "#067647" },
  warning: { icon: <WarningAmberIcon />, color: "#b54708", bg: "#fffaeb" },
  error: { icon: <ErrorIcon />, color: "#c4320a", bg: "#fef3f2" },
  review: { icon: <PauseCircleIcon />, color: "#6941c6", bg: "#f4f3ff" },
};

type Filter = "key" | "all" | "problems";
const FILTERS: Record<Filter, (l: LogLine) => boolean> = {
  all: () => true,
  key: (l) => l.level !== "debug",
  problems: (l) => l.level === "warning" || l.level === "error",
};

function LogRow({ line, compact }: { line: LogLine; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const s = LEVEL_STYLE[line.level];
  return (
    <Box sx={{ borderBottom: "1px solid", borderColor: "divider", bgcolor: s.bg, "&:last-child": { borderBottom: 0 } }}>
      <Stack direction="row" spacing={1.25} alignItems="flex-start" onClick={() => !compact && setOpen(!open)}
        sx={{ px: 1.5, py: compact ? 0.6 : 0.9, cursor: compact ? undefined : "pointer", "&:hover": compact ? undefined : { bgcolor: "rgba(16,24,40,0.03)" } }}>
        <Typography variant="caption" sx={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", color: "text.secondary", pt: "2px", flexShrink: 0 }}>
          {fmtClock(line.ts)}
        </Typography>
        <Box sx={{ color: s.color, display: "flex", pt: "1px", "& svg": { fontSize: 17 } }} aria-label={line.level}>{s.icon}</Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="body2" sx={{ fontWeight: line.level === "debug" ? 400 : 600, color: line.level === "debug" ? "text.secondary" : "text.primary" }}>
              {line.message}
            </Typography>
            {line.durationMs != null && <Chip label={fmtDuration(line.durationMs)} variant="outlined" sx={{ height: 20, fontSize: 11 }} />}
            {!compact && line.node && line.level !== "success" && <Chip label={nodeName(line.node)} sx={{ height: 20, fontSize: 11, bgcolor: "#eef2f7" }} />}
          </Stack>
          {line.detail && (
            <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.25, wordBreak: "break-word", ...(compact ? { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } : {}) }}>
              {line.detail}
            </Typography>
          )}
        </Box>
      </Stack>
      {!compact && (
        <Collapse in={open} unmountOnExit>
          <Box component="pre" sx={{ m: 0, mx: 1.5, mb: 1, p: 1.25, fontSize: 11.5, bgcolor: "#0f172a", color: "#e2e8f0", borderRadius: 1.5, overflow: "auto", maxHeight: 260 }}>
            {JSON.stringify({ event: line.raw.event, id: line.raw.id, ...line.raw.data }, null, 2)}
          </Box>
        </Collapse>
      )}
    </Box>
  );
}

/** Compact feed of the latest important events, used on the claim dashboard. */
export function RecentActivity({ events, limit = 6 }: { events: RunEvent[]; limit?: number }) {
  const lines = useMemo(() => toLogLines(events).filter(FILTERS.key).slice(-limit).reverse(), [events, limit]);
  if (lines.length === 0) return null;
  return (
    <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, overflow: "hidden" }}>
      {lines.map((l) => <LogRow key={l.id} line={l} compact />)}
    </Box>
  );
}

/** Full, filterable run log with live follow, raw-event inspection and download. */
export function ActivityLog({ events, live, loading, fileName = "run-log" }: { events: RunEvent[]; live?: boolean; loading?: boolean; fileName?: string }) {
  const [filter, setFilter] = useState<Filter>("key");
  const [search, setSearch] = useState("");
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const all = useMemo(() => toLogLines(events), [events]);
  const lines = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter(FILTERS[filter]).filter((l) => !q || `${l.message} ${l.detail ?? ""} ${l.node ?? ""}`.toLowerCase().includes(q));
  }, [all, filter, search]);
  const counts = useMemo(() => ({
    errors: all.filter((l) => l.level === "error").length,
    warnings: all.filter((l) => l.level === "warning").length,
  }), [all]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines, follow]);

  const download = () => {
    const url = URL.createObjectURL(new Blob([logToText(all)], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fileName}.log`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(logToText(lines));
      toast.success(`Copied ${lines.length} log lines`);
    } catch {
      toast.error("Could not copy to the clipboard");
    }
  };

  return (
    <Box>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} sx={{ mb: 1.5 }}>
        <ToggleButtonGroup size="small" exclusive value={filter} onChange={(_, v) => v && setFilter(v)} aria-label="Log filter">
          <ToggleButton value="key">Key events</ToggleButton>
          <ToggleButton value="all">Everything</ToggleButton>
          <ToggleButton value="problems">
            Problems{counts.errors + counts.warnings > 0 && <Chip label={counts.errors + counts.warnings} color={counts.errors ? "error" : "warning"} sx={{ ml: 0.75, height: 18, fontSize: 11 }} />}
          </ToggleButton>
        </ToggleButtonGroup>
        <TextField placeholder="Search the log" value={search} onChange={(e) => setSearch(e.target.value)} sx={{ flex: 1, maxWidth: { md: 320 } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} inputProps={{ "aria-label": "Search the log" }} />
        <Box sx={{ flex: 1 }} />
        <Stack direction="row" spacing={0.5} alignItems="center">
          {live && <Chip size="small" color="success" variant="outlined" label="Live" icon={<Box component="span" sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: "success.main", ml: "8px !important", animation: "pulse 1.4s infinite", "@keyframes pulse": { "50%": { opacity: 0.3 } } }} />} />}
          <FormControlLabel control={<Switch size="small" checked={follow} onChange={(e) => setFollow(e.target.checked)} />} label={<Typography variant="body2">Follow</Typography>} sx={{ mr: 0.5 }} />
          <Tooltip title="Copy visible lines"><span><IconButton size="small" onClick={copy} disabled={!lines.length} aria-label="Copy log"><ContentCopyIcon fontSize="small" /></IconButton></span></Tooltip>
          <Tooltip title="Download full log"><span><IconButton size="small" onClick={download} disabled={!all.length} aria-label="Download log"><DownloadIcon fontSize="small" /></IconButton></span></Tooltip>
        </Stack>
      </Stack>
      <Box ref={box} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, maxHeight: 560, overflow: "auto", bgcolor: "background.paper" }}
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          if (!atBottom && follow) setFollow(false);
        }}>
        {lines.map((l) => <LogRow key={l.id} line={l} />)}
        {lines.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 3, textAlign: "center" }}>
            {loading ? "Loading log..." : all.length ? "No log lines match this filter." : "No events recorded for this run yet."}
          </Typography>
        )}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: "block" }}>
        Showing {lines.length} of {all.length} events{counts.errors ? ` · ${counts.errors} error${counts.errors > 1 ? "s" : ""}` : ""}{counts.warnings ? ` · ${counts.warnings} warning${counts.warnings > 1 ? "s" : ""}` : ""}. Click a line to see the raw event.
      </Typography>
    </Box>
  );
}
