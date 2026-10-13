"""Application settings (pydantic-settings, loaded from the repository-level `.env`)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_ENV: Literal["development", "test", "production"] = "development"
    APP_NAME: str = "Claims AI - Medical Record Summarization"
    LOG_LEVEL: str = "INFO"

    # ---- storage -------------------------------------------------------------------------
    DATA_DIR: Path = REPO_DIR / "data"
    DATABASE_PATH: Path | None = None
    CHECKPOINT_DB_PATH: Path | None = None
    FILE_STORE_PATH: Path | None = None
    SECRETS_DIR: Path = REPO_DIR / "secrets"
    FILE_ENCRYPTION_KEY: str | None = None  # urlsafe base64 32 bytes (Fernet); generated in dev

    # ---- auth ----------------------------------------------------------------------------
    JWT_PRIVATE_KEY_PATH: Path | None = None
    JWT_PUBLIC_KEY_PATH: Path | None = None
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    COOKIE_SECURE: bool = False  # True in production (HTTPS)

    # ---- LLM (Gemini via the OpenAI-compatible endpoint) -----------------------------------
    LLM_PROVIDER: Literal["auto", "gemini", "rules"] = "auto"
    GEMINI_API_KEY: str | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GEMINI_CHAT_MODEL: str = "gemini-2.5-flash"
    GEMINI_MODEL_FAST: str | None = None
    GEMINI_MODEL_REASONING: str | None = None
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"
    GEMINI_RPM_LIMIT: int = 15  # AI Studio free tier; raise on a paid tier
    GEMINI_TPM_LIMIT: int = 1_000_000
    GEMINI_TIMEOUT_SECONDS: float = 120.0
    LLM_MAX_RETRIES: int = 5
    LLM_CIRCUIT_FAILURES: int = 5
    LLM_CIRCUIT_COOLDOWN_SECONDS: int = 60
    ALLOW_PHI_TO_LLM: bool = False
    LLM_BODY_RETENTION_DAYS: int = 30
    EMBEDDING_DIM: int = 768

    # ---- business thresholds ----------------------------------------------------------------
    CONFIDENCE_THRESHOLD_BASELINE: float = 0.95
    CONFIDENCE_THRESHOLD_CLASSIFICATION: float = 0.85
    CONFIDENCE_THRESHOLD_FACT: float = 0.90
    QUOTE_MATCH_THRESHOLD: float = 0.90
    RISK_ESCALATION_THRESHOLD: float = 0.7
    TREATMENT_GAP_DAYS: int = 30
    URGENT_SURGERY_WINDOW_DAYS: int = 7
    LOOP_MAX: int = 2
    ONE_PAGE_WORD_LIMIT: int = 600
    HITL_SLA_HOURS: dict[str, int] = {
        "HITL-0": 24, "HITL-1": 24, "HITL-2": 48, "HITL-3": 24, "HITL-4": 48, "HITL-4-UR": 72, "HITL-5": 48,
    }

    # ---- uploads ---------------------------------------------------------------------------
    MAX_UPLOAD_MB: int = 200
    MAX_PAGES_PER_RUN: int = 2000
    CHUNK_UPLOAD_MAX_MB: int = 8

    # ---- runtime ---------------------------------------------------------------------------
    CORS_ORIGINS: list[str] = ["http://localhost:5180"]
    RUN_WORKER_IN_PROCESS: bool = True
    WORKER_POLL_SECONDS: float = 1.0
    JOB_MAX_ATTEMPTS: int = 3
    NODE_MAX_RETRIES: int = 3
    SEED_DEMO_DATA: bool = True
    DEMO_PASSWORD: str = "Demo!Passw0rd"
    RATE_LIMIT_DEFAULT: str = "300/minute"
    RATE_LIMIT_LOGIN: str = "10/minute"
    IDLE_LOGOUT_MINUTES: int = 15
    FRONTEND_DIST: Path = REPO_DIR / "frontend" / "dist"

    # ---- derived ---------------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.DATABASE_PATH or self.DATA_DIR / "app.db"

    @property
    def checkpoint_path(self) -> Path:
        return self.CHECKPOINT_DB_PATH or self.DATA_DIR / "checkpoints.db"

    @property
    def file_store(self) -> Path:
        return self.FILE_STORE_PATH or self.DATA_DIR / "files"

    @property
    def model_fast(self) -> str:
        return self.GEMINI_MODEL_FAST or self.GEMINI_CHAT_MODEL

    @property
    def model_reasoning(self) -> str:
        return self.GEMINI_MODEL_REASONING or self.GEMINI_CHAT_MODEL

    @property
    def llm_mode(self) -> str:
        """`gemini` when an API key is configured (or forced), `rules` = deterministic offline mode."""
        if self.LLM_PROVIDER == "auto":
            return "gemini" if self.GEMINI_API_KEY else "rules"
        return self.LLM_PROVIDER

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
