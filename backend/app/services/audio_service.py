from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import ssl
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from xml.sax.saxutils import escape

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import aiohttp
    import certifi
    from edge_tts.communicate import (
        connect_id,
        date_to_string,
        get_headers_and_data,
        mkssml,
        remove_incompatible_characters,
        split_text_by_byte_length,
        ssml_headers_plus_data,
    )
    from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
    from edge_tts.data_classes import TTSConfig
    from edge_tts.drm import DRM

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - 取决于部署环境
    _IMPORT_ERROR = str(exc)

AUDIO_DIR = Path(__file__).resolve().parents[2] / "storage" / "audio"
VOICES = {"us": "en-US-AriaNeural", "uk": "en-GB-SoniaNeural"}
TEXT_VOICES = {"en-US": "en-US-AriaNeural", "en-GB": "en-GB-SoniaNeural"}
TEXT_DIR = AUDIO_DIR / "sentences"
_SAFE = re.compile(r"[^A-Za-z0-9_-]")


POOL_SIZE = 8
CONNECT_TIMEOUT = 10
SOCK_READ_TIMEOUT = 10
TURN_TIMEOUT = 30
IDLE_TTL = 22.0
WARM_CONNECTIONS = 6

TTS_HOST = "speech.platform.bing.com"
_NO_PROXY_VARS = ("no_proxy", "NO_PROXY")

_direct_route = True

_SSL_CTX: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    return _SSL_CTX


def _safe(word: str) -> str:
    return _SAFE.sub("", word.strip().lower().replace(" ", "_"))[:48]


def _set_direct_route(enabled: bool) -> None:
    current = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    hosts = [item.strip() for item in current.split(",") if item.strip()]
    hosts = [host for host in hosts if host != TTS_HOST]
    if enabled:
        hosts.append(TTS_HOST)

    value = ",".join(hosts)
    for key in _NO_PROXY_VARS:
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def tts_available() -> bool:
    return _IMPORT_ERROR is None


def _command_frame() -> str:
    return (
        f"X-Timestamp:{date_to_string()}\r\n"
        "Content-Type:application/json; charset=utf-8\r\n"
        "Path:speech.config\r\n\r\n"
        '{"context":{"synthesis":{"audio":{"metadataoptions":{'
        '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
        "},"
        '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"'
        "}}}}\r\n"
    )


class _TtsConnection:

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._last_used = 0.0

    @property
    def usable(self) -> bool:
        if self._ws is None or self._ws.closed:
            return False
        return (time.monotonic() - self._last_used) < IDLE_TTL

    async def connect(self) -> None:
        global _direct_route
        _set_direct_route(_direct_route)

        timeout = aiohttp.ClientTimeout(
            total=None, sock_connect=CONNECT_TIMEOUT, sock_read=SOCK_READ_TIMEOUT
        )
        session = aiohttp.ClientSession(timeout=timeout)
        try:
            ws = await session.ws_connect(
                f"{WSS_URL}&ConnectionId={connect_id()}"
                f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
                f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
                compress=15,
                headers=DRM.headers_with_muid(WSS_HEADERS),
                ssl=_ssl_context(),
            )
            await ws.send_str(_command_frame())
        except Exception as exc:
            await session.close()
            if _direct_route:
                _direct_route = False
                logger.warning("edge-tts 直连失败，改用系统代理: %s", exc)
            raise
        self._session = session
        self._ws = ws
        self._last_used = time.monotonic()

    async def synthesize(self, text: str, voice: str) -> bytes:
        ws = self._ws
        if ws is None or ws.closed:
            raise ConnectionError("连接已关闭")

        config = TTSConfig(voice, "+0%", "+0%", "+0Hz", "SentenceBoundary")
        chunks = split_text_by_byte_length(
            escape(remove_incompatible_characters(text)), 4096
        )

        audio = bytearray()
        for chunk in chunks:
            await ws.send_str(
                ssml_headers_plus_data(
                    connect_id(), date_to_string(), mkssml(config, chunk)
                )
            )
            audio += await self._read_turn(ws)
        self._last_used = time.monotonic()
        return bytes(audio)

    async def _read_turn(self, ws: aiohttp.ClientWebSocketResponse) -> bytes:
        audio = bytearray()
        while True:
            message = await ws.receive()
            kind = message.type
            if kind == aiohttp.WSMsgType.BINARY:
                header_length = int.from_bytes(message.data[:2], "big")
                params, data = get_headers_and_data(message.data, header_length)
                if params.get(b"Path") == b"audio" and data:
                    audio += data
            elif kind == aiohttp.WSMsgType.TEXT:
                encoded = message.data.encode("utf-8")
                params, _ = get_headers_and_data(encoded, encoded.find(b"\r\n\r\n"))
                if params.get(b"Path") == b"turn.end":
                    return bytes(audio)
            elif kind in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                raise ConnectionError("合成过程中连接被关闭")
            elif kind == aiohttp.WSMsgType.ERROR:
                raise ConnectionError(f"WebSocket 错误: {message.data}")

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        session, self._session = self._session, None
        try:
            if ws is not None and not ws.closed:
                await ws.close()
        except Exception:  # noqa: BLE001 - 关闭失败无所谓
            pass
        if session is not None:
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass


