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

    # 内部站点：默认关闭公开注册，账号一律由管理员创建。
    # 仅在本地跑测试或临时需要自助注册时才置为 true。
    allow_public_registration: bool = False

    # 初始化管理员账号，由 `python -m app.seed` 写入。
    # seed 按邮箱判断是否已存在，已存在就跳过，所以这里的密码只在全新
    # 部署（库还是空的）时才生效；站内已改用真实密码，不在此处明文存储。
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
    ai_small_model: str = "deepseek-chat"
    # 环境变量兜底 provider 的接入格式，见 app.ai.provider.API_FORMATS
    ai_api_format: str = "openai"
    # 兼容旧配置：模型通道转写使用用户当前模型名，不再另挑 ASR 模型。
    ai_stt_model: str = ""
    # 本地语音识别（不需要 Key、不花钱）：装了 faster-whisper 即可用，
    # 用户没接模型 API 或那把 Key 无效时顶上。置 false 可关掉。
    # 模型名见 app/services/local_asr.py 里的取舍表：small.en 更准（默认），
    # base.en 更快但会听错常见词。
    local_asr: bool = True
    local_asr_model: str = "small.en"
    # 启动时把场景开场白等固定台词的朗读音频先合成好。测试里关掉，免得每次
    # 建 app 都去连一次语音服务。
    speech_prewarm: bool = True
    ai_timeout_seconds: int = 60
    # 单次模型调用的输出上限：结构化回复正常几百 token，封顶后跑题的模型
    # 不会把一整轮对话拖到超时。
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
