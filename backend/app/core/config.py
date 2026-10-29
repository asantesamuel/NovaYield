"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Settings for the API process, loaded from the backend .env file or environment."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIRECTORY / ".env",
        env_file_encoding="utf-8",
        env_prefix="NOVAYIELD_",
        extra="ignore",
    )

    app_name: str = "Nova Yield API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    mongodb_uri: SecretStr = SecretStr("mongodb://localhost:27017")
    mongodb_database_name: str = "nova_yield"
    mongodb_server_selection_timeout_ms: int = Field(default=2_000, gt=0)
    auth_session_lifetime_seconds: int = Field(default=3_600, gt=0)
    auth_cookie_secure: bool = True
    csrf_secret: SecretStr
    csrf_cookie_domain: str | None = None

    @model_validator(mode="after")
    def validate_csrf_secret(self) -> "Settings":
        secret = self.csrf_secret.get_secret_value()
        if not secret.strip():
            raise ValueError("CSRF signing secret cannot be empty")
        if len(secret) < 32:
            raise ValueError("CSRF signing secret must contain at least 32 characters")
        return self

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_v1_prefix(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("/"):
            raise ValueError("API prefix must start with a slash")
        return normalized

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("At least one explicit CORS origin must be configured")
        if "*" in origins:
            raise ValueError("Wildcard CORS origins are not allowed")
        return ",".join(origins)

    @field_validator("mongodb_database_name")
    @classmethod
    def validate_mongodb_database_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MongoDB database name cannot be empty")
        if any(character in normalized for character in '/\\ ."$*<>:|?'):
            raise ValueError("MongoDB database name contains an unsupported character")
        return normalized

    @field_validator("csrf_cookie_domain", mode="before")
    @classmethod
    def normalize_csrf_cookie_domain(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            if "/" in normalized or ":" in normalized:
                raise ValueError("CSRF cookie domain must be a hostname only")
            return normalized
        return value

    @property
    def cors_origins(self) -> list[str]:
        """Return the explicit origins in the comma-separated environment setting."""

        return [origin.strip() for origin in self.cors_allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Return process settings, cached so all modules use one configuration instance."""

    return Settings()
