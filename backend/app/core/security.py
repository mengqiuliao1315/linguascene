from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.crypto import encrypt_secret

ALGORITHM = "HS256"


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
    """设置登录密码并作废已发出的访问令牌。"""
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
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        version = int(payload.get("ver") or 0)
    except (TypeError, ValueError):
        version = 0
    return str(sub), version
