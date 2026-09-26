"""单词发音与整句朗读音频。

优先顺序：
1. 本地已缓存的音频文件（storage/audio/**）
2. 装了 edge-tts 时实时合成并缓存
3. 都没有则返回 None，前端自动回退到浏览器 Web Speech API

这样在没有外网 / 没装 edge-tts 的小内存服务器上也不会报错。

## 慢在哪：不是合成，是建连接（改之前先读这段）

实测（本机、直连）：

| 环节 | 耗时 |
| --- | --- |
| TCP + TLS + WebSocket 升级 | 0.7 ~ 1.3s |
| 同一连接上每合成一句 | 0.2 ~ 0.5s |
| 命中磁盘缓存 | < 10ms |

也就是说**每请求新建连接的写法，每句都要稳定地付 1.8s**——和句子长短几乎无关，
并发 6 路也一样（慢的是各自的握手，不是带宽，见下）。

所以这里的做法是：**后端常驻一小组连接，反复用**。连接建好之后合成只要
0.2~0.5s，等于把建连接的钱从「每句」摊到「每次重连」。

三个必须知道的边界（都实测过，别凭直觉改）：

* **一条连接上可以连做多轮合成**：`turn.end` 之后直接再发一份 SSML 即可，
  连跑 12 轮无退化。所以池子里每条连接串行服务，靠**多条连接**取并发。
* **服务端在 20~40s 没有合成活动后会主动断连**，`ping` 保活**无效**，
  `sock_read` 也不是原因（把它设成 None 照样断）。所以空闲超过 `IDLE_TTL`
  的连接直接丢掉重建，不赌它还能用。
* **死连接上发 SSML 是 0.000s 快速失败的**（`ClientConnectionResetError`），
  而 `ws.closed` 在传输已死时仍报 False。所以靠「失败就换一条重试」来兜底，
  不要靠 `ws.closed` 判断。

## 系统代理（另一条独立的坑）

edge-tts 底层用 aiohttp，而它建 ClientSession 时写死了 `trust_env=True`，
于是会去读系统代理——Windows 上来自 IE 设置 / 注册表，不一定是环境变量。
本机只要装过本地代理（Clash、公司 VPN 之类）就会出现这个坑：明明是直连
就能通的域名，请求却先绕一圈 `127.0.0.1:xxxx`。

实测（同一台机器、同一个服务）：
* 走系统代理：握手 5.9s，冷合成 6.5s
* 直连（no_proxy 命中）：握手 0.5s，冷合成 0.9s

处理方式见 `_set_direct_route`：默认把语音服务加进 no_proxy 白名单直连，
真连不上（企业网里只能走代理）再退回代理，功能优先于速度。
"""
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

# edge-tts 及其依赖都是可选的：没装的部署里语音整体降级到浏览器朗读，
# 模块导入本身不能失败。所以这一整块放 try 里，失败只记一个标记。
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
# 整句朗读用独立的语音表与目录，避免和单词发音的缓存互相覆盖
TEXT_VOICES = {"en-US": "en-US-AriaNeural", "en-GB": "en-GB-SoniaNeural"}
TEXT_DIR = AUDIO_DIR / "sentences"
_SAFE = re.compile(r"[^A-Za-z0-9_-]")

# ---------------------------------------------------------------- 连接池参数

