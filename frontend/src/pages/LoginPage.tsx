import { Alert, Box, Button, Divider, Link, Paper, Stack, TextField, Typography } from "@mui/material";
import LocalHospitalIcon from "@mui/icons-material/LocalHospital";
import { FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { ApiError } from "../api/client";

const DEMO = [
  ["summ@claims.example", "Summarization Team"], ["examiner@claims.example", "Claims Examiner"], ["ncm@claims.example", "Nurse Case Manager"],
  ["reviewer@claims.example", "Clinical / UR Reviewer"], ["supervisor@claims.example", "Claims Supervisor"], ["attorney@claims.example", "Defence Counsel"],
  ["admin@claims.example", "Administrator"],
];

export default function LoginPage() {
  const { login, user, logoutReason } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState("");
  const [needMfa, setNeedMfa] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (user) return <Navigate to={loc.state?.from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password, mfa);
      navigate(loc.state?.from ?? "/", { replace: true });
    } catch (err) {
      const msg = (err as ApiError).message;
      if (msg.includes("MFA code required")) setNeedMfa(true);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "linear-gradient(135deg, #13294b 0%, #1f4f8f 100%)", p: 2 }}>
      <Paper sx={{ p: 4, width: "100%", maxWidth: 420 }} component="form" onSubmit={submit}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          <LocalHospitalIcon color="primary" />
          <Typography variant="h5" component="h1">Claims AI</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>Workers' compensation medical record summarization</Typography>
        {logoutReason && <Alert severity="info" sx={{ mb: 2 }}>{logoutReason}</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Stack spacing={2}>
          <TextField label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {needMfa && <TextField label="Authenticator code" value={mfa} onChange={(e) => setMfa(e.target.value)} inputProps={{ inputMode: "numeric", maxLength: 6 }} />}
          <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</Button>
        </Stack>
        {isLocal && (
          <>
            <Divider sx={{ my: 3 }}>Demo accounts (synthetic data)</Divider>
            <Typography variant="caption" color="text.secondary">Password: <code>Demo!Passw0rd</code></Typography>
            <Stack spacing={0.25} sx={{ mt: 1 }}>
              {DEMO.map(([e, r]) => (
                <Link key={e} component="button" type="button" variant="body2" underline="hover" sx={{ textAlign: "left" }}
                  onClick={() => { setEmail(e); setPassword("Demo!Passw0rd"); }}>
                  {r} - {e}
                </Link>
              ))}
            </Stack>
          </>
        )}
      </Paper>
    </Box>
  );
}
