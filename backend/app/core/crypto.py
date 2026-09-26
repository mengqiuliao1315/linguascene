"""API Key 的对称加密存储。

用户自填的模型 Key 属于敏感凭据，库里不落明文。密钥由 SECRET_KEY
派生（HKDF-SHA256），因此不需要新增环境变量；代价是 SECRET_KEY
一旦更换，旧的加密 Key 无法解开，需要用户重新填写——这与本项目
"生产必须改 SECRET_KEY" 的部署约定一致。
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# Fernet 需要 32 字节 urlsafe base64 密钥；用 SECRET_KEY 派生固定盐值
_KEY_SALT = b"linguascene-ai-credential-v1"


def _fernet() -> Fernet:
    digest = hashlib.pbkdf2_hmac(
        "sha256", settings.secret_key.encode("utf-8"), _KEY_SALT, 100_000
    )
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """加密后的密文以字符串存库。"""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str | None:
    """解密失败（换过 SECRET_KEY 或数据损坏）返回 None，由调用方降级。"""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def secret_fingerprint(ciphertext: str) -> str:
    """只用于展示/缓存隔离的短指纹，不泄露明文。"""
    if not ciphertext:
        return ""
    return hashlib.sha256(ciphertext.encode("ascii")).hexdigest()[:12]
