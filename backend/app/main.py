"""FastAPI application factory (spec §5, §12, §15, §16)."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.core.correlation import correlation_id_var, new_correlation_id, user_id_var
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.main_limiter import limiter

log = get_logger("api")


def problem(status: int, title: str, detail: str, type_: str = "about:blank", **extra) -> JSONResponse:
    body = {"type": type_, "title": title, "status": status, "detail": detail, "correlation_id": correlation_id_var.get(), **extra}
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.LOG_LEVEL, service="api")
    from app.db.init_db import init_db
    from app.db.session import session_scope

    init_db()
    if settings.SEED_DEMO_DATA:
        from app.seed.demo import seed_all
        with session_scope() as db:
            seed_all(db, with_sample_claim=True)
    else:
        from app.seed.reference import seed_reference
        with session_scope() as db:
            seed_reference(db)
    if settings.RUN_WORKER_IN_PROCESS:
        from app.worker import start_in_process
        start_in_process()
    log.info("api_started", env=settings.APP_ENV, llm_mode=settings.llm_mode)
    yield
    if settings.RUN_WORKER_IN_PROCESS:
        from app.worker import stop_in_process
        stop_in_process()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs" if not settings.is_production else None, openapi_url="/api/openapi.json",
                  description="Agentic AI medical-record summarization for workers' compensation claims.")
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    if not settings.is_production:  # same-origin behind the reverse proxy in production (spec §5.3)
        app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def correlation_and_headers(request: Request, call_next):
        cid = request.headers.get("x-request-id") or new_correlation_id()
        correlation_id_var.set(cid[:64])
        user_id_var.set(None)
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = cid[:64]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            log.info("http_request", method=request.method, path=request.url.path, status=response.status_code,
                     duration_ms=int((time.monotonic() - started) * 1000))
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return problem(exc.status_code, exc.title, exc.detail, exc.type_, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return problem(422, "Validation Error", errs[0]["msg"] if errs else "Invalid request", "/problems/validation", errors=errs)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return problem(exc.status_code, "HTTP Error", str(exc.detail))

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_: Request, exc: RateLimitExceeded):
        return problem(429, "Too Many Requests", f"Rate limit exceeded: {exc.detail}", "/problems/rate-limit")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.error("unhandled_error", error=f"{type(exc).__name__}: {exc}")
        return problem(500, "Internal Server Error", "An unexpected error occurred. Quote the correlation id when reporting it.")

    from app.api.v1 import admin, auth, claims, clinical, documents, outputs, reviews, runs
    for module in (auth, claims, documents, runs, clinical, outputs, reviews, admin):
        app.include_router(module.router, prefix="/api/v1")

    dist: Path = settings.FRONTEND_DIST
    if dist.exists():  # single-origin deployment: serve the React build (SPA fallback)
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return problem(404, "Not Found", "Unknown API route")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
