from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, serialize_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    apply_password,
    create_access_token,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    OnboardingRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserPublic

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    """让登录页知道是否需要展示注册入口。"""
    return {"allow_public_registration": settings.allow_public_registration}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if not settings.allow_public_registration:
        raise HTTPException(status_code=403, detail="本站不开放注册，请联系管理员开通账号")

    exists = db.execute(
        select(User).where(
            (User.email == payload.email) | (User.username == payload.username)
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="邮箱或用户名已被注册")

    user = User(
        username=payload.username,
        email=payload.email,
        role="USER",
    )
    try:
        apply_password(user, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=create_access_token(user.id, token_version=user.token_version)
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    return TokenResponse(
        access_token=create_access_token(user.id, token_version=user.token_version)
    )


@router.post("/onboarding", response_model=UserPublic)
def onboarding(
    payload: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPublic:
    user.cefr_level = payload.cefr_level
    user.interests = ",".join(payload.interests)
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(serialize_user(user))