class _Pool:

    def __init__(self, size: int) -> None:
        self._size = size
        self._idle: asyncio.Queue[_TtsConnection] = asyncio.Queue()
        self._created = 0
        self._guard = asyncio.Lock()

    async def _acquire(self) -> _TtsConnection:
        while True:
            try:
                conn = self._idle.get_nowait()
            except asyncio.QueueEmpty:
                conn = None

            if conn is not None:
                if conn.usable:
                    return conn
                await self._discard(conn)
                continue

            async with self._guard:
                reserve = self._created < self._size
                if reserve:
                    self._created += 1
            if not reserve:
                return await self._idle.get()

            conn = _TtsConnection()
            try:
                await conn.connect()
            except BaseException:
                async with self._guard:
                    self._created -= 1
                raise
            return conn

    async def _discard(self, conn: _TtsConnection) -> None:
        async with self._guard:
            self._created -= 1
        await conn.close()

    async def warm_up(self, count: int = WARM_CONNECTIONS) -> None:
        for _ in range(count):
            try:
                conn = await asyncio.wait_for(self._acquire(), timeout=5)
            except Exception:  # noqa: BLE001 - 预热失败不影响后续真实请求
                return
            self._idle.put_nowait(conn)

    async def synthesize(self, text: str, voice: str) -> bytes | None:
        last: Exception | None = None
        for _ in range(2):
            conn = await self._acquire()
            try:
                data = await asyncio.wait_for(
                    conn.synthesize(text, voice), timeout=TURN_TIMEOUT
                )
            except asyncio.CancelledError:
                await self._discard(conn)
                raise
            except Exception as exc:  # noqa: BLE001 - 任何异常都当连接坏了
                last = exc
                await self._discard(conn)
                continue

            if not data:
                last = ValueError("合成结果为空")
                await self._discard(conn)
                continue
            self._idle.put_nowait(conn)
            return data

        logger.warning("edge-tts 连接池合成失败: %s", last)
        return None


_loop: asyncio.AbstractEventLoop | None = None
_pool: _Pool | None = None
_loop_guard = threading.Lock()
_pool_disabled = False
_pool_disabled_at = 0.0
POOL_RETRY_AFTER = 60.0


