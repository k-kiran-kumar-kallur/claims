import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1f4f8f", dark: "#163a6b", light: "#e8f0fa" },
    secondary: { main: "#0f766e" },
    error: { main: "#b42318" },
    warning: { main: "#b54708" },
    success: { main: "#067647" },
    background: { default: "#f4f6f9", paper: "#ffffff" },
    text: { primary: "#1d2330", secondary: "#5b6475" },
    divider: "#e3e7ee",
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: '-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontSize: 13,
    h4: { fontWeight: 650, fontSize: "1.45rem" },
    h5: { fontWeight: 650, fontSize: "1.2rem" },
    h6: { fontWeight: 600, fontSize: "1.02rem" },
    subtitle2: { fontWeight: 600 },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: "1px solid #e3e7ee" } } },
    MuiCard: { defaultProps: { elevation: 0 } },
    MuiAppBar: { styleOverrides: { root: { border: "none" } } },
    MuiButton: { defaultProps: { disableElevation: true, size: "small" } },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiChip: { defaultProps: { size: "small" } },
    MuiTableCell: { styleOverrides: { root: { padding: "6px 10px" }, head: { fontWeight: 650, background: "#f7f9fc" } } },
    MuiTooltip: { defaultProps: { arrow: true } },
  },
});

export const severityColor = (s?: string | null): "error" | "warning" | "default" | "info" =>
  s === "high" ? "error" : s === "medium" ? "warning" : s === "low" ? "info" : "default";
