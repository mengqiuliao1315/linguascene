from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LinguaScene"
    env: str = "development"
    secret_key: str = "dev-secret-key-change-me"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"

    database_url: str = "sqlite:///./linguascene.db"
    auto_create_tables: bool = True

    allow_public_registration: bool = False

    admin_username: str = "admin"
    admin_email: str = "3099684152@qq.com"
    admin_password: str = "change-me-on-first-deploy"

    cache_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "local"
    local_storage_dir: str = "./storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    ai_provider: str = "mock"
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_api_key: str = ""
    ai_model: str = "deepseek-chat"
    ai_api_format: str = "openai"
    local_asr: bool = True
    local_asr_model: str = "small.en"
    speech_prewarm: bool = True
    ai_timeout_seconds: int = 60
    ai_max_tokens: int = 1500

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.local_storage_dir)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
