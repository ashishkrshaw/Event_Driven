"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "event-notification-service"
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_queue_name: str = "events:queue"
    redis_dlq_name: str = "events:dlq"

    # Worker
    max_retries: int = 3
    retry_delay_seconds: int = 1

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Email (SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""

    # Email Rate Limiting
    daily_email_limit: int = 20  # max emails per day
    alert_email: str = ""  # email to notify when limit is reached


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

