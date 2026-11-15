from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER = "change-me"


class Settings(BaseSettings):
    """All configuration comes from env (see .env.example). Nothing else reads os.environ."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    secret_key: str = "dev-only-secret-key-change-me-in-production"  # noqa: S105 (dev default)
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://munim:munim-dev-only@localhost:5432/munim"
    cors_origins: str = ""
    allow_registration: bool = True
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    llm_small_chain: str = ""
    llm_large_chain: str = ""
    llm_api_keys: str = ""
    llm_timeout_s: float = 30.0

    job_poll_seconds: float = 1.0
    job_lease_seconds: int = 120

    @model_validator(mode="after")
    def _reject_weak_secret_in_prod(self) -> "Settings":
        if self.app_env == "prod" and (
            len(self.secret_key) < 32 or _PLACEHOLDER in self.secret_key.lower()
        ):
            raise ValueError("SECRET_KEY must be a random value of at least 32 characters in prod")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