def _run_loop(loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
    global _pool, _pool_disabled
    asyncio.set_event_loop(loop)
    _pool = _Pool(POOL_SIZE)
    _pool_disabled = False
    ready.set()
    loop.run_forever()


def _get_loop() -> asyncio.AbstractEventLoop | None:
    global _loop
    with _loop_guard:
        if _loop is not None and _loop.is_running():
            return _loop
        if _IMPORT_ERROR is not None:
            return None

        loop = asyncio.new_event_loop()
        ready = threading.Event()
        threading.Thread(
            target=_run_loop,
            args=(loop, ready),
            name="tts-pool",
            daemon=True,
        ).start()
        if not ready.wait(timeout=5):  # pragma: no cover - 起不来就降级
            logger.warning("语音连接池线程启动超时，退回一次性合成")
            return None
        _loop = loop
        return _loop


def warm_up() -> None:
    if _pool_disabled or _IMPORT_ERROR is not None:
        return
    loop = _get_loop()
    pool = _pool
    if loop is None or pool is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(pool.warm_up(), loop)
    except Exception:  # noqa: BLE001 - 提交失败说明池子结构性不可用
        pass


def _pool_synthesize(text: str, voice: str) -> bytes | None:
    global _pool_disabled, _pool_disabled_at
    if _pool_disabled:
        if time.monotonic() - _pool_disabled_at < POOL_RETRY_AFTER:
            return None
        _pool_disabled = False

    loop = _get_loop()
    pool = _pool
    if loop is None or pool is None:
        _pool_disabled = True
        _pool_disabled_at = time.monotonic()
        return None

    try:
        future = asyncio.run_coroutine_threadsafe(pool.synthesize(text, voice), loop)
        return future.result(timeout=TURN_TIMEOUT * 2 + 5)
    except FutureTimeout:
        logger.warning("语音连接池合成超时（%s 字），本句返回空", len(text))
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("语音连接池不可用（%s），改用一次性合成", exc)
        _pool_disabled = True
        _pool_disabled_at = time.monotonic()
        return None


def _one_shot(text: str, voice: str) -> bytes | None:
    if _IMPORT_ERROR is not None:
        return None

    async def run() -> bytes:
        conn = _TtsConnection()
        try:
            await conn.connect()
            return await asyncio.wait_for(
                conn.synthesize(text, voice), timeout=TURN_TIMEOUT
            )
        finally:
            await conn.close()

    last: Exception | None = None
    for _ in range(2):
        try:
            data = asyncio.run(run())
        except Exception as exc:  # noqa: BLE001 - 依赖网络
            last = exc
            logger.warning("edge-tts 一次性合成失败（%s 字）: %s", len(text), exc)
            continue
        if data:
            return data
        last = ValueError("合成结果为空")
    logger.warning("edge-tts 一次性合成最终失败: %s", last)
    return None


def _synthesize_bytes(text: str, voice: str) -> bytes | None:
    data = _pool_synthesize(text, voice)
    if data:
        return data
    return _one_shot(text, voice)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def cached_path(word: str, accent: str = "us") -> Path | None:
    accent = accent if accent in VOICES else "us"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".mp3", ".wav", ".ogg", ".m4a"):
        p = AUDIO_DIR / f"{_safe(word)}_{accent}{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _synthesize(word: str, accent: str) -> Path | None:
    if not tts_available():
        return None

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIO_DIR / f"{_safe(word)}_{accent}.mp3"
    data = _synthesize_bytes(word, VOICES[accent])
    if not data:
        return None
    _write_atomic(out, data)
    return out


def get_or_create(word: str, accent: str = "us") -> Path | None:
    accent = accent if accent in VOICES else "us"
    path = cached_path(word, accent)
    if path:
        return path
    return _synthesize(word, accent)


def _text_cache_path(text: str, lang: str) -> Path:
    digest = hashlib.sha1(f"{lang}\x00{text}".encode("utf-8")).hexdigest()
    return TEXT_DIR / f"{digest[:16]}.mp3"


def _ready(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


_synth_locks: dict[str, threading.Lock] = {}
_synth_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = path.name
    with _synth_locks_guard:
        lock = _synth_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _synth_locks[key] = lock
        return lock


def synthesize_text(text: str, lang: str = "en-US") -> Path | None:
    content = text.strip()
    if not content:
        return None
    lang = lang if lang in TEXT_VOICES else "en-US"

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    out = _text_cache_path(content, lang)
    if _ready(out):
        return out

    if not tts_available():
        return None

    with _lock_for(out):
        if _ready(out):
            return out

        data = _synthesize_bytes(content, TEXT_VOICES[lang])
        if not data:
            return None
        _write_atomic(out, data)
        return out


def _prewarm(text: str, lang: str) -> None:
    try:
        synthesize_text(text, lang)
    except Exception as exc:  # noqa: BLE001 - 预热失败不影响任何功能
        logger.info("语音预热失败（%s 字）：%s", len(text), exc)


_DISABLE_PREWARM = not settings.speech_prewarm


def set_prewarm_enabled(enabled: bool) -> None:
    global _DISABLE_PREWARM
    _DISABLE_PREWARM = not enabled


def prewarm_text(text: str, lang: str = "en-US") -> None:
    content = (text or "").strip()
    if not content or _DISABLE_PREWARM or not tts_available():
        return
    lang = lang if lang in TEXT_VOICES else "en-US"
    if _ready(_text_cache_path(content, lang)):
        return
    threading.Thread(
        target=_prewarm, args=(content, lang), name="tts-prewarm", daemon=True
    ).start()


def prewarm_lines(texts, lang: str = "en-US") -> None:
    for text in texts:
        prewarm_text(text, lang)