# 池子大小 = 同时能合成的句子上限。实测 6 路并发各自仍是 0.3~0.5s、服务端不限流。
# 比背景预取的并发（前端 PREFETCH_CONCURRENCY=4）故意大几路：用户点喇叭的请求
# 不走前端队列、直接打进来，池子里必须常有空槽接着，否则点的那句要排在整篇
# 背景预取后面干等——这正是「点了喇叭半天不出声」的主因。调大前先看服务端会不会开始报错。
POOL_SIZE = 8
# 建连超时（直连实测 0.7~1.3s，留足余量）
CONNECT_TIMEOUT = 10
# 单次读超时。合成时首块音频约 0.3s、之后帧与帧之间几乎无间隔，所以这个值
# 只需要覆盖「首块音频」，同时把僵尸连接的等待上限卡住。
SOCK_READ_TIMEOUT = 10
# 一整轮合成的上限，防止极端情况把请求挂死
TURN_TIMEOUT = 30
# 空闲多久就认为连接已经不能用了。实测边界：空闲 30s 还能合成、36s 已断，
# 取 22s 留约 27% 余量。宁可多付一次重连（0.7~1.3s），也不赌一条可能已死的
# 连接——赌输要等满 SOCK_READ_TIMEOUT 才失败。
IDLE_TTL = 22.0
# 预热时先建几条。对齐前端预取的并发（frontend/lib/speech.ts 的
# PREFETCH_CONCURRENCY=6）：AI 回复边流边念，一次会同时来好几句。
WARM_CONNECTIONS = 6

# 合成服务域名，用于拼 no_proxy 白名单
TTS_HOST = "speech.platform.bing.com"
_NO_PROXY_VARS = ("no_proxy", "NO_PROXY")

# 直连优先；确认直连通不了之后置 False，后续不再每次都白等一次超时。
# 只是个性能开关，读写竞争最多让某次合成多走一趟代理，不影响正确性。
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
    """把语音服务加进 / 移出 no_proxy 白名单。

    只做增删自己那一条，用户原有的 no_proxy 条目原样保留——那是别人配的，
    覆盖掉可能踩坏其它服务。
    """
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
    """后端是否能合成语音。前端据此决定要不要显示朗读控件、要不要预取。"""
    return _IMPORT_ERROR is None


# ------------------------------------------------------------ 单条连接

