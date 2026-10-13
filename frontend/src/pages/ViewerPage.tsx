import { Box, Button, Chip, Grid2 as Grid, LinearProgress, List, ListItemButton, ListItemText, Pagination, Paper, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { PageWithHighlights } from "../components/CitationViewer";
import { ErrorAlert, fmtDate, Section, StatusChip } from "../components/common";

export default function ViewerPage() {
  const { claimId, docId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const page = Number(params.get("page") ?? 1);
  const [hl, setHl] = useState<{ ls?: number; le?: number }>({ ls: params.get("ls") ? Number(params.get("ls")) : undefined, le: params.get("le") ? Number(params.get("le")) : undefined });
  useEffect(() => setHl({ ls: params.get("ls") ? Number(params.get("ls")) : undefined, le: params.get("le") ? Number(params.get("le")) : undefined }), [params]);
  const doc = useQuery({ queryKey: ["doc-meta", docId], queryFn: () => api.get<any>(`/documents/${docId}`) });
  if (doc.isLoading) return <LinearProgress />;
  if (doc.error) return <ErrorAlert error={doc.error} />;
  const d = doc.data;
  const pageFacts = (d.facts as any[]).filter((f) => f.citations.some((c: any) => c.page_number === page));
  const go = (p: number, ls?: number, le?: number) => setParams({ page: String(p), ...(ls ? { ls: String(ls), le: String(le ?? ls) } : {}) });
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate(`/claims/${claimId}/documents`)}>Documents</Button>
        <Typography variant="h6">{d.title}</Typography>
        {d.classification && <Chip label={d.classification.doc_type} color="primary" variant="outlined" />}
        <StatusChip status={d.status} />
        <Typography variant="caption" color="text.secondary">{d.alias} - {fmtDate(d.classification?.service_date_start)} - {d.classification?.provider_name ?? ""}</Typography>
      </Stack>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 2 }}>
          <Paper sx={{ maxHeight: "75vh", overflow: "auto" }}>
            <List dense>
              {d.pages.map((p: any) => (
                <ListItemButton key={p.page_number} selected={p.page_number === page} onClick={() => go(p.page_number)}>
                  <ListItemText primary={`Page ${p.page_number}`} secondary={`${p.text_source}${p.ocr_confidence != null ? ` ${(p.ocr_confidence * 100).toFixed(0)}%` : ""}${p.is_blank ? " - blank" : ""}`} />
                </ListItemButton>
              ))}
            </List>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, md: 7 }}>
          <Paper sx={{ p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="body2" color="text.secondary">{hl.ls ? `Highlighting lines ${hl.ls}-${hl.le}` : "Click a fact to highlight its source lines"}</Typography>
              <Pagination size="small" count={d.pages.length} page={page} onChange={(_, p) => go(p)} />
            </Stack>
            <PageWithHighlights docId={docId!} page={page} lineStart={hl.ls} lineEnd={hl.le} onLineClick={(l) => setHl({ ls: l.line_number, le: l.line_number })} />
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, md: 3 }}>
          <Section title={`Linked facts (page ${page})`} dense>
            {pageFacts.length === 0 && <Typography variant="body2" color="text.secondary">No extracted facts cite this page.</Typography>}
            <List dense disablePadding>
              {pageFacts.map((f: any) => {
                const c = f.citations.find((x: any) => x.page_number === page);
                return (
                  <ListItemButton key={f.id} onClick={() => go(page, c.line_start, c.line_end)} selected={hl.ls === c.line_start}>
                    <ListItemText primary={f.label} secondary={<><StatusChip status={f.validation_status} /> L{c.line_start}-{c.line_end}</>} secondaryTypographyProps={{ component: "div" }} />
                  </ListItemButton>
                );
              })}
            </List>
          </Section>
          <Section title="Classification history" dense>
            {d.classification_history.map((h: any) => (
              <Box key={h.id} sx={{ mb: 1 }}>
                <Typography variant="body2" fontWeight={h.is_current ? 650 : 400}>v{h.version} {h.doc_type} ({Math.round(h.confidence * 100)}%)</Typography>
                <Typography variant="caption" color="text.secondary">{h.classified_by === "agent" ? "AI" : "Human"} - {h.reason ?? h.rationale}</Typography>
              </Box>
            ))}
          </Section>
        </Grid>
      </Grid>
    </Box>
  );
}
