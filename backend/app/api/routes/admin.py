"""管理员账号管理：内部站点不开放注册，账号统一由这里创建与分发。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.database import get_db
from app.core.security import apply_password
from app.models.user import User
from app.schemas.admin import (
    AdminUserOut,
    CreatedCredentials,
    CreateUserRequest,
    ResetPasswordRequest,
    UpdateUserRequest,
    UpdateUserRoleRequest,
)
from app.services import levels
from app.services.user_service import ensure_identifiers_available

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _serialize(user: User) -> dict:
    level, level_name = levels.level_for_xp(user.xp)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "cefr_level": user.cefr_level,
        "level": level,
        "level_name": level_name,
        "xp": user.xp,
        "streak": user.streak,
        "created_at": user.created_at,
        "last_active_date": user.last_active_date,
        "avatar": user.avatar,
        "password_updated_at": user.password_updated_at,
    }


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> list[AdminUserOut]:
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return [AdminUserOut.model_validate(_serialize(u)) for u in rows]


@router.post(
    "/users", response_model=CreatedCredentials, status_code=status.HTTP_201_CREATED
)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> CreatedCredentials:
    ensure_identifiers_available(db, username=payload.username, email=payload.email)

    user = User(
        username=payload.username,
        email=payload.email,
        role=payload.role,
        cefr_level=payload.cefr_level,
    )
    try:
        apply_password(user, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(user)
    db.commit()
    db.refresh(user)

    # 同时回传明文，省得管理员再去列表里找一次
    return CreatedCredentials(
        id=user.id,
        username=user.username,
        email=user.email,
        password=payload.password,
    )


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> dict:
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        apply_password(user, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "success": True,
        "user_id": user.id,
        "by": admin.username,
        "password": payload.password,
    }


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> AdminUserOut:
    """管理员编辑账号：改用户名/邮箱、密码、等级或角色。"""
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不能把最后一个管理员降级，避免把自己锁在门外
    if user.id == admin.id and payload.role is not None and payload.role != "ADMIN":
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")

    username = payload.username.strip() if payload.username else None
    email = str(payload.email).strip() if payload.email else None
    if (username and username != user.username) or (email and email != user.email):
        ensure_identifiers_available(
            db,
            username=username if username != user.username else None,
            email=email if email != user.email else None,
            exclude_user_id=user.id,
        )
        if username:
            user.username = username
        if email:
            user.email = email

    if payload.password:
        try:
            apply_password(user, payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.cefr_level:
        user.cefr_level = payload.cefr_level
    if payload.role:
        user.role = payload.role

    db.commit()
    db.refresh(user)
    return AdminUserOut.model_validate(_serialize(user))


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
def update_role(
    user_id: int,
    payload: UpdateUserRoleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> AdminUserOut:
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不允许把自己降级，避免把最后一个管理员锁在门外
    if user.id == admin.id and payload.role != "ADMIN":
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")

    user.role = payload.role
    db.commit()
    db.refresh(user)
    return AdminUserOut.model_validate(_serialize(user))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> None:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 会话、词库、成就、XP 记录等均带 ON DELETE CASCADE，会随之清理
    db.delete(user)
    db.commit()
