from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, serialize_user
from app.core.database import get_db
from app.core.security import apply_password, verify_password
from app.core.storage import (
    AVATAR_EXTENSIONS,
    MAX_AVATAR_BYTES,
    avatar_path,
    delete_avatar,
    save_avatar,
)
from app.core.uploads import read_limited
from app.models.user import User
from app.schemas.user import ChangePasswordRequest, UpdateUserRequest, UserPublic
from app.services import levels
from app.services.user_service import ensure_identifiers_available

router = APIRouter(prefix="/api/users", tags=["users"])

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(serialize_user(user))


@router.patch("/me", response_model=UserPublic)
def update_me(
    payload: UpdateUserRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPublic:
    """更新自己的资料，账号标识（用户名/邮箱）也可以改。

    改标识等于换登录凭据，所以要求带上当前密码；只改等级/兴趣/主题
    这类普通资料时不需要。头像走 /me/avatar 上传。
    """
    username = payload.username.strip() if payload.username else None
    email = str(payload.email).strip() if payload.email else None

    wants_username = bool(username) and username != user.username
    wants_email = bool(email) and email != user.email

    if wants_username or wants_email:
        if not payload.current_password:
            raise HTTPException(status_code=400, detail="修改用户名或邮箱需要输入当前密码")
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="当前密码不正确")
        ensure_identifiers_available(
            db,
            username=username if wants_username else None,
            email=email if wants_email else None,
            exclude_user_id=user.id,
        )
        if wants_username:
            user.username = username
        if wants_email:
            user.email = email

    if payload.cefr_level:
        user.cefr_level = payload.cefr_level
    if payload.interests is not None:
        user.interests = ",".join(payload.interests)
    if payload.theme:
        if payload.theme not in {t["code"] for t in levels.THEMES}:
            raise HTTPException(status_code=400, detail="皮肤不存在")
        user.theme = payload.theme
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(serialize_user(user))


@router.post("/me/password")
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    try:
        apply_password(user, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"success": True}


@router.post("/me/avatar", response_model=UserPublic)
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPublic:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in AVATAR_EXTENSIONS:
        raise HTTPException(status_code=400, detail="头像仅支持 PNG/JPG/WEBP/GIF 图片")

    raw = await read_limited(file, MAX_AVATAR_BYTES, too_large="头像不能超过 2MB")
    if not raw:
        raise HTTPException(status_code=400, detail="上传的文件是空的")

    previous = user.avatar
    user.avatar = save_avatar(file.filename or "avatar.png", raw)
    db.commit()
    db.refresh(user)

    if previous and previous != user.avatar:
        delete_avatar(previous)

    return UserPublic.model_validate(serialize_user(user))


@router.delete("/me/avatar", response_model=UserPublic)
def remove_avatar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPublic:
    previous = user.avatar
    user.avatar = None
    db.commit()
    db.refresh(user)
    delete_avatar(previous)
    return UserPublic.model_validate(serialize_user(user))


@router.get("/avatar/{name}")
def serve_avatar(name: str) -> FileResponse:
    """头像文件接口。

    不校验登录：<img> 标签无法附带 Authorization 头，而排行榜、论坛等页面
    需要展示他人头像。文件名含时间戳与内容哈希，不可枚举。
    """
    path = avatar_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(
        path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    )