def _command_frame() -> str:
    """开一条连接后先发的 speech.config：约定音频格式与元数据选项。

    格式固定为 audio-24khz-48kbitrate-mono-mp3（48kbps CBR）——连接池里所有
    连接都用同一套配置，省掉每轮重复协商。
    """
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
    """一条到 edge-tts 服务的常驻 WebSocket 连接。

    串行使用：同一条连接上不并发发多轮 SSML（响应帧里没有请求 id 可供归位），
    并发靠池子里的多条连接。
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._last_used = 0.0

    @property
    def usable(self) -> bool:
        """这条连接还能不能直接拿来用。"""
        if self._ws is None or self._ws.closed:
            return False
        # 服务端空闲 20~40s 就断连，而且 ws.closed 不一定反映得出来，
        # 所以超过 TTL 一律不赌，交给上层重建。
        return (time.monotonic() - self._last_used) < IDLE_TTL

    async def connect(self) -> None:
        """建连并发出 speech.config。"""
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
                # 直连不通（企业网里只能走代理）。改掉标记后，下一次重试就会
                # 走系统代理——这样只白等一次，不用每次请求都等一遍超时。
                _direct_route = False
                logger.warning("edge-tts 直连失败，改用系统代理: %s", exc)
            raise
        self._session = session
        self._ws = ws
        self._last_used = time.monotonic()

    async def synthesize(self, text: str, voice: str) -> bytes:
        """在已建立的连接上跑完一轮（或几轮）合成，返回拼好的 mp3 字节。"""
        ws = self._ws
        if ws is None or ws.closed:
            raise ConnectionError("连接已关闭")

        config = TTSConfig(voice, "+0%", "+0%", "+0Hz", "SentenceBoundary")
        # 服务端单轮文本上限 4096 字节，超了要拆多轮——拆出来的 mp3 段直接首尾
        # 相接即可，CBR 帧本身就能这么拼。
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
        """读到本轮的 turn.end 为止。"""
        audio = bytearray()
        while True:
            message = await ws.receive()
            kind = message.type
            if kind == aiohttp.WSMsgType.BINARY:
                header_length = int.from_bytes(message.data[:2], "big")
                params, data = get_headers_and_data(message.data, header_length)
                # 收尾会有一个不带 Content-Type 的空帧，跳过即可
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
            # PING / PONG 直接忽略

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
    """一小组常驻连接，按需复用。

    为什么要池：见模块开头的耗时表——单次合成的钱几乎全花在建连接上。旧写法
    每次请求 `asyncio.run` 一条新连接，于是每句都稳定慢 1.8s；池子把这笔钱
    从「每句」摊到「每次重连」。

    服务端空闲 20~40s 会断连，所以池子只在「连续读文章」这种爆发场景里省下
    握手；用户隔一分钟再回来，付一次重连（约 0.7~1.3s）之后又全快。
    """

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

            # 先占名额再建连：建连要 1s 上下，不能锁着 guard 做，
            # 否则冷启动时 6 条连接会排成 6 秒。
            async with self._guard:
                reserve = self._created < self._size
                if reserve:
                    self._created += 1
            if not reserve:
                # 池子满了，等别的请求还回来
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
        """提前把连接建好放进池子，用户第一次点喇叭就不付握手钱。

        池子是惰性的：第一条请求到来之前一条连接都没有，而建连要 0.7~1.3s
        （走系统代理能到 6s）。前端页面一加载就会探测 /api/audio/capability，
        那正是预热的时机——探测本身说明用户大概率会朗读。

        预热条数对齐前端的预取并发（PREFETCH_CONCURRENCY=4）：AI 回复是逐句
        边流边合成的，一次可能同时来 4 句，只热 2 条的话另外 2 句仍要各自付
        一次握手钱。

        建好的连接闲置超过 IDLE_TTL 会被正常淘汰，不会积攒死连接。
        """
        for _ in range(count):
            try:
                # 池子被真实请求占满时 _acquire 会一直等；那种情况下预热本来
                # 就没意义了，超时放弃即可，别留一个悬着的协程。
                conn = await asyncio.wait_for(self._acquire(), timeout=5)
            except Exception:  # noqa: BLE001 - 预热失败不影响后续真实请求
                return
            self._idle.put_nowait(conn)

    async def synthesize(self, text: str, voice: str) -> bytes | None:
        """取一条连接合成；失败就丢掉换一条重试一次，仍失败返回 None。

        重试是有意义的：连接可能在我们没注意的时候被服务端断掉，而那种情况
        失败得极快（0.000s），换一条新连接就能正常出音频。
        """
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


# ------------------------------------------------------ 后台事件循环与提交

_loop: asyncio.AbstractEventLoop | None = None
_pool: _Pool | None = None
_loop_guard = threading.Lock()
# 连接池结构性不可用（起不来 / 提交不进去）时置位，之后一律走一次性兜底
_pool_disabled = False
# 置位时刻。结构性故障不是永久的（比如后台循环崩了又重建），隔一段时间放行
# 一次重试，不然一次抖动之后整个进程都只能用「每句 1.8s」的一次性合成。
_pool_disabled_at = 0.0
# 结构性不可用后的重试间隔
POOL_RETRY_AFTER = 60.0


def _run_loop(loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
    global _pool, _pool_disabled
    asyncio.set_event_loop(loop)
    _pool = _Pool(POOL_SIZE)
    # 换了新的后台循环就是一个全新的池子，之前的结构性故障不再适用
    _pool_disabled = False
    ready.set()
    loop.run_forever()


def _get_loop() -> asyncio.AbstractEventLoop | None:
    """惰性启动跑连接池的后台事件循环。

    路由是同步函数、跑在 FastAPI 的线程池里，而 aiohttp 的连接得待在一个长期
    存活的事件循环上，所以单独开一条守护线程专跑它；请求侧只做
    `run_coroutine_threadsafe` + 等结果。
    """
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
    """让连接池提前建好连接，调用方（capability 探测）立即返回、不等结果。

    故意 fire-and-forget：预热失败无所谓，真实的合成请求自己会再试。
    连接池已经被判不可用时直接跳过，不改变那个状态。
    """
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
    """同步接口：把合成任务丢进后台循环并等结果。"""
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
        # 只是这一句等太久（网络抖动 / 服务端卡住），**不是**池子坏了。
        # 这里曾经和下面的分支一样把 _pool_disabled 置到底，于是接下来每句都退回
        # 一次性合成（每句多付一次 1.8s 建连），整场对话一直慢且不会自愈。
        #
        # 不撤销那个 future：让它跑完，合成结果的磁盘缓存正好留给前端重试时命中
        # （前端等不到这么久，早就自己退到下一步了）。
        logger.warning("语音连接池合成超时（%s 字），本句返回空", len(text))
        return None
    except Exception as exc:  # noqa: BLE001
        # 提交不进去 / 后台循环没了属于结构性故障，别每句都白试一遍
        logger.warning("语音连接池不可用（%s），改用一次性合成", exc)
        _pool_disabled = True
        _pool_disabled_at = time.monotonic()
        return None


def _one_shot(text: str, voice: str) -> bytes | None:
    """不开连接池的一次性合成，连接池不可用时的兜底。

    复用 `_TtsConnection`，所以直连→代理的降级逻辑和池子完全一致；`asyncio.run`
    每次新开一个事件循环，正是改造前的老路子（每句约 1.8s，慢但一定能用）。
    """
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
    # 跑两次：第一次直连失败会把 _direct_route 翻成 False，第二次就走代理
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
    """先走连接池，池子不行再退回一次性合成。"""
    data = _pool_synthesize(text, voice)
    if data:
        return data
    return _one_shot(text, voice)


def _write_atomic(path: Path, data: bytes) -> None:
    """先写 .part 再原子改名。

    直接写正式文件的话，另一个并发请求可能在写到一半时看到「文件存在且非空」，
    把半截 mp3 当成缓存命中发出去。
    """
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 单词发音

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


# ---------------------------------------------------------------- 整句朗读

def _text_cache_path(text: str, lang: str) -> Path:
    """整句音频按内容哈希命名：同一句话只合成一次，不同句子互不覆盖。"""
    digest = hashlib.sha1(f"{lang}\x00{text}".encode("utf-8")).hexdigest()
    return TEXT_DIR / f"{digest[:16]}.mp3"


def _ready(path: Path) -> bool:
    """文件存在且非空——半截的 mp3 不能拿去播，也不算缓存命中。"""
    return path.exists() and path.stat().st_size > 0


# 同一句话的合成锁。前端「预取」和「点击」可能同时请求同一句，两路各合成一次
# 既白白多等一个来回，又可能把同一个文件写花。按缓存路径加锁后，后到的那路直接
# 吃前一路的成果。锁只保护合成过程，不保护缓存读取，所以不同句子仍是并发的。
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
    """把整句英文合成为 mp3 并缓存，拿不到音频时返回 None。

    浏览器自带的 speechSynthesis 在内嵌 webview 里可能只装了中文语音，
    读英文会「点了没声音」。这条后端通道保证朗读始终可用，前端仍会在 404 时
    回退到浏览器朗读。

    命中磁盘缓存是毫秒级的；走连接池的冷合成 0.2~0.5s（几乎全花在首块音频上，
    连接是复用的）；连接池不可用而退回一次性合成时约 1.8s。所以前端会提前预取，
    这里则保证重复请求不会重复合成。
    """
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
        # 等锁期间别的一路可能已经合成好了，再确认一次
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


# 测试里不想让每个用例都拉起一条预热线程（也没网），由 SPEECH_PREWARM=0 关掉
_DISABLE_PREWARM = not settings.speech_prewarm


def set_prewarm_enabled(enabled: bool) -> None:
    global _DISABLE_PREWARM
    _DISABLE_PREWARM = not enabled


def prewarm_text(text: str, lang: str = "en-US") -> None:
    """后台把一句话的音频先合成好，调用方立即返回。

    场景开场白、任务提问这些都是**固定文本**：用户还没开口，我们就知道他会听
    到哪一句。提前合成掉，等他真正进到对话页时朗读就是毫秒级命中磁盘缓存，
    而不是现场付一次「建连 + 合成」的 1~2 秒（走系统代理时能到 6 秒）。
    """
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
    """批量预热（一句一个线程）。给启动时的开场白预热用。"""
    for text in texts:
        prewarm_text(text, lang)
