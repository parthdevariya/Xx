from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    environment: str = Field("development", alias="X_ENV")  # development | test | production
    database_url: str = Field("sqlite:///./x_dev.db", alias="DATABASE_URL")
    redis_url: str = Field("", alias="REDIS_URL")
    secret_key: str = Field("dev-insecure-secret-change-me", alias="X_SECRET_KEY")
    encryption_key: str = Field("", alias="X_ENCRYPTION_KEY")  # Fernet key; required in production
    frontend_origin: str = Field("http://localhost:3000", alias="X_FRONTEND_ORIGIN")
    session_hours: int = Field(12, alias="X_SESSION_HOURS")
    cookie_secure: bool = Field(False, alias="X_COOKIE_SECURE")
    embedded_worker: bool = Field(True, alias="X_EMBEDDED_WORKER")
    bootstrap_admin_email: str = Field("", alias="X_BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_password: str = Field("", alias="X_BOOTSTRAP_ADMIN_PASSWORD")
    allow_registration: bool = Field(False, alias="X_ALLOW_REGISTRATION")
    upload_max_bytes: int = Field(10 * 1024 * 1024, alias="X_UPLOAD_MAX_BYTES")
    upload_dir: str = Field("./uploads", alias="X_UPLOAD_DIR")
    default_max_cost_usd: float = Field(0.0, alias="X_DEFAULT_MAX_COST_USD")
    execution_timeout_s: int = Field(900, alias="X_EXECUTION_TIMEOUT_S")
    rate_limit_per_min: int = Field(120, alias="X_RATE_LIMIT_PER_MIN")
    login_rate_limit_per_min: int = Field(10, alias="X_LOGIN_RATE_LIMIT_PER_MIN")
    # Optional bootstrap of an AI provider from env on first start (stored encrypted in the DB).
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def validate_for_production(self) -> list[str]:
        problems = []
        if self.is_production:
            if self.secret_key.startswith("dev-") or len(self.secret_key) < 32:
                problems.append("X_SECRET_KEY must be set to a random value of at least 32 characters")
            if not self.encryption_key:
                problems.append("X_ENCRYPTION_KEY must be set (Fernet key)")
            if self.is_sqlite:
                import os
                raw = os.environ.get("DATABASE_URL")
                similar = sorted(k for k in os.environ if "DATABASE" in k.upper() or "POSTGRES" in k.upper()
                                 or k.upper().startswith("DB"))
                if raw is None:
                    detail = "DATABASE_URL is not set on this service"
                elif not raw.strip():
                    detail = "DATABASE_URL is set but empty"
                else:
                    detail = f"DATABASE_URL is set but uses scheme '{raw.split(':', 1)[0][:20]}'"
                problems.append("DATABASE_URL must point to PostgreSQL in production (" + detail
                                + (f"; similarly named variables present: {similar}" if similar else "") + ")")
            if not self.cookie_secure:
                problems.append("X_COOKIE_SECURE must be true in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
