"""缓存抽象。

默认使用进程内 TTL 缓存，零依赖即可运行；设置 CACHE_BACKEND=redis 后
自动切换到 Redis。用于缓存单词释义、文章分析等昂贵且可复用的 AI 结果。
"""

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> Any | None: ...

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int = 86400) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class InMemoryCache(CacheBackend):
    def __init__(self, max_items: int = 2048) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max_items = max_items

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int = 86400) -> None:
        with self._lock:
            if len(self._data) >= self._max_items:
                # 简单的容量淘汰：清掉最早过期的 10%
                ordered = sorted(self._data.items(), key=lambda kv: kv[1][0])
                for k, _ in ordered[: max(1, self._max_items // 10)]:
                    self._data.pop(k, None)
            self._data[key] = (time.time() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


class RedisCache(CacheBackend):  # pragma: no cover - 需要真实 Redis
    def __init__(self, url: str) -> None:
        import redis  # 延迟导入，未安装时不影响内存缓存路径

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def set(self, key: str, value: Any, ttl_seconds: int = 86400) -> None:
        self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self._client.delete(key)


_cache: CacheBackend | None = None


def get_cache() -> CacheBackend:
    global _cache
    if _cache is None:
        if settings.cache_backend == "redis":
            try:
                _cache = RedisCache(settings.redis_url)
            except ImportError:
                logger.error(
                    "CACHE_BACKEND=redis，但未安装 redis 包。"
                    "请执行 `py -3.12 -m pip install redis`，当前回落到进程内缓存。"
                )
                _cache = InMemoryCache()
            except Exception as exc:  # noqa: BLE001 - 连不上时仍要能启动
                logger.error(
                    "Redis 不可用（%s），当前回落到进程内缓存。多实例部署时结果不会共享。",
                    exc,
                )
                _cache = InMemoryCache()
        else:
            _cache = InMemoryCache()
    return _cache


def cache_key(*parts: str) -> str:
    return "linguascene:" + ":".join(str(p).strip().lower() for p in parts)


def reset_cache() -> None:
    """测试用：丢掉已选中的缓存后端。"""
    global _cache
    _cache = None
