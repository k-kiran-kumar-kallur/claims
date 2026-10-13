import {
  AppBar, Avatar, Badge, Box, Chip, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem,
  Popover, Stack, Toolbar, Tooltip, Typography, useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import InboxIcon from "@mui/icons-material/Inbox";
import FolderSharedIcon from "@mui/icons-material/FolderShared";
import NoteAddIcon from "@mui/icons-material/NoteAdd";
import SupervisorAccountIcon from "@mui/icons-material/SupervisorAccount";
import DescriptionIcon from "@mui/icons-material/Description";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import NotificationsIcon from "@mui/icons-material/Notifications";
import MenuIcon from "@mui/icons-material/Menu";
import LocalHospitalIcon from "@mui/icons-material/LocalHospital";
import { ReactNode, useState } from "react";
import { Link as RouterLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ROLE_LABELS } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { fmtDateTime } from "./common";
import { ErrorBoundary } from "./ErrorBoundary";

const WIDTH = 228;

interface NavItem { to: string; label: string; icon: ReactNode; show: boolean }

function NotificationBell() {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.getEnv<any[]>("/notifications"), refetchInterval: 30000 });
  const mark = useMutation({ mutationFn: () => api.post("/notifications/read"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const unread = (q.data?.meta?.unread as number) ?? 0;
  return (
    <>
      <Tooltip title="Notifications">
        <IconButton color="inherit" onClick={(e) => setAnchor(e.currentTarget)} aria-label={`${unread} unread notifications`}>
          <Badge badgeContent={unread} color="error"><NotificationsIcon /></Badge>
        </IconButton>
      </Tooltip>
      <Popover open={!!anchor} anchorEl={anchor} onClose={() => { setAnchor(null); if (unread) mark.mutate(); }}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }} transformOrigin={{ vertical: "top", horizontal: "right" }}>
        <Box sx={{ width: 380, maxHeight: 460, overflow: "auto" }}>
          <Typography variant="subtitle2" sx={{ p: 1.5 }}>Notifications</Typography>
          <Divider />
          {(q.data?.data ?? []).length === 0 && <Typography sx={{ p: 2 }} color="text.secondary" variant="body2">No notifications</Typography>}
          {(q.data?.data ?? []).map((n: any) => (
            <ListItemButton key={n.id} onClick={() => { setAnchor(null); if (n.link) navigate(n.link.startsWith("/reviews/") ? `/claims/${n.claim_id}` : n.link); }}
              sx={{ alignItems: "flex-start", bgcolor: n.read_at ? undefined : "primary.light" }}>
              <ListItemText primary={n.title} secondary={<>{n.body}<br />{fmtDateTime(n.created_at)}</>}
                primaryTypographyProps={{ variant: "body2", fontWeight: n.read_at ? 400 : 650 }} secondaryTypographyProps={{ variant: "caption" }} />
            </ListItemButton>
          ))}
        </Box>
      </Popover>
    </>
  );
}

export function AppLayout() {
  const { user, logout, can, hasRole } = useAuth();
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("md"));
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  const loc = useLocation();
  const phi = can("document:view_phi");
  const items: NavItem[] = [
    { to: "/", label: "My work queue", icon: <InboxIcon />, show: phi && !hasRole("attorney") || hasRole("claims_supervisor") },
    { to: "/claims", label: "Claims", icon: <FolderSharedIcon />, show: phi && !(user?.roles.length === 1 && hasRole("attorney")) },
    { to: "/claims/new", label: "New claim & upload", icon: <NoteAddIcon />, show: can("claim:create") },
    { to: "/supervisor", label: "Supervisor console", icon: <SupervisorAccountIcon />, show: hasRole("claims_supervisor") },
    { to: "/reports", label: "Approved reports", icon: <DescriptionIcon />, show: can("report:export") },
    { to: "/admin", label: "Administration", icon: <AdminPanelSettingsIcon />, show: can("config:manage") },
  ];
  const nav = (
    <Box sx={{ width: WIDTH, pt: 1 }}>
      <List dense>
        {items.filter((i) => i.show).map((i) => {
          const active = i.to === "/" ? loc.pathname === "/" : loc.pathname === i.to || (i.to === "/claims" && loc.pathname.startsWith("/claims/") && loc.pathname !== "/claims/new") || (i.to !== "/claims" && loc.pathname.startsWith(i.to) && i.to !== "/");
          return (
            <ListItemButton key={i.to} component={RouterLink} to={i.to} selected={active} onClick={() => setOpen(false)} sx={{ mx: 1, borderRadius: 1.5, mb: 0.25 }}>
              <ListItemIcon sx={{ minWidth: 36, color: active ? "primary.main" : undefined }}>{i.icon}</ListItemIcon>
              <ListItemText primary={i.label} primaryTypographyProps={{ fontWeight: active ? 650 : 500 }} />
            </ListItemButton>
          );
        })}
      </List>
    </Box>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: "#13294b" }}>
        <Toolbar variant="dense" sx={{ gap: 1 }}>
          {mobile && <IconButton color="inherit" onClick={() => setOpen(true)} aria-label="Open navigation"><MenuIcon /></IconButton>}
          <LocalHospitalIcon sx={{ color: "#7fb3ff" }} />
          <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: 0.2 }}>Claims AI</Typography>
          <Typography variant="body2" sx={{ opacity: 0.75, display: { xs: "none", sm: "block" } }}>Medical Record Summarization - Workers' Compensation</Typography>
          <Box sx={{ flex: 1 }} />
          {user?.llm_mode === "rules" && (
            <Tooltip title="No Gemini API key configured: deterministic offline extraction is used. Set GOOGLE_API_KEY to enable Gemini.">
              <Chip label="Offline rules mode" size="small" sx={{ bgcolor: "#fff3cd", color: "#7a5300" }} />
            </Tooltip>
          )}
          <NotificationBell />
          <Tooltip title="Account">
            <IconButton onClick={(e) => setMenu(e.currentTarget)} aria-label="Account menu">
              <Avatar sx={{ width: 30, height: 30, fontSize: 13, bgcolor: "#2f6bc0" }}>{user?.full_name.split(" ").map((p) => p[0]).slice(0, 2).join("")}</Avatar>
            </IconButton>
          </Tooltip>
          <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
            <Box sx={{ px: 2, py: 1 }}>
              <Typography variant="subtitle2">{user?.full_name}</Typography>
              <Typography variant="caption" color="text.secondary">{user?.email}</Typography>
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>{user?.roles.map((r) => <Chip key={r} label={ROLE_LABELS[r] ?? r} size="small" />)}</Stack>
            </Box>
            <Divider />
            <MenuItem onClick={() => { setMenu(null); logout(); }}>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer variant={mobile ? "temporary" : "permanent"} open={mobile ? open : true} onClose={() => setOpen(false)}
        sx={{ width: WIDTH, flexShrink: 0, "& .MuiDrawer-paper": { width: WIDTH, boxSizing: "border-box", borderRight: "1px solid", borderColor: "divider" } }}>
        <Toolbar variant="dense" />
        {nav}
      </Drawer>
      <Box component="main" sx={{ flex: 1, minWidth: 0, p: { xs: 1.5, md: 3 }, pt: { xs: 8, md: 9 } }}>
        <ErrorBoundary resetKey={loc.pathname}><Outlet /></ErrorBoundary>
      </Box>
    </Box>
  );
}
