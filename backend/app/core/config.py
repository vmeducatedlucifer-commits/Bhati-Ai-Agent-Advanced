"""Application settings, loaded from environment or `backend/.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- app -------------------------------------------------------------
    APP_NAME: str = "Rawal AI"
    ENV: Literal["dev", "prod"] = "dev"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"

    # ---- security --------------------------------------------------------
    SECRET_KEY: str = "dev-secret-change-me-in-production-please-use-64-chars"
    JWT_SECRET: str = "dev-jwt-secret-change-me-in-production-please-64-chars"
    JWT_ALGORITHM: str = "HS256"
    JWT_TTL_HOURS: int = 72
    JWT_ISSUER: str = "bhati-ai-agent"
    JWT_AUDIENCE: str = "bhati-ai-agent-app"
    # When empty, auth is open (single-user local mode). Set to enable login.
    AUTH_PASSWORD: str = ""
    AUTH_USERNAME: str = "bhati"
    # Prod must never boot open by accident: set a password, or explicitly opt
    # into an anonymous instance with ALLOW_ANONYMOUS=true.
    ALLOW_ANONYMOUS: bool = False

    # ---- storage ---------------------------------------------------------
    DATA_DIR: str = str(REPO_DIR / "data")
    WORKSPACE_ROOT: str = str(REPO_DIR / "data" / "workspaces")
    DATABASE_URL: str = ""
    MONGO_URI: str = ""
    MONGODB_URI: str = ""
    DATABASE_NAME: str = "bhati_ai_agent"
    MONGODB_DB_NAME: str = ""
    GDRIVE_CREDENTIALS_JSON: str = ""
    GDRIVE_FOLDER_ID: str = ""

    @property
    def mongo_uri(self) -> str:
        return self.MONGO_URI or self.MONGODB_URI

    @property
    def database_name(self) -> str:
        return self.MONGODB_DB_NAME or self.DATABASE_NAME or "bhati_ai_agent"

    # ---- llm -------------------------------------------------------------
    DEFAULT_LLM_BASE_URL: str = "https://api.openai.com/v1"
    DEFAULT_LLM_API_KEY: str = ""
    DEFAULT_LLM_MODEL: str = "gpt-4o-mini"
    # Embedded model gateway (loopback-only, agent-only). Serves the builtin
    # models below; deployed inside the same container (see start.sh).
    GATEWAY_URL: str = "http://127.0.0.1:8081/v1"
    GATEWAY_SHARED_SECRET: str = ""
    LLM_TIMEOUT_SECONDS: int = 600
    MAX_AGENT_STEPS: int = 80
    MAX_CONTEXT_TOKENS: int = 160_000
    COMPACT_AT_RATIO: float = 0.75

    # ---- sandbox ---------------------------------------------------------
    SANDBOX_BACKEND: Literal["docker", "local", "auto", "superserve", "github"] = "auto"
    SANDBOX_IMAGE: str = "rawal-ai-sandbox:latest"
    SANDBOX_FALLBACK_IMAGE: str = "python:3.12-slim"
    SANDBOX_CPUS: float = 1.0
    SANDBOX_MEMORY_MB: int = 2048
    SANDBOX_IDLE_TIMEOUT_S: int = 1800
    SANDBOX_NETWORK: str = "bridge"
    SANDBOX_COMMAND_TIMEOUT_S: int = 300
    # Superserve cloud sandboxes (https://api.superserve.ai). Key can also
    # live in the DB-backed sandbox setting (Settings → Sandbox).
    SUPERSERVE_API_KEY: str = ""
    SUPERSERVE_API_URL: str = "https://api.superserve.ai"
    SUPERSERVE_TEMPLATE: str = "superserve/base"
    SUPERSERVE_POOL_SIZE: int = 5
    # Optional remote Chromium endpoint (Browserless, Browserbase, or a private
    # browser service). When set, Render never launches a local browser.
    BROWSER_CDP_URL: str = ""
    BROWSER_MAX_SESSIONS: int = 1
    BROWSER_IDLE_TIMEOUT_S: int = 900

    # ---- integrations ----------------------------------------------------
    GITHUB_TOKEN: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""
    VERCEL_TOKEN: str = ""
    RENDER_TOKEN: str = ""
    HF_TOKEN: str = ""
    SEARCH_PROVIDER: Literal["duckduckgo", "tavily", "brave"] = "duckduckgo"
    TAVILY_API_KEY: str = ""
    BRAVE_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_USER_IDS: str = ""

    # ---- email (transcript sharing) --------------------------------------
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins(self) -> list[str]:
        if self.CORS_ORIGINS in ("*", ""):
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite+aiosqlite:///{Path(self.DATA_DIR) / 'bhati.db'}"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.AUTH_PASSWORD)

    def ensure_dirs(self) -> None:
        Path(self.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.WORKSPACE_ROOT).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
