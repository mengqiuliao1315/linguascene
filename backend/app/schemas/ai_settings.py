from datetime import datetime

from pydantic import BaseModel, Field

API_FORMAT_PATTERN = "^(openai|openai_responses|anthropic|gemini)$"


class AiProviderConfigIn(BaseModel):

    name: str = Field(default="", max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)
    api_format: str = Field(default="openai", pattern=API_FORMAT_PATTERN)
    models: list[str] = Field(default_factory=list)
    active_model: str = Field(default="", max_length=128)


class AiActiveIn(BaseModel):

    config_id: int | None = None
    share_id: int | None = None


class AiConnectionResult(BaseModel):

    success: bool
    message: str
    status: str = "ok"
    suggested_models: list[str] = Field(default_factory=list)


class AiModelListIn(BaseModel):

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


class AiShareIn(BaseModel):

    config_id: int
    title: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=200)


class AiShareUpdateIn(BaseModel):

    is_active: bool


class AiShareOut(BaseModel):

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

    available: bool
    share: AiShareOut | None = None
    reason: str = ""


class AiShareListOut(BaseModel):

    mine: list[AiShareOut] = Field(default_factory=list)
    available: list[AiShareOut] = Field(default_factory=list)
    adopted_id: int | None = None


class UserAiStatusOut(BaseModel):
    configs: list[AiProviderConfigOut] = Field(default_factory=list)
    active_source: str
    active_label: str
    active_config_id: int | None = None
    active_share_id: int | None = None
    shares: list[AiShareOut] = Field(default_factory=list)
    adopted_share: AiShareOut | None = None
