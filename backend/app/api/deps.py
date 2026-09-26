from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.services import ai_config_service, levels

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    decoded = decode_access_token(credentials.credentials)
    if not decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期"
        )
    subject, token_version = decoded

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期"
        ) from None

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if int(getattr(user, "token_version", 0) or 0) != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期"
        )
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def get_user_provider(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ai_config_service.get_provider_for(db, user)


def serialize_user(user: User) -> dict:
    level, level_name = levels.level_for_xp(user.xp)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "avatar": user.avatar,
        "role": user.role,
        "cefr_level": user.cefr_level,
        "interests": user.interest_list,
        "level": level,
        "level_name": level_name,
        "xp": user.xp,
        "xp_to_next": levels.xp_to_next(user.xp),
        "streak": user.streak,
        "longest_streak": user.longest_streak,
        "theme": user.theme,
        "created_at": user.created_at,
    }
