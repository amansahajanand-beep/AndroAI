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
    # Extra browser origins allowed to make cookie-authenticated requests (comma separated).
    allowed_origins: str = ""
    # Session cookies. `Secure` defaults to on in production; SameSite=Lax + Origin checks stop CSRF.
    cookie_secure: bool | None = None
    cookie_domain: str | None = None

    # Required infrastructure
    database_url: PostgresDsn
    redis_url: RedisDsn

    # Auth (JWT) - issuance is implemented by a later module
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = Field(default=30, gt=0)
    refresh_ttl_days: int = Field(default=30, gt=0)
    email_token_ttl_hours: int = Field(default=24, gt=0)
    reset_token_ttl_minutes: int = Field(default=30, gt=0)
    # Fernet key (urlsafe base64, 32 bytes) for encrypting stored secrets. Required in production.
    secrets_encryption_key: str | None = None

    # Email
    email_backend: Literal["console", "smtp"] = "console"
    email_from: str = "AndroAI <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None

    # Rate limiting (requests per window, per client IP / per account)
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = Field(default=10, gt=0)
    rate_limit_login_per_account_per_minute: int = Field(default=5, gt=0)
    # Trust X-Forwarded-For only when running behind our own reverse proxy (Nginx).
    trust_proxy_headers: bool = False

    # Uploads
    upload_max_bytes: int = Field(default=200 * 1024 * 1024, gt=0)
    upload_max_uncompressed_bytes: int = Field(default=1024 * 1024 * 1024, gt=0)
    upload_max_files: int = Field(default=20000, gt=0)
    editor_max_file_bytes: int = Field(default=2 * 1024 * 1024, gt=0)

    # Scheduler
    max_active_jobs_per_user: int = Field(default=2, gt=0)  # starting + running
    max_pending_jobs_per_user: int = Field(default=10, gt=0)  # queued + blocked + active
    max_queue_depth: int = Field(default=500, gt=0)  # global backpressure
    job_lease_seconds: int = Field(default=120, gt=0)
    worker_heartbeat_timeout_seconds: int = Field(default=90, gt=0)
    retry_backoff_seconds: int = Field(default=30, ge=0)
    max_log_bytes_per_job: int = Field(default=5 * 1024 * 1024, gt=0)
    artifact_max_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    notify_orchestration: bool = False  # send build/test results to the orchestration Celery queue

    # Registration policy
    allow_registration: bool = True
    require_email_verification: bool = False  # set true in production once SMTP is configured

    # AI providers - optional until the AI modules need them
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None

    # Object storage (S3-compatible) - optional until the storage module lands
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str | None = None
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./.data/storage"  # dev only; never used when storage_backend=s3
    signed_url_ttl_seconds: int = Field(default=300, gt=0, le=3600)

    # Workers
    worker_concurrency: int = Field(default=2, gt=0)

    @model_validator(mode="after")
    def _reject_placeholders_in_production(self) -> "Settings":
        if self.environment == "production":
            secret = self.jwt_secret.lower()
            if any(m in secret for m in _PLACEHOLDER_MARKERS):
                raise ValueError("JWT_SECRET must not be a placeholder in production")
            if not self.secrets_encryption_key:
                raise ValueError("SECRETS_ENCRYPTION_KEY is required in production")
            if self.storage_backend != "s3":
                raise ValueError("STORAGE_BACKEND must be 's3' in production")
            if not (self.s3_bucket and self.s3_access_key_id and self.s3_secret_access_key):
                raise ValueError("S3_BUCKET / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY are required in production")
        return self

    @property
    def cookies_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.environment == "production"

    @property
    def trusted_origins(self) -> set[str]:
        extra = {o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()}
        return {self.app_url.rstrip("/"), *extra}

    @property
    def sqlalchemy_url(self) -> str:
        """Force the psycopg (v3) driver regardless of the scheme given."""
        url = str(self.database_url)
        return url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
