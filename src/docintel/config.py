"""Application settings, read from environment and config/.env.

This module defines the Settings class using pydantic-settings for type-safe
configuration management. All settings are prefixed with DOCINTEL_ and can be
set via environment variables or the config/.env file (anchored to the project
root).

The settings are cached via @lru_cache on get_settings() to ensure a single
Settings instance is used throughout the application lifecycle.

Configuration categories:
- Database: PostgreSQL async connection URL
- Storage: Local filesystem or S3-compatible backend
- LLM: Model specifications, fallbacks, output mode, API keys
- Tracing: Optional Logfire token for observability
- Processing: Retry attempts, confidence thresholds, upload limits
- Logging: Log level
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root directory (two levels up from this file: src/docintel/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Environment file location
ENV_FILE = PROJECT_ROOT / "config" / ".env"
# Application version
VERSION = "0.1.0"
# API URL prefix for versioning
BASE_URL_PREFIX = "/v1alpha1"


class Settings(BaseSettings):
    """Application configuration settings.

    All fields can be overridden via environment variables with the DOCINTEL_
    prefix (e.g., DOCINTEL_DATABASE_URL). Values in config/.env take precedence
    over defaults but are overridden by actual environment variables.

    Attributes:
        database_url: PostgreSQL async connection string (asyncpg driver).
        storage_backend: "local" for filesystem, "s3" for S3-compatible.
        local_storage_path: Root directory for local file storage.
        s3_endpoint: S3-compatible endpoint URL (e.g., MinIO, AWS).
        s3_bucket: S3 bucket name for document storage.
        llm_model: Primary LLM model specification (e.g., "nim:model-id").
        classifier_model: LLM model for document classification.
        llm_fallbacks: Comma-separated fallback model specs for resilience.
        llm_output_mode: "tool" for function calling, "prompted" for JSON in prompt.
        nvidia_api_key: API key for NVIDIA NIM models.
        llm_base_url: Base URL for openai-compatible endpoints.
        llm_api_key: API key for openai-compatible endpoints.
        logfire_token: Logfire token for tracing (empty = disabled).
        llm_max_attempts: Maximum retry attempts for LLM calls.
        min_classification_confidence: Minimum confidence to accept classification.
        max_upload_bytes: Maximum upload size in bytes (default 20MB).
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
    """

    model_config = SettingsConfigDict(env_prefix="DOCINTEL_", env_file=ENV_FILE, extra="ignore")

    database_url: str = "postgresql+asyncpg://docintel:docintel@localhost:5433/docintel"
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = PROJECT_ROOT / "storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    llm_model: str = "nim:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    classifier_model: str = "nim:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    # Tried in order when the main model fails (comma-separated model specs, empty = none)
    llm_fallbacks: str = "nim:meta/llama-3.2-11b-vision-instruct"
    llm_output_mode: Literal["tool", "prompted"] = "prompted"
    nvidia_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    logfire_token: SecretStr = SecretStr("")  # empty = tracing off
    llm_max_attempts: int = Field(default=8, ge=1)
    min_classification_confidence: float = 0.7
    max_upload_bytes: int = 20 * 1024 * 1024
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Get the cached settings instance.

    Uses lru_cache to ensure a single Settings instance is created and reused
    throughout the application. The cache is keyed on no arguments, so all
    calls return the same instance.

    Returns:
        Settings: The application settings instance.
    """
    return Settings()
