import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_KEY_SALT = b"linguascene-ai-credential-v1"


def _fernet() -> Fernet:
    digest = hashlib.pbkdf2_hmac(
        "sha256", settings.secret_key.encode("utf-8"), _KEY_SALT, 100_000
    )
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def secret_fingerprint(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return hashlib.sha256(ciphertext.encode("ascii")).hexdigest()[:12]
