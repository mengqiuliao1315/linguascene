from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.crypto import encrypt_secret

ALGORITHM = "HS256"

DOWNLOAD_SCOPE = "reading_export"


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("密码过长，请缩短后再试")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        raw = password.encode("utf-8")
        if len(raw) > 72:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def apply_password(user, password: str) -> None:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("密码过长，请缩短后再试")
    user.password_hash = hash_password(password)
    user.password_enc = encrypt_secret(password)
    user.password_updated_at = datetime.now(timezone.utc)
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1


def create_access_token(
    subject: str,
    expires_minutes: int | None = None,
    *,
    token_version: int = 0,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "ver": int(token_version or 0),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> tuple[str, int] | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    # 带 scope 的非登录令牌（例如下载票据）不能当访问令牌用，否则泄露的下载
    # 地址会等于泄露一枚可读写全部接口的登录令牌。
    if payload.get("scope") not in (None, "access"):
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        version = int(payload.get("ver") or 0)
    except (TypeError, ValueError):
        version = 0
    return str(sub), version


def create_download_token(
    user_id: int, material_id: int, kind: str, expires_minutes: int = 10
) -> str:
    """签发一张短时效下载票据，只用于把 PDF 交给浏览器下载（不携带登录权限）。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "mid": int(material_id),
        "kind": kind,
        "scope": DOWNLOAD_SCOPE,
        "exp": now + timedelta(minutes=expires_minutes),
        "iat": now,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_download_token(token: str) -> tuple[int, int, str] | None:
    """校验下载票据，返回 (user_id, material_id, kind)。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("scope") != DOWNLOAD_SCOPE:
        return None
    try:
        return int(payload["sub"]), int(payload["mid"]), str(payload["kind"])
    except (KeyError, TypeError, ValueError):
        return None
