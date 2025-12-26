"""
Configuration module for Whop embedded app.

Centralized configuration management using Pydantic Settings.
All environment variables are validated and typed here.

Usage:
    from core.config import settings
    api_key = settings.WHOP_API_KEY
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Required variables:
        - WHOP_API_KEY: API key for Whop API requests (App or Company API key)
        - WEBHOOK_SECRET: Secret for validating webhook signatures

    Optional variables:
        - DATABASE_URL: Connection string for database (if using persistence)
        - DEV_MODE: Enable development mode (relaxed auth, debug logging)
        - WHOP_API_BASE_URL: Base URL for Whop API (default: https://api.whop.com/api/v5)
    """

    # Required Whop credentials
    WHOP_API_KEY: str
    WEBHOOK_SECRET: str

    # Optional database configuration
    DATABASE_URL: Optional[str] = None

    # Development mode flag
    # When True:
    #   - Accepts token from query params for testing
    #   - Enables detailed error responses
    #   - Relaxes some security checks
    DEV_MODE: bool = False

    # Whop API configuration
    # v5 is the latest stable API version as of documentation
    WHOP_API_BASE_URL: str = "https://api.whop.com/api/v5"

    # Application settings
    APP_NAME: str = "Whop Embedded App"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Security settings
    # Maximum time in seconds to process webhook (Whop requires < 3s response)
    WEBHOOK_TIMEOUT_SECONDS: int = 3

    model_config = SettingsConfigDict(
        # Load from .env file in project root
        env_file=".env",
        env_file_encoding="utf-8",
        # Don't fail if .env doesn't exist (use system env vars)
        env_ignore_empty=True,
        # Allow extra fields for forward compatibility
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Using lru_cache ensures settings are only loaded once,
    improving performance and consistency across the application.

    Returns:
        Settings: Validated application settings
    """
    return Settings()


# Convenience export for direct import
settings = get_settings()
