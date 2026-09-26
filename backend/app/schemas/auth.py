from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OnboardingRequest(BaseModel):
    cefr_level: str = Field(pattern="^(A1|A2|B1|B2|C1)$")
    interests: list[str] = Field(default_factory=list)
