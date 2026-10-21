"""Application settings, loaded from environment variables / `.env` via
pydantic-settings. All settings live here — don't scatter `os.getenv` calls
across modules.
"""

# Standard library
from functools import lru_cache
from typing import Literal

# Third-party
from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Library Management System"
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./library.db"

    # Auth (PyJWT / bcrypt)
    # HS256 needs a key of at least 32 bytes; generate one with
    # python3 -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Business rules
    borrow_limit: int = 5
    loan_duration_days: int = 14
    renewal_days: int = 14

    # Rate limiting — in-memory, per-process (see app/core/rate_limiter.py).
    # Guards /auth/login and /auth/register against brute-force/spam.
    auth_rate_limit_max_attempts: int = 5
    auth_rate_limit_window_seconds: int = 60

    # Email (SMTP) — used by `EmailNotifier`/`SMTPEmailSender` (see
    # `app/core/notifications.py`). Left unset in dev/test: `main.py`'s
    # lifespan falls back to `InMemoryEmailSender` rather than requiring
    # real SMTP credentials just to boot.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str = "noreply@library.local"
    # False when verifying against a local catcher (Mailpit, MailHog, ...)
    # that doesn't advertise STARTTLS — real providers need this True (the
    # default).
    smtp_use_tls: bool = True

    # CORS — "*" is convenient for local dev but must never reach prod: it lets
    # any origin call the API from a browser. Set explicit origins via the
    # CORS_ORIGINS env var (JSON array, e.g. '["https://app.example.com"]').
    cors_origins: list[str] = ["*"]

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors_in_prod(cls, value: list[str], info: ValidationInfo) -> list[str]:
        if info.data.get("env") == "prod" and "*" in value:
            raise ValueError(
                "cors_origins must not contain '*' when env=prod — "
                "set CORS_ORIGINS to an explicit list of allowed origins"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — depend on this, not `Settings()` directly, so
    FastAPI's dependency-override mechanism can swap in test settings later."""
    return Settings()
