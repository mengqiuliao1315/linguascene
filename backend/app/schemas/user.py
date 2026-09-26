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

    username: str | None = Field(default=None, min_length=2, max_length=32)
    email: EmailStr | None = None
    current_password: str | None = Field(default=None, max_length=72)

    cefr_level: str | None = None
    interests: list[str] | None = None
    theme: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)
