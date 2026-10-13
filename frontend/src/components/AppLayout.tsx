import {
  AppBar, Autocomplete, Avatar, Badge, Box, Button, Chip, Divider, Drawer, IconButton, InputAdornment, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem,
  Popover, Stack, TextField, Toolbar, Tooltip, Typography, useMediaQuery,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import LogoutIcon from "@mui/icons-material/Logout";
import NotificationsNoneIcon from "@mui/icons-material/NotificationsNone";
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
import { ReactNode, useEffect, useState } from "react";
import { Link as RouterLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import { ROLE_LABELS, type Claim } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { RelativeTime } from "./common";
import { ErrorBoundary } from "./ErrorBoundary";

const WIDTH = 240;

/** Top-bar claim finder: type a claim number, claimant or employer and jump straight to the claim. */
function ClaimSearch() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => { const id = window.setTimeout(() => setTerm(input.trim()), 250); return () => window.clearTimeout(id); }, [input]);
  const q = useQuery({ queryKey: ["claims", "search", term], queryFn: () => api.get<Claim[]>(`/claims${qs({ q: term, page_size: 8 })}`), enabled: term.length >= 2 });
  return (
    <Autocomplete<Claim, false, false, false>
      size="small" forcePopupIcon={false} sx={{ width: { md: 280, lg: 340 } }} options={term.length >= 2 ? q.data ?? [] : []} loading={q.isFetching}
      filterOptions={(o) => o} getOptionLabel={(c) => c.claim_number} inputValue={input} value={null} blurOnSelect clearOnBlur
      onInputChange={(_, v, reason) => reason !== "reset" && setInput(v)}
      onChange={(_, c) => { if (c) { setInput(""); navigate(`/claims/${c.id}`); } }}
      noOptionsText={term.length < 2 ? "Type at least 2 characters" : "No matching claims"}
      renderOption={(props, c) => (
        <li {...props} key={c.id}>
          <Box>
            <Typography variant="body2" fontWeight={650}>{c.claim_number}</Typography>
            <Typography variant="caption" color="text.secondary">{c.claimant ?? "-"} · {c.employer_name ?? "-"}</Typography>
          </Box>
        </li>
      )}
      renderInput={(params) => (
        <TextField {...params} placeholder="Find a claim..." inputProps={{ ...params.inputProps, "aria-label": "Find a claim" }}
          InputProps={{ ...params.InputProps, startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" sx={{ color: "rgba(255,255,255,0.7)" }} /></InputAdornment> }}
          sx={{ "& .MuiOutlinedInput-root": { bgcolor: "rgba(255,255,255,0.1)", color: "#fff", "& fieldset": { borderColor: "rgba(255,255,255,0.18)" }, "&:hover fieldset": { borderColor: "rgba(255,255,255,0.4)" } },
            "& input::placeholder": { color: "rgba(255,255,255,0.7)", opacity: 1 }, "& .MuiAutocomplete-popupIndicator, & .MuiAutocomplete-clearIndicator": { color: "rgba(255,255,255,0.7)" } }} />
      )} />
  );
}

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
        <Box sx={{ width: { xs: "calc(100vw - 32px)", sm: 380 }, maxHeight: 480, overflow: "auto" }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 1.5, py: 1 }}>
            <Typography variant="subtitle2">Notifications</Typography>
            {unread > 0 && <Button size="small" onClick={() => mark.mutate()}>Mark all as read</Button>}
          </Stack>
          <Divider />
          {(q.data?.data ?? []).length === 0 && (
            <Stack alignItems="center" spacing={0.5} sx={{ p: 4, color: "text.secondary" }}>
              <NotificationsNoneIcon />
              <Typography variant="body2">You're all caught up</Typography>
            </Stack>
          )}
          {(q.data?.data ?? []).map((n: any) => (
            <ListItemButton key={n.id} onClick={() => { setAnchor(null); if (n.link) navigate(n.link.startsWith("/reviews/") ? `/claims/${n.claim_id}` : n.link); }}
              sx={{ alignItems: "flex-start", bgcolor: n.read_at ? undefined : "primary.light", borderBottom: "1px solid", borderColor: "divider" }}>
              <ListItemText primary={n.title} secondary={<>{n.body}{n.body && <br />}<RelativeTime iso={n.created_at} variant="caption" /></>}
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
  const initials = user?.full_name.split(" ").map((p) => p[0]).slice(0, 2).join("");
  const nav = (
    <Box sx={{ width: WIDTH, pt: 1.5, display: "flex", flexDirection: "column", height: "100%" }}>
      <Typography variant="overline" color="text.secondary" sx={{ px: 3 }}>Workspace</Typography>
      <List dense sx={{ flex: 1 }}>
        {items.filter((i) => i.show).map((i) => {
          const active = i.to === "/" ? loc.pathname === "/" : loc.pathname === i.to || (i.to === "/claims" && loc.pathname.startsWith("/claims/") && loc.pathname !== "/claims/new") || (i.to !== "/claims" && loc.pathname.startsWith(i.to) && i.to !== "/");
          return (
            <ListItemButton key={i.to} component={RouterLink} to={i.to} selected={active} onClick={() => setOpen(false)}
              sx={{ mx: 1.5, borderRadius: 2, mb: 0.5, py: 0.9, "&.Mui-selected": { bgcolor: "primary.light", color: "primary.main" }, "&.Mui-selected:hover": { bgcolor: "primary.light" } }}>
              <ListItemIcon sx={{ minWidth: 36, color: active ? "primary.main" : "text.secondary" }}>{i.icon}</ListItemIcon>
              <ListItemText primary={i.label} primaryTypographyProps={{ fontWeight: active ? 650 : 500, fontSize: 14 }} />
            </ListItemButton>
          );
        })}
      </List>
      <Box sx={{ m: 1.5, p: 1.5, borderRadius: 2, bgcolor: "#f5f7fb", border: "1px solid", borderColor: "divider" }}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Avatar sx={{ width: 32, height: 32, fontSize: 13, bgcolor: "primary.main" }}>{initials}</Avatar>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="body2" fontWeight={650} noWrap>{user?.full_name}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap component="div">{user?.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</Typography>
          </Box>
          <Tooltip title="Sign out"><IconButton size="small" onClick={() => logout()} aria-label="Sign out"><LogoutIcon fontSize="small" /></IconButton></Tooltip>
        </Stack>
      </Box>
    </Box>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: "#0f2444" }}>
        <Toolbar variant="dense" sx={{ gap: 1, minHeight: 56 }}>
          {mobile && <IconButton color="inherit" onClick={() => setOpen(true)} aria-label="Open navigation"><MenuIcon /></IconButton>}
          <Box component={RouterLink} to="/" sx={{ display: "flex", alignItems: "center", gap: 1, color: "inherit", textDecoration: "none" }}>
            <Box sx={{ width: 30, height: 30, borderRadius: 1.5, bgcolor: "rgba(127,179,255,0.18)", display: "grid", placeItems: "center" }}>
              <LocalHospitalIcon sx={{ color: "#7fb3ff", fontSize: 20 }} />
            </Box>
            <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: 0.2 }}>Claims AI</Typography>
          </Box>
          <Typography variant="body2" sx={{ opacity: 0.7, display: { xs: "none", lg: "block" }, ml: 1 }}>Workers' Compensation Medical Records</Typography>
          <Box sx={{ flex: 1 }} />
          {phi && !mobile && <ClaimSearch />}
          {user?.llm_mode === "rules" && (
            <Tooltip title="No Gemini API key configured: deterministic offline extraction is used. Set GOOGLE_API_KEY to enable Gemini.">
              <Chip label="Offline rules mode" size="small" sx={{ bgcolor: "#fff3cd", color: "#7a5300" }} />
            </Tooltip>
          )}
          <NotificationBell />
          <Tooltip title="Account">
            <IconButton onClick={(e) => setMenu(e.currentTarget)} aria-label="Account menu">
              <Avatar sx={{ width: 30, height: 30, fontSize: 13, bgcolor: "#2f6bc0" }}>{initials}</Avatar>
            </IconButton>
          </Tooltip>
          <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
            <Box sx={{ px: 2, py: 1 }}>
              <Typography variant="subtitle2">{user?.full_name}</Typography>
              <Typography variant="caption" color="text.secondary">{user?.email}</Typography>
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>{user?.roles.map((r) => <Chip key={r} label={ROLE_LABELS[r] ?? r} size="small" />)}</Stack>
            </Box>
            <Divider />
            <MenuItem onClick={() => { setMenu(null); logout(); }}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer variant={mobile ? "temporary" : "permanent"} open={mobile ? open : true} onClose={() => setOpen(false)}
        sx={{ width: WIDTH, flexShrink: 0, "& .MuiDrawer-paper": { width: WIDTH, boxSizing: "border-box", borderRight: "1px solid", borderColor: "divider" } }}>
        <Toolbar variant="dense" sx={{ minHeight: "56px !important" }} />
        {nav}
      </Drawer>
      <Box component="main" sx={{ flex: 1, minWidth: 0, p: { xs: 1.5, md: 3 }, pt: { xs: 9, md: 10 }, maxWidth: 1680, mx: "auto", width: "100%" }}>
        <ErrorBoundary resetKey={loc.pathname}><Outlet /></ErrorBoundary>
      </Box>
    </Box>
  );
}
