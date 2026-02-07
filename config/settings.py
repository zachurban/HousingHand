"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """HousingHand application configuration."""

    # Database
    database_url: str = "postgresql://housinghand:password@localhost:5432/housinghand"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_secret_key: str = "change-me-in-production"
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    # HousingMind Ecosystem
    housing_lens_api_url: str = "http://localhost:8001/api/v1"
    housing_lens_api_key: str = ""
    housing_ear_api_url: str = "http://localhost:8002/api/v1"
    housing_ear_api_key: str = ""
    housing_mind_webhook_secret: str = ""

    # ML
    ml_model_path: str = "models/timeline_prediction.joblib"
    ml_model_version: str = "0.1.0"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Paths
    project_root: Path = Path(__file__).parent.parent

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
