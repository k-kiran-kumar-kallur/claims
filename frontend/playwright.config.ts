import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const dataDir = path.join(os.tmpdir(), `claims-ai-e2e-${Date.now()}`);

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:8020", viewport: { width: 1440, height: 900 }, screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: {
    // isolated offline (rules-mode) backend serving the production React build
    command: "../backend/.venv/bin/uvicorn app.main:app --app-dir ../backend --port 8020",
    url: "http://localhost:8020/api/v1/health/live",
    reuseExistingServer: false,
    timeout: 120_000,
    env: { DATA_DIR: dataDir, SECRETS_DIR: path.join(dataDir, "secrets"), LLM_PROVIDER: "rules", SEED_DEMO_DATA: "true",
           RUN_WORKER_IN_PROCESS: "true", RATE_LIMIT_LOGIN: "200/minute", LOG_LEVEL: "WARNING", WORKER_POLL_SECONDS: "0.3" },
  },
});
