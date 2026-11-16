from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
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
    # One key per provider; the name in a chain entry picks the key (groq -> GROQ_API_KEY).
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = Field(
        default="", validation_alias=AliasChoices("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY")
    )
    llm_api_keys: str = ""  # older "name=key,name2=key2" form, for providers not listed above
    llm_timeout_s: float = 30.0

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_cache_dir: str = ""
    storage_dir: str = "./uploads"
    max_upload_mb: int = 10

    search_max_distance: float = 0.65
    debounce_seconds: float = 2.5
    router_confidence_threshold: float = 0.6

    job_poll_seconds: float = 1.0
    job_lease_seconds: int = 120

    # Channel credentials are encrypted at rest with this Fernet key. Outside prod an empty value
    # derives a key from SECRET_KEY so local setups work without extra steps.
    credentials_encryption_key: str = ""
    # One Meta app serves every business: its verify token and app secret live here, while each
    # business stores only its own phone number id and access token (encrypted, in the database).
    # With either empty the WhatsApp webhook refuses everything.
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_api_version: str = "v24.0"

    stt_model: str = "small"  # faster-whisper model name
    stt_device: str = "cpu"
    stt_cache_dir: str = ""
    # Below this the bot asks the customer to confirm what it heard instead of acting on it.
    stt_confidence_threshold: float = 0.6
    max_voice_note_mb: int = 16

    # A sent quote with no customer reply for this long gets a follow-up draft for the owner.
    followup_after_days: int = 2

    @model_validator(mode="after")
    def _reject_weak_secret_in_prod(self) -> "Settings":
        if self.app_env == "prod" and (
            len(self.secret_key) < 32 or _PLACEHOLDER in self.secret_key.lower()
        ):
            raise ValueError("SECRET_KEY must be a random value of at least 32 characters in prod")
        if self.app_env == "prod" and not self.credentials_encryption_key:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY is required in prod")
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
