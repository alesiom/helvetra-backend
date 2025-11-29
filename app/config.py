"""
Application configuration loaded from environment variables.
Centralizes all settings to ensure consistent access across the app.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/helvetra"

    # Cache
    redis_url: str = "redis://localhost:6379"

    # Translation API
    apertus_api_base: str = ""
    apertus_api_key: str = ""
    apertus_model: str = ""

    # App settings
    debug: bool = False
    cors_origins: str = "http://localhost:3000"

    # Rate limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_day: int = 500
    max_text_length: int = 5000

    # Encryption (for PII)
    encryption_key: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
