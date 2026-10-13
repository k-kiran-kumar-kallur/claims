import { Box, Button, CircularProgress, Drawer, IconButton, Stack, Typography, Chip, Tooltip } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import FormatQuoteIcon from "@mui/icons-material/FormatQuote";
import { createContext, ReactNode, useContext, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Citation } from "../api/types";
import { usePageImage } from "../hooks/usePageImage";

interface Line { line_number: number; text: string; bbox: number[] | null }

/** Rendered page with line-level highlight overlays (bounding boxes from page_lines). */
export function PageWithHighlights({ docId, page, lineStart, lineEnd, onLineClick }: {
  docId: string; page: number; lineStart?: number; lineEnd?: number; onLineClick?: (l: Line) => void;
}) {
  const { url, error } = usePageImage(docId, page);
  const text = useQuery({ queryKey: ["page-text", docId, page], queryFn: () => api.get<{ lines: Line[]; text_source: string; ocr_confidence: number | null }>(`/documents/${docId}/pages/${page}/text`) });
  const lines = text.data?.lines ?? [];
  const highlighted = lines.filter((l) => lineStart !== undefined && l.line_number >= lineStart && l.line_number <= (lineEnd ?? lineStart));
  if (error) return <Typography color="error">Could not load page image: {error}</Typography>;
  if (!url) return <Box sx={{ display: "grid", placeItems: "center", height: 300 }}><CircularProgress size={28} /></Box>;
  return (
    <Box sx={{ position: "relative", width: "100%", border: "1px solid", borderColor: "divider", bgcolor: "#fff" }}>
      <img src={url} alt={`Page ${page}`} style={{ width: "100%", display: "block" }} />
      {lines.map((l) => {
        if (!l.bbox || l.bbox.length < 4) return null;
        const hit = highlighted.includes(l);
        const [x0, y0, x1, y1] = l.bbox;
        return (
          <Tooltip key={l.line_number} title={`Line ${l.line_number}`} placement="left" disableInteractive>
            <Box onClick={() => onLineClick?.(l)} data-testid={hit ? "highlight" : undefined}
              sx={{ position: "absolute", left: `${x0 * 100}%`, top: `${y0 * 100 - 0.3}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100 + 0.6}%`,
                    bgcolor: hit ? "rgba(255, 196, 0, 0.38)" : "transparent", outline: hit ? "2px solid rgba(214,150,0,0.85)" : "none",
                    cursor: onLineClick ? "pointer" : "default", "&:hover": { bgcolor: hit ? undefined : "rgba(31,79,143,0.07)" } }} />
          </Tooltip>
        );
      })}
    </Box>
  );
}

const Ctx = createContext<{ open: (c: Citation, claimId?: string) => void }>({ open: () => undefined });
export const useCitation = () => useContext(Ctx);

