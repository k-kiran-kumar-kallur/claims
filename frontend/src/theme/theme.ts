import { alpha, createTheme } from "@mui/material/styles";

const BORDER = "#e4e8ef";
const PRIMARY = "#1f5fbf";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: PRIMARY, dark: "#17468f", light: "#eaf1fc", contrastText: "#fff" },
    secondary: { main: "#0f766e" },
    error: { main: "#c4320a", light: "#fef3f2" },
    warning: { main: "#b54708", light: "#fffaeb" },
    success: { main: "#067647", light: "#ecfdf3" },
    info: { main: "#0e7090", light: "#ecfdff" },
    background: { default: "#f5f7fb", paper: "#ffffff" },
    text: { primary: "#151b28", secondary: "#5d6679" },
    divider: BORDER,
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontSize: 13.5,
    h4: { fontWeight: 700, fontSize: "1.5rem", letterSpacing: -0.2 },
    h5: { fontWeight: 700, fontSize: "1.25rem", letterSpacing: -0.1 },
    h6: { fontWeight: 650, fontSize: "1.05rem" },
    subtitle1: { fontWeight: 650 },
    subtitle2: { fontWeight: 650 },
    overline: { fontWeight: 700, letterSpacing: 0.8, fontSize: "0.68rem", lineHeight: 1.8 },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { WebkitFontSmoothing: "antialiased" },
        "*::-webkit-scrollbar": { width: 10, height: 10 },
        "*::-webkit-scrollbar-thumb": { background: "#cdd3de", borderRadius: 8, border: "2px solid transparent", backgroundClip: "content-box" },
      },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { border: `1px solid ${BORDER}`, boxShadow: "0 1px 2px rgba(16,24,40,0.04)" } },
    },
    MuiPopover: { styleOverrides: { paper: { boxShadow: "0 12px 32px rgba(16,24,40,0.14)" } } },
    MuiMenu: { styleOverrides: { paper: { boxShadow: "0 12px 32px rgba(16,24,40,0.14)" } } },
    MuiDrawer: { styleOverrides: { paper: { boxShadow: "none" } } },
    MuiCard: { defaultProps: { elevation: 0 } },
    MuiAppBar: { styleOverrides: { root: { border: "none", boxShadow: "none" } } },
    MuiButton: {
      defaultProps: { disableElevation: true, size: "small" },
      styleOverrides: { root: { borderRadius: 8, paddingInline: 12 }, sizeLarge: { paddingBlock: 9 } },
    },
    MuiIconButton: { styleOverrides: { root: { borderRadius: 8 } } },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiOutlinedInput: { styleOverrides: { root: { backgroundColor: "#fff" } } },
    MuiChip: { defaultProps: { size: "small" }, styleOverrides: { root: { fontWeight: 550, borderRadius: 6 } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 10, alignItems: "center" } } },
    MuiTableCell: {
      styleOverrides: {
        root: { padding: "9px 12px", borderColor: BORDER },
        head: { fontWeight: 650, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: 0.5, color: "#5d6679", background: "#f8fafc" },
      },
    },
    MuiTableRow: { styleOverrides: { root: { "&.MuiTableRow-hover:hover": { backgroundColor: alpha(PRIMARY, 0.04) } } } },
    MuiTab: { styleOverrides: { root: { textTransform: "none", fontWeight: 600, minWidth: 0, paddingInline: 14 } } },
    MuiTooltip: { defaultProps: { arrow: true }, styleOverrides: { tooltip: { fontSize: 12 } } },
    MuiLinearProgress: { styleOverrides: { root: { borderRadius: 4 } } },
    MuiDialog: { styleOverrides: { paper: { borderRadius: 14 } } },
  },
});

export const severityColor = (s?: string | null): "error" | "warning" | "default" | "info" =>
  s === "high" ? "error" : s === "medium" ? "warning" : s === "low" ? "info" : "default";

export const riskColor = (r?: number | null): "error" | "warning" | "success" | "default" =>
  r == null ? "default" : r >= 0.7 ? "error" : r >= 0.4 ? "warning" : "success";
