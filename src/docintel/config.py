"""Settings, read once from the environment and config/.env (anchored to the project root)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / "config" / ".env"
VERSION = "0.1.0"
BASE_URL_PREFIX = "/v1alpha1"


class Settings(BaseSettings):
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
    return Settings()