/** Global side panel: every AI statement is clickable to its source (spec §13.3). */
export function CitationProvider({ children }: { children: ReactNode }) {
  const [cite, setCite] = useState<Citation | null>(null);
  const [claimId, setClaimId] = useState<string | undefined>();
  const navigate = useNavigate();
  const doc = useQuery({ queryKey: ["doc-meta", cite?.document_id], queryFn: () => api.get<any>(`/documents/${cite!.document_id}`), enabled: !!cite });
  return (
    <Ctx.Provider value={{ open: (c, id) => { setCite(c); setClaimId(id); } }}>
      {children}
      <Drawer anchor="right" open={!!cite} onClose={() => setCite(null)} PaperProps={{ sx: { width: { xs: "100%", md: 620 }, p: 2 } }}>
        {cite && (
          <Stack spacing={1.5}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="subtitle1" fontWeight={650}>{doc.data?.title ?? "Source document"}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {doc.data?.classification?.doc_type ?? ""} - page {cite.page_number}, lines {cite.line_start}-{cite.line_end}
                </Typography>
              </Box>
              <IconButton onClick={() => setCite(null)} aria-label="Close source panel"><CloseIcon /></IconButton>
            </Stack>
            {cite.quote && (
              <Box sx={{ p: 1.25, bgcolor: "#fffbea", border: "1px solid #f3e2a9", borderRadius: 1 }}>
                <Stack direction="row" spacing={1}>
                  <FormatQuoteIcon fontSize="small" color="warning" />
                  <Typography variant="body2" sx={{ fontStyle: "italic" }}>{cite.quote}</Typography>
                </Stack>
                {cite.match_score != null && <Chip sx={{ mt: 1 }} label={`Quote match ${(cite.match_score * 100).toFixed(0)}%`} color={cite.match_score >= 0.9 ? "success" : "warning"} variant="outlined" />}
              </Box>
            )}
            <PageWithHighlights docId={cite.document_id} page={cite.page_number} lineStart={cite.line_start} lineEnd={cite.line_end} />
            {claimId && (
              <Button startIcon={<OpenInNewIcon />} onClick={() => { setCite(null); navigate(`/claims/${claimId}/viewer/${cite.document_id}?page=${cite.page_number}&ls=${cite.line_start}&le=${cite.line_end}`); }}>
                Open in document viewer
              </Button>
            )}
          </Stack>
        )}
      </Drawer>
    </Ctx.Provider>
  );
}

export function CitationChip({ citation, index, claimId }: { citation: Citation; index?: number; claimId?: string }) {
  const { open } = useCitation();
  return (
    <Tooltip title={citation.quote ? `"${citation.quote.slice(0, 160)}" (p${citation.page_number} L${citation.line_start})` : `Page ${citation.page_number}`}>
      <Chip component="button" clickable onClick={() => open(citation, claimId)} label={index !== undefined ? `[${index}]` : `p${citation.page_number}:L${citation.line_start}`}
        size="small" variant="outlined" color="primary" sx={{ height: 20, fontSize: 11, mx: 0.25, verticalAlign: "baseline" }} />
    </Tooltip>
  );
}

export function CitationList({ citations, claimId }: { citations?: Citation[]; claimId?: string }) {
  if (!citations?.length) return <Chip label="no citation" size="small" color="error" variant="outlined" sx={{ height: 20, fontSize: 11 }} />;
  return <>{citations.map((c, i) => <CitationChip key={c.id ?? i} citation={c} claimId={claimId} />)}</>;
}

/** Renders summary markdown (### headings, - bullets) with [[cite:id]] tokens as clickable chips. */
export function CitedMarkdown({ md, citations, claimId }: { md: string; citations: Record<string, Citation>; claimId?: string }) {
  const numbering: Record<string, number> = {};
  let n = 0;
  const lines = md.split("\n");
  return (
    <Box>
      {lines.map((line, i) => {
        if (line.startsWith("### ")) return <Typography key={i} variant="subtitle2" color="primary.dark" sx={{ mt: i ? 1.5 : 0, mb: 0.5 }}>{line.slice(4)}</Typography>;
        if (!line.trim()) return null;
        const bullet = line.trim().startsWith("- ");
        const raw = bullet ? line.trim().slice(2) : line;
        const parts = raw.split(/(\[\[cite:[0-9a-f-]{36}\]\])/g);
        return (
          <Typography key={i} variant="body2" component="div" sx={{ pl: bullet ? 2 : 0, position: "relative", mb: 0.5, lineHeight: 1.6,
            "&::before": bullet ? { content: '"•"', position: "absolute", left: 4, color: "text.secondary" } : undefined }}>
            {parts.map((p, j) => {
              const m = p.match(/^\[\[cite:([0-9a-f-]{36})\]\]$/);
              if (!m) return <span key={j}>{p}</span>;
              const c = citations[m[1]];
              if (!c) return null;
              numbering[m[1]] ??= ++n;
              return <CitationChip key={j} citation={c} index={numbering[m[1]]} claimId={claimId} />;
            })}
          </Typography>
        );
      })}
    </Box>
  );
}
