"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    @property
    def cors_origins(self) -> list[str]:
        """Return the explicit origins in the comma-separated environment setting."""

        return [origin.strip() for origin in self.cors_allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Return process settings, cached so all modules use one configuration instance."""

    return Settings()
