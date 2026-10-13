import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { theme } from "./theme/theme";
import { AuthProvider } from "./auth/AuthProvider";
import { ToastHost, toast } from "./components/Toast";
import type { ApiError } from "./api/client";
import App from "./App";

const queryClient = new QueryClient({
  // every mutation reports its outcome; set meta.success for a confirmation, meta.silent to opt out
  mutationCache: new MutationCache({
    onError: (err, _v, _c, m) => {
      if (m.meta?.silent) return;
      const e = err as ApiError;
      toast.error(e.message || "Action failed", e.correlationId ? `Reference: ${e.correlationId}` : undefined);
    },
    onSuccess: (_d, _v, _c, m) => { if (typeof m.meta?.success === "string") toast.success(m.meta.success); },
  }),
  defaultOptions: {
    queries: { retry: (count, err: any) => count < 2 && !(err?.status >= 400 && err?.status < 500), staleTime: 10_000, refetchOnWindowFocus: false },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
        <ToastHost />
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
