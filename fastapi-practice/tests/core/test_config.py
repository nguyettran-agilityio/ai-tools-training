"""Tests for app.core.config.Settings / get_settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_settings_load_with_defaults(monkeypatch):
    """With only the required field set, every other field falls back to its default."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_name == "Library Management System"
    assert settings.env == "dev"
    assert settings.debug is False
    assert settings.database_url == "sqlite:///./library.db"
    assert settings.jwt_secret_key == "test-secret-key-with-at-least-32-characters"
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 60
    assert settings.borrow_limit == 5
    assert settings.loan_duration_days == 14
    assert settings.late_return_ban_days == 7
    assert settings.cors_origins == ["*"]

    get_settings.cache_clear()


def test_env_var_override(monkeypatch):
    """Environment variables override the declared defaults."""
    monkeypatch.setenv("JWT_SECRET_KEY", "override-secret-key-with-at-least-32-chars")
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("BORROW_LIMIT", "10")
    monkeypatch.setenv("LOAN_DURATION_DAYS", "30")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120")
    # env=prod rejects the wildcard CORS default, so override it here too.
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.jwt_secret_key == "override-secret-key-with-at-least-32-chars"
    assert settings.env == "prod"
    assert settings.debug is True
    assert settings.borrow_limit == 10
    assert settings.loan_duration_days == 30
    assert settings.access_token_expire_minutes == 120
    assert settings.cors_origins == ["https://app.example.com"]

    get_settings.cache_clear()


def test_missing_jwt_secret_key_raises(monkeypatch):
    """jwt_secret_key has no default — omitting it (and any .env file) must fail to build."""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_wildcard_cors_in_prod_raises():
    """ "*" would let any origin call the API from a browser — refuse it in prod."""
    with pytest.raises(ValidationError, match="cors_origins"):
        Settings(
            _env_file=None,
            jwt_secret_key="test-secret-key-with-at-least-32-characters",
            env="prod",
            cors_origins=["*"],
        )


def test_explicit_origins_in_prod_are_accepted():
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-secret-key-with-at-least-32-characters",
        env="prod",
        cors_origins=["https://app.example.com"],
    )

    assert settings.cors_origins == ["https://app.example.com"]


def test_wildcard_cors_outside_prod_is_still_allowed():
    """ "*" stays the convenient default for dev/test envs."""
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-secret-key-with-at-least-32-characters",
        env="dev",
        cors_origins=["*"],
    )

    assert settings.cors_origins == ["*"]


def test_negative_late_return_ban_days_is_rejected(monkeypatch):
    """`late_return_ban_days` must be >= 0; `-1` fails at load time."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters")
    monkeypatch.setenv("LATE_RETURN_BAN_DAYS", "-1")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()
