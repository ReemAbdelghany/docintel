from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCINTEL_", env_file="config/.env")

    database_url: str = "postgresql+asyncpg://docintel:docintel@localhost:5432/docintel"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    llm_model: str
    classifier_model: str
    llm_fallbacks: list[str] = Field(default_factory=list)
    llm_concurrency: int = 4
    min_classification_confidence: float = 0.7
    job_max_attempts: int = 5
    otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"
