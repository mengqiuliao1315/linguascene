from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    avatar: str | None = None
    role: str
    cefr_level: str
    interests: list[str] = []
    level: int
    level_name: str = ""
    xp: int
    xp_to_next: int = 0
    streak: int
    longest_streak: int
    theme: str
    created_at: datetime


class UpdateUserRequest(BaseModel):
    """用户可自行修改的资料。

    账号标识（用户名、邮箱）也在这里：管理员只是最初的创建者，账号分发
    出去之后用户要能自己改。改动标识属于敏感操作，必须同时带上当前密码，
    由接口校验；头像走单独的上传接口。
    """

    username: str | None = Field(default=None, min_length=2, max_length=32)
    email: EmailStr | None = None
    # 仅在改用户名/邮箱时必填，改其他资料不需要
    current_password: str | None = Field(default=None, max_length=72)

    cefr_level: str | None = None
    interests: list[str] | None = None
    theme: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)
