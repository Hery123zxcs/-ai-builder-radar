"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


class Settings(BaseModel):
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str | None = None
    github_token: SecretStr | None = None
    github_api_base_url: str = "https://api.github.com"
    request_timeout_seconds: float = Field(default=30, gt=0, le=120)
    github_max_retries: int = Field(default=2, ge=0, le=5)
    github_cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    database_path: str = "ai_builder_radar.db"

    @field_validator("deepseek_api_key", "github_token", mode="before")
    @classmethod
    def empty_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("deepseek_model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return None
        return value

    @field_validator("github_api_base_url")
    @classmethod
    def validate_github_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("https://", "http://")):
            raise ValueError("GITHUB_API_BASE_URL must be an HTTP(S) URL")
        return value

    @property
    def deepseek_configured(self) -> bool:
        return self.deepseek_api_key is not None

    @property
    def github_authenticated(self) -> bool:
        return self.github_token is not None

    @property
    def deepseek_model_configured(self) -> bool:
        return self.deepseek_model is not None

    def require_deepseek_key(self) -> str:
        if self.deepseek_api_key is None:
            raise ConfigurationError(
                "DEEPSEEK_API_KEY is missing. Copy .env.example to .env and add your key."
            )
        return self.deepseek_api_key.get_secret_value()

    def require_deepseek_model(self) -> str:
        if self.deepseek_model is None:
            raise ConfigurationError(
                "DEEPSEEK_MODEL is missing. Configure an available tool-calling model in .env."
            )
        return self.deepseek_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load .env once and return validated, secret-safe settings."""
    load_dotenv()
    try:
        return Settings(
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL"),
            github_token=os.getenv("GITHUB_TOKEN"),
            github_api_base_url=_env_or_default(
                "GITHUB_API_BASE_URL", "https://api.github.com"
            ),
            request_timeout_seconds=_env_or_default(
                "REQUEST_TIMEOUT_SECONDS", "30"
            ),
            github_max_retries=_env_or_default("GITHUB_MAX_RETRIES", "2"),
            github_cache_ttl_seconds=_env_or_default(
                "GITHUB_CACHE_TTL_SECONDS", "300"
            ),
            database_path=_env_or_default(
                "DATABASE_PATH", "ai_builder_radar.db"
            ),
        )
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid environment configuration: {exc}") from exc


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default
