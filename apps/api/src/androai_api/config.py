"""Application configuration. Loaded and validated once at startup.

Missing or invalid required settings raise a pydantic ValidationError, which
aborts startup (see main.lifespan). Never put real credentials in code.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MARKERS = ("change-me", "changeme", "replace-me")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"), extra="ignore", case_sensitive=False
    )

    # General
    app_name: str = "androai-api"
    environment: Literal["development", "test", "production"] = "development"
    app_url: str = "http://localhost:3000"

    # Required infrastructure
    database_url: PostgresDsn
    redis_url: RedisDsn

    # Auth (JWT) - issuance is implemented by a later module
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = Field(default=30, gt=0)

    # AI providers - optional until the AI modules need them
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None

    # Object storage (S3-compatible) - optional until the storage module lands
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    # Workers
    worker_concurrency: int = Field(default=2, gt=0)

    @model_validator(mode="after")
    def _reject_placeholders_in_production(self) -> "Settings":
        if self.environment == "production":
            secret = self.jwt_secret.lower()
            if any(m in secret for m in _PLACEHOLDER_MARKERS):
                raise ValueError("JWT_SECRET must not be a placeholder in production")
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """Force the psycopg (v3) driver regardless of the scheme given."""
        url = str(self.database_url)
        return url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
