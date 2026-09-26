"""AI 模型设置的请求/响应 schema。凭据只进不出，响应里一律脱敏。"""

from datetime import datetime

from pydantic import BaseModel, Field

# 与 app.ai.provider.API_FORMATS 保持一致。这里写字面量，避免 schema 层反向依赖 provider。
API_FORMAT_PATTERN = "^(openai|openai_responses|anthropic|gemini)$"


class AiProviderConfigIn(BaseModel):
    """新建/编辑一条供应商配置。api_key 留空表示沿用已保存的那把。"""

    name: str = Field(default="", max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)
    api_format: str = Field(default="openai", pattern=API_FORMAT_PATTERN)
    models: list[str] = Field(default_factory=list)
    active_model: str = Field(default="", max_length=128)


class AiActiveIn(BaseModel):
    """切换当前使用的模型：二选一，都不传表示回到自动回落。"""

    config_id: int | None = None
    share_id: int | None = None


class AiConnectionResult(BaseModel):
    """测试连接 / 当前生效的回显。

    status 三档：ok（一次往返走通）、warn（地址与 Key 没问题，只是模型这次太慢）、
    fail（明确失败，message 里是可以照着改的说明）。
    """

    success: bool
    message: str
    status: str = "ok"
    # 失败且像是模型名的问题时，带上该地址下真实存在的模型名，供前端一键挑选
    suggested_models: list[str] = Field(default_factory=list)


class AiModelListIn(BaseModel):
    """测试连接/拉取模型列表。

    api_key 留空时用 config_id 对应配置里已保存的那把；测试连接需要 model。
    """

    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)
    api_format: str = Field(default="openai", pattern=API_FORMAT_PATTERN)
    config_id: int | None = None
    model: str = Field(default="", max_length=128)


class AiModelListOut(BaseModel):
    success: bool
    message: str = ""
    models: list[str] = Field(default_factory=list)


class AiProviderConfigOut(BaseModel):
    id: int
    name: str = ""
    base_url: str = ""
    api_format: str = "openai"
    models: list[str] = Field(default_factory=list)
    active_model: str = ""
    key_hint: str = ""
    is_active: bool = False
    updated_at: datetime | None = None


# ------------------------------------------------------------------ 用户分享

class AiShareIn(BaseModel):
    """把自己的一条供应商配置分享出去。Key 由服务端从该配置取出。"""

    config_id: int
    title: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=200)


class AiShareUpdateIn(BaseModel):
    """分享开关：关掉即不再推送给其他人，记录保留。"""

    is_active: bool


class AiShareOut(BaseModel):
    """一条分享的对外视图。Key 永不回传，只给指纹尾号。"""

    id: int
    owner_id: int
    owner_name: str
    title: str
    base_url: str
    api_format: str
    models: list[str] = Field(default_factory=list)
    active_model: str = ""
    note: str
    is_active: bool
    is_mine: bool
    adoption_count: int = 0
    key_hint: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AiSharePromptOut(BaseModel):
    """登录后的分享弹窗内容。available=False 时不弹。"""

    available: bool
    share: AiShareOut | None = None
    reason: str = ""


class AiShareListOut(BaseModel):
    """分享总览：我分享出去的 + 我可以用别人的 + 我当前采纳的那条。"""

    mine: list[AiShareOut] = Field(default_factory=list)
    available: list[AiShareOut] = Field(default_factory=list)
    adopted_id: int | None = None


class UserAiStatusOut(BaseModel):
    # 我接入的供应商，一人可有多条
    configs: list[AiProviderConfigOut] = Field(default_factory=list)
    active_source: str
    active_label: str
    # 当前生效的自己的供应商 id / 采纳的分享 id，供设置页高亮
    active_config_id: int | None = None
    active_share_id: int | None = None
    # 别人（和自己）分享出来的可用模型
    shares: list[AiShareOut] = Field(default_factory=list)
    # 我当前采纳的那条分享；若已被分享者关掉/删除，这里仍会带出来但 is_active=False
    adopted_share: AiShareOut | None = None
