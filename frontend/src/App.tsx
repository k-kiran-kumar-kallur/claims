import { lazy, Suspense } from "react";
import { LinearProgress } from "@mui/material";
import { Navigate, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppLayout } from "./components/AppLayout";
import { ClaimLayout } from "./components/ClaimLayout";
import { CitationProvider } from "./components/CitationViewer";
import LoginPage from "./pages/LoginPage";
import WorkQueuePage from "./pages/WorkQueuePage";
import { useAuth } from "./auth/AuthProvider";

const ClaimsListPage = lazy(() => import("./pages/ClaimsListPage"));
const NewClaimPage = lazy(() => import("./pages/NewClaimPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const BaselinePage = lazy(() => import("./pages/BaselinePage"));
const DocumentsPage = lazy(() => import("./pages/DocumentsPage"));
const ViewerPage = lazy(() => import("./pages/ViewerPage"));
const TimelinePage = lazy(() => import("./pages/TimelinePage"));
const FactsPage = lazy(() => import("./pages/FactsPage"));
const ClinicalPage = lazy(() => import("./pages/ClinicalPage"));
const GuidelinesPage = lazy(() => import("./pages/GuidelinesPage"));
const ChronologyPage = lazy(() => import("./pages/ChronologyPage"));
const SummaryPage = lazy(() => import("./pages/SummaryPage"));
const DecisionPage = lazy(() => import("./pages/DecisionPage"));
const RtwPage = lazy(() => import("./pages/RtwPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));
const ActivityPage = lazy(() => import("./pages/ActivityPage"));
const SupervisorPage = lazy(() => import("./pages/SupervisorPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const AdminPage = lazy(() => import("./pages/admin/AdminPage"));

function Home() {
  const { hasRole, can } = useAuth();
  if (hasRole("admin") && !can("document:view_phi")) return <Navigate to="/admin" replace />;
  if (hasRole("attorney") && !can("decision:make", "fact:validate", "timeline:approve", "classification:edit")) return <Navigate to="/reports" replace />;
  return <WorkQueuePage />;
}

export default function App() {
  return (
    <CitationProvider>
      <Suspense fallback={<LinearProgress />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
          <Route index element={<Home />} />
          <Route path="claims" element={<ProtectedRoute perms={["document:view_phi"]}><ClaimsListPage /></ProtectedRoute>} />
          <Route path="claims/new" element={<ProtectedRoute perms={["claim:create"]}><NewClaimPage /></ProtectedRoute>} />
          <Route path="claims/:claimId" element={<ProtectedRoute perms={["document:view_phi"]}><ClaimLayout /></ProtectedRoute>}>
            <Route index element={<DashboardPage />} />
            <Route path="baseline" element={<BaselinePage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="viewer/:docId" element={<ViewerPage />} />
            <Route path="timeline" element={<TimelinePage />} />
            <Route path="facts" element={<FactsPage />} />
            <Route path="clinical" element={<ClinicalPage />} />
            <Route path="guidelines" element={<GuidelinesPage />} />
            <Route path="chronology" element={<ChronologyPage />} />
            <Route path="summary" element={<SummaryPage />} />
            <Route path="decision" element={<DecisionPage />} />
            <Route path="signoff" element={<DecisionPage />} />
            <Route path="rtw" element={<RtwPage />} />
            <Route path="activity" element={<ActivityPage />} />
            <Route path="audit"element={<ProtectedRoute perms={["audit:view"]}><AuditPage /></ProtectedRoute>} />
          </Route>
          <Route path="supervisor" element={<ProtectedRoute roles={["claims_supervisor"]}><SupervisorPage /></ProtectedRoute>} />
          <Route path="reports" element={<ProtectedRoute perms={["report:export"]}><ReportsPage /></ProtectedRoute>} />
          <Route path="admin/*" element={<ProtectedRoute perms={["config:manage"]}><AdminPage /></ProtectedRoute>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </CitationProvider>
  );
}
