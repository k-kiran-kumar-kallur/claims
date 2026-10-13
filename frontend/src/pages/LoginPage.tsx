import { Alert, Box, Button, ButtonBase, CircularProgress, Divider, IconButton, InputAdornment, Paper, Stack, TextField, Typography } from "@mui/material";
import LocalHospitalIcon from "@mui/icons-material/LocalHospital";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import VerifiedUserIcon from "@mui/icons-material/VerifiedUser";
import { FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { ApiError } from "../api/client";

const DEMO = [
  ["summ@claims.example", "Summarization Team"], ["examiner@claims.example", "Claims Examiner"], ["ncm@claims.example", "Nurse Case Manager"],
  ["reviewer@claims.example", "Clinical / UR Reviewer"], ["supervisor@claims.example", "Claims Supervisor"], ["attorney@claims.example", "Defence Counsel"],
  ["admin@claims.example", "Administrator"],
];
const DEMO_PW = "Demo!Passw0rd";

const FEATURES = [
  { icon: <AutoAwesomeIcon />, title: "AI-organized records", text: "Faxes, scans and PDFs classified into a cited medical timeline." },
  { icon: <FactCheckIcon />, title: "Human-in-the-loop", text: "Every fact, summary and decision is reviewed by the right role." },
  { icon: <VerifiedUserIcon />, title: "Audit-ready", text: "Hash-chained audit trail and sealed decision records." },
];

export default function LoginPage() {
  const { login, user, logoutReason } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [mfa, setMfa] = useState("");
  const [needMfa, setNeedMfa] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (user) return <Navigate to={loc.state?.from ?? "/"} replace />;

  const doLogin = async (e: string, p: string) => {
    setBusy(true);
    setError(null);
    try {
      await login(e, p, mfa);
      navigate(loc.state?.from ?? "/", { replace: true });
    } catch (err) {
      const msg = (err as ApiError).message;
      if (msg.includes("MFA code required")) setNeedMfa(true);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); doLogin(email, password); };

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", gridTemplateColumns: { xs: "1fr", md: "1.1fr 1fr" }, bgcolor: "background.default" }}>
      <Box sx={{ display: { xs: "none", md: "flex" }, flexDirection: "column", justifyContent: "center", p: 8, color: "#fff",
        background: "radial-gradient(circle at 20% 20%, #2a5fae 0%, transparent 55%), linear-gradient(135deg, #0f2444 0%, #1f4f8f 100%)" }}>
        <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 4 }}>
          <Box sx={{ width: 42, height: 42, borderRadius: 2, bgcolor: "rgba(127,179,255,0.2)", display: "grid", placeItems: "center" }}><LocalHospitalIcon sx={{ color: "#9cc4ff" }} /></Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>Claims AI</Typography>
        </Stack>
        <Typography variant="h4" sx={{ fontSize: "2rem", lineHeight: 1.25, mb: 1.5, maxWidth: 480 }}>Medical record summarization for workers' compensation</Typography>
        <Typography sx={{ opacity: 0.8, mb: 5, maxWidth: 460 }}>From an unsorted record package to a reviewed, cited claim decision.</Typography>
        <Stack spacing={2.5} sx={{ maxWidth: 440 }}>
          {FEATURES.map((f) => (
            <Stack key={f.title} direction="row" spacing={1.75}>
              <Box sx={{ width: 36, height: 36, borderRadius: 1.5, bgcolor: "rgba(255,255,255,0.1)", display: "grid", placeItems: "center", flexShrink: 0, "& svg": { fontSize: 20, color: "#9cc4ff" } }}>{f.icon}</Box>
              <Box>
                <Typography fontWeight={650}>{f.title}</Typography>
                <Typography variant="body2" sx={{ opacity: 0.75 }}>{f.text}</Typography>
              </Box>
            </Stack>
          ))}
        </Stack>
      </Box>

      <Box sx={{ display: "grid", placeItems: "center", p: { xs: 2, sm: 4 } }}>
        <Box sx={{ width: "100%", maxWidth: 420 }}>
          <Paper sx={{ p: { xs: 3, sm: 4 }, boxShadow: "0 12px 40px rgba(16,24,40,0.08)" }} component="form" onSubmit={submit}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5, display: { md: "none" } }}>
              <LocalHospitalIcon color="primary" /><Typography variant="h6">Claims AI</Typography>
            </Stack>
            <Typography variant="h5" component="h1">Sign in</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>Welcome back. Sign in to continue to your work queue.</Typography>
            {logoutReason && <Alert severity="info" sx={{ mb: 2 }}>{logoutReason}</Alert>}
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            <Stack spacing={2}>
              <TextField label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus fullWidth />
              <TextField label="Password" type={show ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required fullWidth
                InputProps={{ endAdornment: (
                  <InputAdornment position="end">
                    <IconButton onClick={() => setShow(!show)} edge="end" size="small" aria-label={show ? "Hide characters" : "Show characters"}>
                      {show ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                    </IconButton>
                  </InputAdornment>) }} />
              {needMfa && <TextField label="Authenticator code" value={mfa} onChange={(e) => setMfa(e.target.value)} autoFocus helperText="Enter the 6-digit code from your authenticator app" inputProps={{ inputMode: "numeric", maxLength: 6 }} />}
              <Button type="submit" variant="contained" size="large" disabled={busy} startIcon={busy ? <CircularProgress size={16} color="inherit" /> : undefined}>
                {busy ? "Signing in..." : "Sign in"}
              </Button>
            </Stack>
          </Paper>
          {isLocal && (
            <Paper sx={{ p: 2.5, mt: 2 }}>
              <Divider sx={{ mb: 1.5 }}><Typography variant="caption" color="text.secondary">Demo accounts (synthetic data) - click to sign in</Typography></Divider>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 1 }}>
                {DEMO.map(([e, r]) => (
                  <ButtonBase key={e} disabled={busy} onClick={() => { setEmail(e); setPassword(DEMO_PW); doLogin(e, DEMO_PW); }}
                    sx={{ justifyContent: "flex-start", textAlign: "left", p: 1, borderRadius: 1.5, border: "1px solid", borderColor: "divider", "&:hover": { borderColor: "primary.main", bgcolor: "primary.light" } }}>
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" fontWeight={650} noWrap>{r}</Typography>
                      <Typography variant="caption" color="text.secondary" noWrap component="div">{e}</Typography>
                    </Box>
                  </ButtonBase>
                ))}
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>Password for all demo accounts: <code>{DEMO_PW}</code></Typography>
            </Paper>
          )}
        </Box>
      </Box>
    </Box>
  );
}
