from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    cefr_level: str
    level: int
    level_name: str
    xp: int
    streak: int
    created_at: datetime
    last_active_date: str | None = None
    password_updated_at: datetime | None = None
    avatar: str | None = None


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    cefr_level: str = Field(default="B1", pattern="^(A1|A2|B1|B2|C1)$")
    role: str = Field(default="USER", pattern="^(USER|ADMIN)$")


class CreatedCredentials(BaseModel):

    id: int
    username: str
    email: str
    password: str


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=72)


class UpdateUserRequest(BaseModel):

    username: str | None = Field(default=None, min_length=2, max_length=32)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    cefr_level: str | None = Field(default=None, pattern="^(A1|A2|B1|B2|C1)$")
    role: str | None = Field(default=None, pattern="^(USER|ADMIN)$")


class UpdateUserRoleRequest(BaseModel):
    role: str = Field(pattern="^(USER|ADMIN)$")
