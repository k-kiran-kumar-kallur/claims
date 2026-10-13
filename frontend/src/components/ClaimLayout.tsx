import { Badge, Box, Breadcrumbs, Chip, Link, Paper, Stack, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import EventIcon from "@mui/icons-material/Event";
import BusinessIcon from "@mui/icons-material/Business";
import PlaceIcon from "@mui/icons-material/Place";
import AccessibilityNewIcon from "@mui/icons-material/AccessibilityNew";
import { ReactNode } from "react";
import { Link as RouterLink, Outlet, useLocation, useParams } from "react-router-dom";
import { CHECKPOINTS } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { useClaim, useClaimReviews } from "../hooks/queries";
import { riskColor } from "../theme/theme";
import { ErrorAlert, fmtDate, LoadingRows, StatusChip } from "./common";
import { ErrorBoundary } from "./ErrorBoundary";

function Fact({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" sx={{ color: "text.secondary", "& svg": { fontSize: 16 } }}>
      {icon}<Typography variant="body2" color="text.secondary">{children}</Typography>
    </Stack>
  );
}

export function ClaimLayout() {
  const { claimId } = useParams();
  const { data: claim, error, isLoading } = useClaim(claimId);
  const reviews = useClaimReviews(claimId);
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
    { path: "activity", label: "Activity", show: !attorneyOnly },
    { path: "audit", label: "Audit", show: can("audit:view") && !hasRole("admin") },
  ].filter((t) => t.show);
  // tabs that hold an open human-review task get a dot so reviewers see where action is needed
  const pending: Record<string, string> = {};
  (reviews.data ?? []).forEach((r) => {
    const p = CHECKPOINTS[r.checkpoint]?.path;
    if (p) pending[p === "signoff" ? "decision" : p] = r.checkpoint;
  });
  const base = `/claims/${claimId}`;
  const current = loc.pathname.replace(base, "").replace(/^\//, "").split("/")[0];
  const value = tabs.some((t) => t.path === current) ? current : current === "viewer" ? "documents" : current === "signoff" ? "decision" : "";
  if (isLoading) return <LoadingRows rows={3} height={56} />;
  if (error || !claim) return <ErrorAlert error={error} />;
  return (
    <Box>
      <Breadcrumbs sx={{ mb: 1 }} aria-label="breadcrumb">
        <Link component={RouterLink} to="/claims" underline="hover" color="text.secondary" variant="body2">Claims</Link>
        <Typography variant="body2" color="text.primary">{claim.claim_number}</Typography>
      </Breadcrumbs>
      <Paper sx={{ px: { xs: 1.5, md: 2.5 }, pt: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1.5}>
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="h5" component="h1">{claim.claim_number}</Typography>
              <StatusChip status={claim.status} />
              {claim.is_synthetic && <Chip label="Synthetic test data" size="small" color="secondary" variant="outlined" />}
              {claim.litigated && <Chip label="Litigated" size="small" color="error" />}
              {claim.baseline_locked && <Chip label="Baseline locked" size="small" color="success" variant="outlined" />}
            </Stack>
            <Typography variant="subtitle1" sx={{ mt: 0.5 }}>{claim.claimant ?? "Unknown claimant"}</Typography>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
              <Fact icon={<EventIcon />}>Injured {fmtDate(claim.date_of_injury)}</Fact>
              <Fact icon={<BusinessIcon />}>{claim.employer_name ?? "Employer unknown"}</Fact>
              <Fact icon={<PlaceIcon />}>{claim.jurisdiction_state ?? "--"}</Fact>
              {(claim.body_parts || []).length > 0 && <Fact icon={<AccessibilityNewIcon />}>{claim.body_parts.join(", ")}</Fact>}
            </Stack>
          </Box>
          <Stack direction="row" spacing={1} alignItems="flex-start" flexWrap="wrap" useFlexGap>
            {claim.risk_score != null && (
              <Tooltip title="Risk score from the routing agent (surgery, TTD duration, guideline deviations, opioids, open issues...)">
                <Chip icon={claim.risk_score >= 0.7 ? <WarningAmberIcon /> : undefined} label={`Risk ${claim.risk_score.toFixed(2)} - ${claim.complexity}`}
                  color={riskColor(claim.risk_score)} />
              </Tooltip>
            )}
            {claim.pending_reviews > 0 && <Chip label={`${claim.pending_reviews} pending review${claim.pending_reviews > 1 ? "s" : ""}`} color="warning" variant="outlined" />}
          </Stack>
        </Stack>
        <Tabs value={value} variant="scrollable" scrollButtons="auto" allowScrollButtonsMobile
          sx={{ mt: 1.5, minHeight: 44, "& .MuiTab-root": { minHeight: 44, py: 0.5, px: 1.25, fontSize: 13.5 } }}>
          {tabs.map((t) => (
            <Tab key={t.path} value={t.path} component={RouterLink} to={t.path ? `${base}/${t.path}` : base}
              label={pending[t.path]
                ? <Badge variant="dot" color="warning" sx={{ "& .MuiBadge-dot": { right: -6, top: 2 } }}>{t.label}</Badge>
                : t.label} />
          ))}
        </Tabs>
      </Paper>
      <ErrorBoundary resetKey={loc.pathname}><Outlet context={{ claim }} /></ErrorBoundary>
    </Box>
  );
}
