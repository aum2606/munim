from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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

    eval_use_real_llm: bool = False
    eval_database_url: str = ""
    eval_report_path: str = str(Path(__file__).resolve().parents[3] / ".cache/evals/report.json")

    max_request_bytes: int = Field(default=6 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    max_json_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)
    request_body_timeout_s: int = Field(default=15, ge=1, le=120)
    rate_limits_enabled: bool = True
    auth_rate_per_minute: int = Field(default=30, ge=1)
    tenant_rate_per_minute: int = Field(default=3000, ge=1)
    user_rate_per_minute: int = Field(default=600, ge=1)

    privacy_hash_key: SecretStr = SecretStr("")

    allow_fake_models_in_prod: bool = False

    @model_validator(mode="after")
    def production_guards(self) -> "Settings":
        if self.app_env != "prod":
            return self
        from urllib.parse import urlparse

        from cryptography.fernet import Fernet

        if (
            len(self.secret_key.get_secret_value()) < 48
            or len(self.privacy_hash_key.get_secret_value()) < 32
        ):
            raise ValueError("Production needs strong signing and stable privacy keys")
        if not self.rate_limits_enabled:
            raise ValueError("Production request limits must remain enabled")
        try:
            Fernet(self.credentials_encryption_key.get_secret_value().encode())
        except (ValueError, TypeError) as error:
            raise ValueError("Configure a valid production credential encryption key") from error
        urls = [self.public_api_url, self.widget_script_url, *self.cors_origins.split(",")]
        if any(
            urlparse(url).scheme != "https"
            or not urlparse(url).hostname
            or urlparse(url).username
            or urlparse(url).password
            or "*" in url
            for url in urls
        ):
            raise ValueError("Production public URLs and origins require HTTPS hosts")
        if not self.allow_fake_models_in_prod:
            if self.llm_provider == "fake" or self.embedding_provider == "fake":
                raise ValueError("Configure live providers before pilot launch")
            if not self.llm_api_key.get_secret_value() or not all(
                (
                    self.llm_model_router,
                    self.llm_model_cheap,
                    self.llm_model_reasoning,
                    self.embedding_model,
                )
            ):
                raise ValueError("Configure provider models and credentials before pilot launch")
        return self
