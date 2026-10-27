from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / "config" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCINTEL_", env_file=ENV_FILE, extra="ignore")

    database_url: str = "postgresql+asyncpg://docintel:docintel@localhost:5433/docintel"
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = PROJECT_ROOT / "storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    parser_backend: Literal["docling", "unstructured"] = "docling"
    unstructured_strategy: str = "auto"
    llm_model: str
    classifier_model: str
    llm_output_mode: Literal["tool", "prompted"] = "prompted"
    nvidia_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_fallbacks: list[str] = Field(default_factory=list)
    llm_concurrency: int = 4
    min_classification_confidence: float = 0.7
    job_max_attempts: int = 8
    job_visibility_seconds: int = 600
    outbox_max_attempts: int = 5
    poll_seconds: float = 0.5
    embedded_worker: bool = True
    otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"
