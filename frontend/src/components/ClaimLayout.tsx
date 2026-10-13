import { Box, Chip, LinearProgress, Paper, Stack, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { Link as RouterLink, Outlet, useLocation, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useClaim } from "../hooks/queries";
import { ErrorAlert, fmtDate, StatusChip } from "./common";
import { ErrorBoundary } from "./ErrorBoundary";

export function ClaimLayout() {
  const { claimId } = useParams();
  const { data: claim, error, isLoading } = useClaim(claimId);
  const { can, hasRole } = useAuth();
  const loc = useLocation();
  const attorneyOnly = hasRole("attorney") && !can("decision:make", "fact:validate", "timeline:approve", "classification:edit", "summary:edit");
  const tabs = [
    { path: "", label: "Dashboard", show: !attorneyOnly },
    { path: "baseline", label: "Baseline", show: can("baseline:confirm", "decision:make") },
    { path: "documents", label: "Documents", show: !attorneyOnly },
    { path: "timeline", label: "Timeline", show: !attorneyOnly },
    { path: "facts", label: "Facts", show: !attorneyOnly },
    { path: "clinical", label: "Clinical", show: !attorneyOnly },
    { path: "guidelines", label: "Guidelines", show: !attorneyOnly },
    { path: "chronology", label: "Chronology", show: true },
    { path: "summary", label: "Summary", show: !attorneyOnly },
    { path: "decision", label: "Decision", show: can("decision:make", "ur:determine", "decision:signoff") },
    { path: "rtw", label: "RTW & care", show: !attorneyOnly },
    { path: "audit", label: "Audit", show: can("audit:view") && !hasRole("admin") },
  ].filter((t) => t.show);
  const base = `/claims/${claimId}`;
  const current = loc.pathname.replace(base, "").replace(/^\//, "").split("/")[0];
  const value = tabs.some((t) => t.path === current) ? current : current === "viewer" ? "documents" : current === "signoff" ? "decision" : "";
  if (isLoading) return <LinearProgress />;
  if (error || !claim) return <ErrorAlert error={error} />;
  return (
    <Box>
      <Paper sx={{ px: 2, pt: 1.5, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="h5" component="h1">{claim.claim_number}</Typography>
              <StatusChip status={claim.status} />
              {claim.is_synthetic && <Chip label="Synthetic test data" size="small" color="secondary" variant="outlined" />}
              {claim.litigated && <Chip label="Litigated" size="small" color="error" />}
              {claim.baseline_locked && <Chip label="Baseline locked" size="small" color="success" variant="outlined" />}
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
              {claim.claimant} - DOI {fmtDate(claim.date_of_injury)} - {claim.employer_name ?? "Employer unknown"} - {claim.jurisdiction_state ?? "--"} - {(claim.body_parts || []).join(", ")}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center">
            {claim.risk_score != null && (
              <Tooltip title="Risk score from the routing agent (surgery, TTD duration, guideline deviations, opioids, open issues...)">
                <Chip icon={claim.risk_score >= 0.7 ? <WarningAmberIcon /> : undefined} label={`Risk ${claim.risk_score.toFixed(2)} - ${claim.complexity}`}
                  color={claim.risk_score >= 0.7 ? "error" : claim.risk_score >= 0.4 ? "warning" : "success"} />
              </Tooltip>
            )}
            {claim.pending_reviews > 0 && <Chip label={`${claim.pending_reviews} pending review${claim.pending_reviews > 1 ? "s" : ""}`} color="warning" variant="outlined" />}
          </Stack>
        </Stack>
        <Tabs value={value} variant="scrollable" scrollButtons="auto" sx={{ mt: 1, minHeight: 40, "& .MuiTab-root": { minHeight: 40, py: 0.5 } }}>
          {tabs.map((t) => <Tab key={t.path} value={t.path} label={t.label} component={RouterLink} to={t.path ? `${base}/${t.path}` : base} />)}
        </Tabs>
      </Paper>
      <ErrorBoundary resetKey={loc.pathname}><Outlet context={{ claim }} /></ErrorBoundary>
    </Box>
  );
}
