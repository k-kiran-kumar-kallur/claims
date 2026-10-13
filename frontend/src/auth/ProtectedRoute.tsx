import { Navigate, useLocation } from "react-router-dom";
import { Box, CircularProgress, Typography } from "@mui/material";
import { ReactNode } from "react";
import { useAuth } from "./AuthProvider";

export function ProtectedRoute({ children, perms, roles }: { children: ReactNode; perms?: string[]; roles?: string[] }) {
  const { user, loading, can, hasRole } = useAuth();
  const loc = useLocation();
  if (loading)
    return (
      <Box sx={{ display: "grid", placeItems: "center", height: "60vh" }}>
        <CircularProgress />
      </Box>
    );
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if ((perms && !can(...perms)) || (roles && !hasRole(...roles)))
    return (
      <Box sx={{ p: 4 }}>
        <Typography variant="h6">Not available for your role</Typography>
        <Typography color="text.secondary">Your role does not include access to this screen.</Typography>
      </Box>
    );
  return <>{children}</>;
}
