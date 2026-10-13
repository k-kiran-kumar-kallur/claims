# Claims AI — Agentic Medical Record Summarization (Workers' Compensation)

Implementation of `Agentic_AI_Medical_Record_Summarization_Architecture.md` (the "spec"): a React + FastAPI + SQLite + LangGraph + Gemini platform that takes a workers' compensation medical-record package through the **7 business stages** — intake, classification, clinical review, fact and milestone extraction, guideline review, chronology and summary, decision — with **human-in-the-loop (HITL) checkpoints** for every persona, page/line citations on every AI statement, and a hash-chained audit trail.

```
claims_demo/
├── backend/            FastAPI app, LangGraph workflow, agents, tools, worker, tests
├── frontend/           React 18 + TypeScript + Vite + MUI single-page app
├── deploy/             docker-compose (nginx + api + worker + litestream), nginx.conf
├── data/               app.db, checkpoints.db, encrypted file store (git-ignored, created on first run)
├── secrets/            dev JWT keys + file encryption key (git-ignored, generated in development)
├── .env                your configuration (never commit)  ·  .env.example  ·  Makefile
└── Agentic_AI_Medical_Record_Summarization_Architecture.md   (the spec)
```

## Quick start (development)

Prerequisites: Python 3.11, [uv](https://github.com/astral-sh/uv), Node 20+.

```bash
make setup                     # backend venv + frontend node_modules
make backend                   # API + built UI on http://localhost:8020, in-process worker, seeds demo users + sample claim
make frontend                  # dev UI on http://localhost:5180 (proxies /api to API_TARGET in frontend/.env)
```

Ports are set in `frontend/.env` (`API_TARGET`, `VITE_DEV_PORT`). If you change the backend port, update `API_TARGET` to match. You can also skip the dev server: run `make build` once and open http://localhost:8020 — FastAPI serves `frontend/dist` as a single-origin app.

**Demo accounts** (password `Demo!Passw0rd`, development only, synthetic data):

| Persona | Email | HITL checkpoints |
|---|---|---|
| Medical Records / Summarization Team | `summ@claims.example` | uploads, HITL-0 (shared) |
| Claims Examiner | `examiner@claims.example` | HITL-0, HITL-4 decision |
| Nurse Case Manager | `ncm@claims.example` | HITL-1 timeline, HITL-3 summary |
| Clinical / UR Reviewer | `reviewer@claims.example` | HITL-2 facts, HITL-4 UR determination |
| Claims Supervisor | `supervisor@claims.example` | HITL-5 sign-off, escalations, audit |
| Defence counsel | `attorney@claims.example` | approved reports + chronology (read-only) |
| Administrator | `admin@claims.example` | users, guidelines, prompts, health (no PHI) |

### LLM modes

| `.env` | Behaviour |
|---|---|
| `GOOGLE_API_KEY` set (`LLM_PROVIDER=auto`) | Gemini through its OpenAI-compatible endpoint (`GEMINI_BASE_URL`), model `GEMINI_CHAT_MODEL` (optionally `GEMINI_MODEL_FAST` / `GEMINI_MODEL_REASONING`), embeddings `GEMINI_EMBED_MODEL`. |
| no key, or `LLM_PROVIDER=rules` | **Offline deterministic mode**: every agent has a rule-based implementation that produces the same artifacts with exact citations. Used by the test suite; also the graceful-degradation path when Gemini output is invalid or blocked. The UI shows an "Offline rules mode" chip. |

**Free-tier note:** AI Studio free keys allow ~15 requests/minute per model. The gateway rate-limits to `GEMINI_RPM_LIMIT` (default 15), honours `Retry-After` / "retry in Ns" hints, opens a circuit breaker after repeated failures, and a quota-exhausted run moves to `retrying` and resumes from its LangGraph checkpoint. A full run of the sample claim makes on the order of 60–100 LLM calls, so expect several minutes on the free tier.

> **PHI warning (spec §15.1).** Free-tier AI Studio keys may use prompts for product improvement and carry no BAA. Use synthetic or de-identified data unless you are on a paid tier or Vertex AI under a BAA. With `ALLOW_PHI_TO_LLM=false` (default) the gateway masks SSNs, DOBs, phone numbers, emails and the claimant's name before any prompt leaves the server; baseline fields masked this way are filled from deterministic extraction.

## Walking through the sample claim

The seeded claim `WC-2024-PA-087341` (Marcus T. Delgado — fictitious) has nine files (two multi-document fax packets, operative report, post-op notes, PT notes + extension request, pharmacy history, FCE, CMS-1500 bills, and an `.eml` with a work-status-slip attachment). It contains the situations the spec calls out: fax covers and a blank separator, the ED record faxed twice, an MRI that is referenced and billed but missing, an employer conflict (Meridian Risk Partners vs Keystone Industrial Services), 24 PT visits with a pain plateau and an extension request, a five-month opioid course, an FCE at light capacity against a medium-demand job, and MMI "not yet reached".

1. **Summarization Team** → claim → **Start processing**. The stage stepper updates live over SSE.
2. **Examiner** → *My work queue* → **HITL-0**: confirm the employer (Keystone) and the review question; the baseline is locked.
3. **NCM** → **HITL-1 Timeline**: 9 episodes, duplicates and fax covers removed, missing MRI flagged and requested. Approve, request records, or mark documents for re-classification (loops back through the supervisor router).
4. **Clinical reviewer** → **HITL-2 Facts**: side-by-side source viewer with highlighted lines; `J/K` move, `A` accept, `E` edit (new version, reason required), `R` reject. Resolve any discrepancies.
5. Guideline findings appear (PT visits 24 vs 16, off-guideline extension request, opioid duration, stalled recovery, TTD duration; early MRI and surgery assessed against their exception criteria).
6. **NCM** → **HITL-3 Summary**: one-page summary (≤ 600 words, one rendered page), narrative, MMI status and case-progress reports; edit inline (version diff), regenerate with instructions, or approve.
7. **Examiner** → **HITL-4 Decision**: one-click approve/override per AI flag (override needs a reason), record decisions; **reviewer** records the UR determination in parallel (AI output labelled "AI draft — not a determination").
8. **Supervisor** → **HITL-5** (required for high risk, exceptional complexity, any override or manual escalation; the deciding user cannot sign off). The decision record is sealed (SHA-256), follow-ups are diaried, approved PDFs are rendered and the record is posted to the mock CMS outbox.
9. **Supervisor** → grant the attorney access (`POST /claims/{id}/members`); **attorney** then sees approved reports and the chronology only.

## How the implementation maps to the spec

| Spec | Where |
|---|---|
| §3 roles, permission matrix, separation of duties | `backend/app/core/rbac.py`, `api/deps.py` (`require_permission`), `services/claims.py` (claim scoping), `services/reviews.py` (HITL-4/5 SoD, UR = clinical reviewer only, override reasons) |
| §5.4 worker + SQLite job queue, §6.7 run lifecycle | `backend/app/worker.py`, `services/runs.py` |
| §6.2 graph, §6.3 state, §6.4 node contract, §6.5 HITL, §6.6 supervisor router | `orchestration/graph.py`, `state.py`, `decorators.py`, `hitl.py`, `supervisor.py` |
| §7 agents (intake … record keeping) | `backend/app/agents/` (one module per agent; `extraction/` holds the parallel MMI, RTW, treatment-plan, clinical, IME extractors and the turning-point detector) |
| §8 tools + registry (validation, timeouts, retries, telemetry) | `backend/app/tools/` (19 tools) |
| §5.6 LLM gateway | `backend/app/llm/gateway.py`, `rate_limiter.py`, `redaction.py`; versioned prompts in `agents/prompts/registry.py` (admin-publishable) |
| §10.3 page/line citations | `page_lines` with bounding boxes, `<<D|P|L>>` markers in prompts, `repositories/docs.py` (quote matching with RapidFuzz), citation chips → highlighted page in the UI |
| §11 schema | `backend/app/models/` (67 tables incl. FTS5), `db/init_db.py` (FTS5, append-only audit triggers, sealed-decision immutability), Alembic `0001_initial` |
| §12 API | `backend/app/api/v1/*` — OpenAPI at `/api/docs` (non-production) |
| §13 frontend routes | `frontend/src/App.tsx`, `pages/*` |
| §14 error handling | taxonomy in `core/errors.py`; node retries with backoff, run deferral on quota, failed runs retryable from checkpoint, per-document isolation, outbox for CMS |
| §15 security | Argon2id, RS256 JWT (15 min) + rotating httpOnly refresh cookie with reuse detection, lockout, optional TOTP MFA (required for supervisor/admin in production), Fernet-encrypted file store and PHI columns, CSP/HSTS/X-Frame headers, rate limiting, MIME sniffing + optional ClamAV, PHI-redacting logs |
| §16 logging/monitoring/audit | structlog JSON with correlation ids; `agent_steps`, `tool_calls`, `llm_calls` (encrypted bodies, retention purge); `/metrics` (Prometheus), `/metrics/summary`; hash-chained `audit_log` + `/audit/verify`; Decision Provenance report |
| §17 testing | `backend/tests` (unit + full API E2E through every HITL checkpoint), `frontend/src/**/__tests__` (Vitest), `frontend/e2e` (Playwright: every persona drives the real UI from upload to sealed decision) |

## Configuration and operations

* All settings: `.env.example`. Thresholds and model tiers can also be changed at runtime by an admin (Administration → Prompts & thresholds); prompt templates are versioned.
* **Production:** `deploy/docker-compose.yml` runs nginx (TLS, SSE-safe proxying), the API (`alembic upgrade head` on start), one worker, and Litestream replication. Set `APP_ENV=production`, `FILE_ENCRYPTION_KEY`, JWT key paths, `COOKIE_SECURE=true`, `SEED_DEMO_DATA=false`, `RUN_WORKER_IN_PROCESS=false`. Keep SQLite on local SSD (spec §11.4).
* Health: `GET /api/v1/health/live`, `/health/ready` (DB, file store, worker heartbeat, Gemini reachability).
* Tests and lint: `make test`, `make lint`, `make e2e` (Playwright; starts an isolated offline backend on :8020 — run `npx playwright install chromium` once).

## Known limitations and deviations (v1)

* **Guideline content is a curated sample rule set**, not licensed ODG/ACOEM text (spec §19.2). Import licensed rules via Administration → Guidelines (CSV/JSON).
* **CMS integration is mocked** (`integrations/cms/mock.py`) with an outbox log, as specified for v1.
* **Vector search** uses embeddings stored in SQLite and cosine similarity in NumPy instead of `sqlite-vec` (adequate at v1 volumes); without a Gemini key a local hashing embedding keeps semantic search working.
* **PDF rendering** uses `fpdf2` instead of WeasyPrint (no native system dependencies); `.msg` email needs the optional `extract-msg` package (`.eml` is supported natively).
* **OCR** of scanned pages uses Gemini vision; in offline rules mode scanned pages have no text and are surfaced for human handling.
* The worker processes one job at a time (single SQLite writer, as the spec recommends for v1); classification and extractors fan out inside a run.
* Rule-based (offline) extraction is tuned for labelled clinical sections (`Diagnosis:`, `Work Status:`, `Plan:` …) and is a fallback, not a replacement for the LLM on free-form records.
