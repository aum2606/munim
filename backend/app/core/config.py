from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", Path(__file__).resolve().parents[3] / ".env"), extra="ignore"
    )
    app_env: Literal["dev", "test", "prod"] = "dev"
    secret_key: SecretStr = Field(default=SecretStr(""), min_length=32)
    database_url: str = "postgresql+asyncpg://munim:munim@localhost:57432/munim"
    redis_url: str = "redis://localhost:56379/0"
    cors_origins: str = "http://localhost:5173"
    widget_script_url: str = "http://localhost:5174/widget.js"
    public_api_url: str = "http://localhost:18000"
    widget_session_hours: int = Field(default=24, ge=1, le=168)
    widget_rate_per_minute: int = Field(default=60, ge=1)
    widget_stream_seconds: int = Field(default=60, ge=1, le=300)
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=7, ge=1)
    llm_provider: Literal["fake", "openai_compatible"] = "fake"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model_router: str = ""
    llm_model_reasoning: str = ""
    llm_model_cheap: str = ""
    llm_timeout_s: int = Field(default=30, ge=1)
    embedding_provider: str = "fake"
    embedding_model: str = ""
    embedding_dim: int = Field(default=1024, ge=1)
    reranker_enabled: bool = False
    storage_dir: str = "uploads"
    demo_seed_password: SecretStr = SecretStr("")
    credentials_encryption_key: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_api_version: str = ""
    whatsapp_max_media_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    whatsapp_timeout_s: int = Field(default=20, ge=1, le=120)
    whatsapp_max_attempts: int = Field(default=6, ge=1, le=20)
    debounce_seconds: float = Field(default=2.5, ge=0)
    router_confidence_threshold: float = Field(default=0.6, ge=0, le=1)
