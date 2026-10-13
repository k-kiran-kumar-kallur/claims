# Developer commands
.PHONY: setup backend worker frontend test e2e lint build sample

setup:            ## install backend venv + frontend deps
	cd backend && uv venv -p 3.11 .venv && uv pip install -p .venv/bin/python -r requirements.txt
	cd frontend && npm install

backend:          ## API on :8020 (in-process worker, seeds demo data; also serves the built UI)
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8020

worker:           ## standalone worker (set RUN_WORKER_IN_PROCESS=false for the API)
	cd backend && .venv/bin/python -m app.worker

frontend:         ## Vite dev server on :5180 (proxies /api to API_TARGET in frontend/.env)
	cd frontend && npm run dev

test:             ## backend + frontend tests
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npx vitest run

e2e:              ## Playwright UI end-to-end test (isolated offline backend on :8020)
	cd frontend && npm run e2e

lint:
	cd backend && .venv/bin/ruff check app tests
	cd frontend && npx tsc -b --noEmit

build:            ## production React build served by FastAPI from frontend/dist
	cd frontend && npm run build

sample:           ## write the synthetic sample package to ./sample_package
	cd backend && .venv/bin/python -m app.seed.sample_package ../sample_package
