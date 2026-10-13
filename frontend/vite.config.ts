/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Dev settings come from frontend/.env (see .env.example):
//   API_TARGET    backend URL the dev server proxies /api to
//   VITE_DEV_PORT port of the Vite dev server
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const apiTarget = env.API_TARGET || "http://localhost:8020";
  const port = Number(env.VITE_DEV_PORT || 5180);
  return {
    plugins: [react()],
    server: {
      port,
      strictPort: true, // fail loudly instead of silently moving to another port
      proxy: { "/api": { target: apiTarget, changeOrigin: true } },
    },
    build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
    test: { environment: "jsdom", globals: true, setupFiles: ["./src/setupTests.ts"] },
  };
});
