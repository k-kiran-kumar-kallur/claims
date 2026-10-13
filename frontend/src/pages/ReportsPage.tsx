import { Box, Button, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, downloadFile } from "../api/client";
import type { Report } from "../api/types";
import { EmptyState, ErrorAlert, fmtDateTime, PageHeader } from "../components/common";

export default function ReportsPage() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["approved-reports"], queryFn: () => api.get<Report[]>("/reports") });
  const rows = q.data ?? [];
  return (
    <Box>
      <PageHeader title="Approved reports" subtitle="Human-approved one-page summaries, MMI status reports, medical chronologies and decision provenance reports (read only)." />
      <ErrorAlert error={q.error} />
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead><TableRow><TableCell>Claim</TableCell><TableCell>Report</TableCell><TableCell>Format</TableCell><TableCell>Version</TableCell><TableCell>Generated</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell><Button size="small" onClick={() => navigate(`/claims/${r.claim_id}/chronology`)}>{r.claim_number}</Button></TableCell>
                <TableCell>{r.report_type.replace(/_/g, " ")}</TableCell><TableCell>{r.format.toUpperCase()}</TableCell><TableCell>{r.version}</TableCell>
                <TableCell>{fmtDateTime(r.created_at)}</TableCell>
                <TableCell><Button size="small" startIcon={<DownloadIcon />} onClick={() => downloadFile(`/reports/${r.id}/download`, `${r.claim_number}_${r.report_type}.${r.format}`)}>Download</Button></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!q.isLoading && rows.length === 0 && <EmptyState title="No approved reports available" hint={<Typography variant="body2">Reports appear here once a claim's decision record is sealed and access has been granted.</Typography>} />}
      </TableContainer>
    </Box>
  );
}
