"""文件存储抽象。默认写本地磁盘，设置 STORAGE_BACKEND=s3 后走 S3 兼容对象存储。"""

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".srt", ".vtt", ".json"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 头像与内容上传分开：只收图片，体积也限制得更小，避免小内存服务器被塞满
AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_DIR = Path(__file__).resolve().parents[2] / "storage" / "avatars"


def save_avatar(filename: str, raw: bytes) -> str:
    """保存头像，返回可直接用于 <img src> 的 URL 路径。

    文件名带内容哈希与时间戳，既避免重名覆盖，也让旧头像在换新后自然失效。
    """
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(raw).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    name = f"{stamp}-{digest}{Path(filename).suffix.lower()}"
    (AVATAR_DIR / name).write_bytes(raw)
    return f"/api/users/avatar/{name}"


def avatar_path(url_or_name: str) -> Path | None:
    """把头像 URL 还原为本地路径；只认文件名，防止路径穿越。"""
    name = Path(url_or_name).name
    if not name:
        return None
    path = AVATAR_DIR / name
    return path if path.is_file() else None


def delete_avatar(url: str | None) -> None:
    """删除被替换掉的头像文件，失败不报错。"""
    if not url:
        return
    path = avatar_path(url)
    if path:
        path.unlink(missing_ok=True)


# 论坛配图：用户发帖时引用的图片，与头像分开存放，便于单独限额与清理
FORUM_IMAGE_DIR = Path(__file__).resolve().parents[2] / "storage" / "forum"
MAX_FORUM_IMAGE_BYTES = 5 * 1024 * 1024


def save_forum_image(filename: str, raw: bytes) -> str:
    """保存论坛配图，返回可直接用于 Markdown ![]() 的 URL 路径。"""
    FORUM_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(raw).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    name = f"{stamp}-{digest}{Path(filename).suffix.lower()}"
    (FORUM_IMAGE_DIR / name).write_bytes(raw)
    return f"/api/forum/images/{name}"


def forum_image_path(url_or_name: str) -> Path | None:
    """把论坛图片 URL 还原为本地路径；只认文件名，防止路径穿越。"""
    name = Path(url_or_name).name
    if not name:
        return None
    path = FORUM_IMAGE_DIR / name
    return path if path.is_file() else None


class StorageBackend(ABC):
    @abstractmethod
    def save(self, filename: str, content: bytes) -> str: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...


class LocalStorage(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, filename: str) -> str:
        stem = Path(filename).stem[:48]
        digest = hashlib.sha1(filename.encode("utf-8")).hexdigest()[:10]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{stamp}-{digest}-{stem}{Path(filename).suffix.lower()}"

    def save(self, filename: str, content: bytes) -> str:
        key = self._safe_name(filename)
        (self.root / key).write_bytes(content)
        return key

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class S3Storage(StorageBackend):  # pragma: no cover - 需要真实对象存储
    def __init__(self) -> None:
        import boto3

        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
        )

    def save(self, filename: str, content: bytes) -> str:
        key = f"uploads/{LocalStorage(settings.storage_path)._safe_name(filename)}"
        self._client.put_object(Bucket=self._bucket, Key=key, Body=content)
        return key

    def read(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        if settings.storage_backend == "s3" and settings.s3_bucket:
            try:
                _storage = S3Storage()
            except ImportError:
                logger.error(
                    "STORAGE_BACKEND=s3，但未安装 boto3。"
                    "请执行 `py -3.12 -m pip install boto3`，当前回落到本地磁盘。"
                )
                _storage = LocalStorage(settings.storage_path)
            except Exception as exc:  # noqa: BLE001 - 对象存储不可用时仍要能上传
                logger.error(
                    "对象存储不可用（%s），当前回落到本地磁盘。",
                    exc,
                )
                _storage = LocalStorage(settings.storage_path)
        elif settings.storage_backend == "s3":
            logger.error("STORAGE_BACKEND=s3 但未配置 S3_BUCKET，当前回落到本地磁盘。")
            _storage = LocalStorage(settings.storage_path)
        else:
            _storage = LocalStorage(settings.storage_path)
    return _storage


def reset_storage() -> None:
    """测试用：丢掉已选中的存储后端。"""
    global _storage
    _storage = None
