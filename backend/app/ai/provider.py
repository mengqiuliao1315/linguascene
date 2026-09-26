"""统一 AI Provider 接口与多 API 格式适配。

业务代码只依赖 AIProvider，不直接依赖任何模型 SDK。
- MockAIProvider: 无外部依赖，返回 None 表示“请走规则引擎”，保证本地可运行。
- HttpAIProvider: 按 api_format 适配各家 HTTP 接口。

支持的 API 格式（api_format）：
- openai: /v1/chat/completions（OpenAI、DeepSeek、Moonshot 及绝大多数兼容服务）
- openai_responses: /v1/responses（OpenAI Responses API）
- anthropic: /v1/messages（Claude 官方与兼容网关）
- gemini: /v1beta/models/{model}:generateContent（Google Gemini）

实例可以来自三处，优先级见 app.services.ai_config_service：
用户自己填的供应商配置、用户采纳的别人的分享、部署时的环境变量兜底。
每个实例带一个 signature，用于把不同模型的结果隔离开，避免互相污染缓存。

系统 Prompt 中的 {schema} 占位符会被替换为 JSON Schema 文本，让模型按结构输出。
"""

import ipaddress
import json
import logging
import random
import re
import socket
import struct
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import getproxies

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.crypto import secret_fingerprint

logger = logging.getLogger(__name__)

FORMAT_OPENAI = "openai"
FORMAT_OPENAI_RESPONSES = "openai_responses"
FORMAT_ANTHROPIC = "anthropic"
FORMAT_GEMINI = "gemini"

API_FORMATS = (FORMAT_OPENAI, FORMAT_OPENAI_RESPONSES, FORMAT_ANTHROPIC, FORMAT_GEMINI)
DEFAULT_API_FORMAT = FORMAT_OPENAI

# 用户常把完整端点粘进“地址”框，归一化时剥掉这些尾巴
_STRIP_SUFFIXES = ("/chat/completions", "/responses", "/messages", "/models")

# --------------------------------------------------------------- 探活参数
#
# 「测试连接」只验证地址 + Key + 模型名能否走通，不校验业务 Schema。
# 思考型模型可能要几十秒才回 ping，所以读超时比连接超时更宽。
PROBE_USER_TEXT = "ping"
PROBE_MAX_TOKENS = 16
PROBE_TIMEOUT_SECONDS = 45.0
PROBE_CONNECT_TIMEOUT_SECONDS = 10.0
PROBE_TOTAL_BUDGET_SECONDS = 90.0
PROBE_CREDENTIAL_TIMEOUT_SECONDS = 12.0
PROBE_ATTEMPTS = 4
PROBE_RETRY_DELAY = 0.6
PROBE_RATE_LIMIT_CAP = 8.0
COMPLETE_ATTEMPTS = 4
COMPLETE_RETRY_DELAY = 0.5

# 临时性传输故障：连不上、超时、连接被中途掐断、代理异常。
_TRANSIENT_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ProxyError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
    httpx.WriteTimeout,
)

# 常见状态码的中文解释，让用户直接知道下一步改什么
_PROBE_STATUS_HINTS: dict[int, str] = {
    400: "服务商认为请求不合法，多半是模型名写错了",
    401: "API Key 不被接受，确认是否复制完整、是否已过期",
    402: "账号余额不足",
    403: "API Key 没有权限访问这个模型",
    404: "地址或模型名不对：确认 Base URL 是否需要 /v1，模型名是否拼写正确",
    405: "地址指向的不是模型接口，确认 Base URL 是否填成了网页地址",
    422: "服务商不接受请求里的某个字段，多半是模型名写错了",
    429: "触发了服务商限流，等几秒再试",
    500: "服务商内部错误，通常是临时的，稍后再试",
    502: "服务商网关错误，通常是临时的，稍后再试",
    503: "服务商暂时不可用，稍后再试",
    504: "服务商网关超时，稍后再试",
}


class AIProviderError(RuntimeError):
    """模型调用失败，或返回内容不符合 Schema。"""


@dataclass
class ProbeOutcome:
    """一次探活的结论。

    三档而不是两档：「地址与 Key 都对、只是模型没在超时内吐字」既不是成功，
    也不该被当成错误——思考型模型（DeepSeek-R1 实测一个 ping 能跑 10~75 秒）
    经常这样，报成红色错误会逼着用户一遍遍点「测试连接」，看着就像系统抽风。
    """

    success: bool
    message: str
    status: str = "ok"  # ok | warn | fail
    # 失败时顺手带出该地址下真实存在的模型名，省得用户对着 404 猜模型名
    suggested_models: list[str] = field(default_factory=list)


# 流式请求的建连超时。首 token 通常 0.3~2s，留足余量。
STREAM_CONNECT_TIMEOUT = 10.0

# ------------------------------------------------------- 语音转写（用用户自己的模型）
#
# 转写走用户当前选中的地址、Key 和模型名（/audio/transcriptions），不再按服务商
# 地址另挑一份模型名单：那会把录音打到用户没填过的模型上。
# 探测结果按 provider signature 记一笔：这个模型认不认转写。改配置会换
# signature，记忆自然失效。
# 探测用音频时长：够长以免被服务商当「空音频」拒绝，又不至于白花合成时间
STT_PROBE_SECONDS = 0.8
# 单次转写超时。实测一段 5 秒音频约 0.7s；但免费额度的服务商偶发几十秒无响应
# （硅基流动的 SenseVoice 就遇到过），与其让前端一直转圈，不如早点失败让用户重说。
STT_TIMEOUT_SECONDS = 15.0


class AIProvider(ABC):
    name: str
    model: str = ""
    api_format: str = DEFAULT_API_FORMAT

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def signature(self) -> str:
        """缓存隔离用：不同接入方式的结果不互相复用。"""
        return self.name

    @property
    def label(self) -> str:
        """给用户看的来源名称，不包含任何凭据。"""
        return self.name

    @abstractmethod
    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """返回符合 schema 的 dict；返回 None 表示交由调用方使用规则引擎。

        max_tokens 仅在批量等需要更大输出的场景覆盖默认值，传 None 走
        provider 自带的 self.max_tokens。做成可选关键字参数是为了不破坏
        只实现了三参数签名的测试替身——它们忽略该参数即可。
        """

    def complete_json_fast(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """结构化请求的低延迟通道。

        默认实现保持旧 provider 的兼容性；支持重试预算的 provider 可以覆盖它，
        将首句请求限制为一次尝试，避免流式精读的首个结果被重试拖住。
        """
        return self.complete_json(system_prompt, user_prompt, schema)

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        """返回纯文本（非 JSON），用于只需要一段话的场景。

        比 complete_json 快：不带 response_format、不做 JSON 解析与校验，
        模型直接输出正文。默认实现退回到 complete_json 取第一个字符串字段，
        真正的 provider 应覆写。
        """
        raise AIProviderError("当前 provider 不支持纯文本补全")

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """流式纯文本补全，逐块 yield 文本。

        支持 OpenAI 兼容格式的 stream:true；其它格式默认退回 complete_text
        一次性返回整段。yield 的每个 chunk 是一小段文本（0~若干字），
        调用方拼起来就是完整回复。
        """
        # 默认：不支持流式，一次性返回
        yield self.complete_text(system_prompt, user_prompt, max_tokens=max_tokens)

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.webm",
        content_type: str = "audio/webm",
        language: str = "en",
    ) -> str | None:
        """把一段录音转成英文文本，返回 None 表示这个 provider 不支持转写。

        返回 None 与抛异常是两件事：前者是「这个接入方式没有语音识别能力」，
        调用方据此告诉用户换一个支持转写的模型或改用其它识别通道；后者是
        「本该能用但这次失败了」，调用方应当提示用户重试，而不是悄悄降级。
        """
        return None


class MockAIProvider(AIProvider):
    name = "mock"

    @property
    def is_mock(self) -> bool:
        return True

    @property
    def label(self) -> str:
        return "离线规则引擎"

    def complete_json(
        self, system_prompt: str, user_prompt: str, schema: type[BaseModel]
    ) -> dict[str, Any] | None:
        # 离线模式：不产生假数据，明确交给规则引擎计算真实结果
        return None

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        # 离线模式：返回空串，由调用方走规则引擎
        return ""

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.webm",
        content_type: str = "audio/webm",
        language: str = "en",
    ) -> str | None:
        # 离线模式（没配任何模型）没有语音识别能力
        return None


# --------------------------------------------------------------- 地址归一化


def _ensure_scheme(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return raw


def _strip_endpoint_suffix(path: str) -> str:
    for suffix in _STRIP_SUFFIXES:
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


def normalize_base_url(raw: str, api_format: str = DEFAULT_API_FORMAT) -> str:
    """把用户填的地址整理成可直接拼接端点的根地址。

    容错：缺协议补 https、多余的尾斜杠、误粘的完整端点（/chat/completions 等）。
    填错的地址在这里就以 AIProviderError 报出来——早先这些错误会拖到发请求时
    才炸（`http://[::1/v1` 直接 500，`https://` 报一句英文的 URL 缺协议），
    用户只看到「服务器内部错误」，完全不知道该改哪里。
    """
    raw = _ensure_scheme(raw)
    if not raw:
        return ""
    if re.search(r"\s", raw):
        raise AIProviderError("Base URL 里有空格，检查一下是不是复制时带进了多余字符")
    try:
        parsed = urlparse(raw)
    except ValueError as exc:  # 方括号没配对等（urlparse 抛的是英文的 Invalid IPv6 URL）
        raise AIProviderError(f"Base URL 格式不正确：{exc}") from exc
    if not parsed.netloc:
        raise AIProviderError("Base URL 缺少域名，应形如 https://api.example.com/v1")
    path = _strip_endpoint_suffix(parsed.path.rstrip("/")).rstrip("/")

    if api_format == FORMAT_ANTHROPIC:
        if path.endswith("/v1"):
            path = path[: -len("/v1")]
        path = path.rstrip("/")
    elif api_format == FORMAT_GEMINI:
        if not path.endswith("/v1beta"):
            path = f"{path}/v1beta" if path else "/v1beta"
    elif not path:
        # OpenAI 兼容接口约定挂在 /v1 下；已有自定义路径（如 /api/v1）则原样保留
        path = "/v1"

    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_public_http_url(raw: str, *, resolve: bool = True) -> None:
    """拦截指向本机、内网或链路本地地址的模型接口，避免 SSRF。

    保存配置时只检查字面量地址与明确的本机名，避免虚构域名在离线测试里
    因 DNS 失败而无法入库。真正发请求时再解析 DNS，挡住解析到私网的主机。
    """
    if not raw:
        return
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise AIProviderError("模型地址只支持 http 或 https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise AIProviderError("Base URL 缺少域名")
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise AIProviderError("不能使用本机或内网地址作为模型接口")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_is_blocked(literal):
            raise AIProviderError("不能使用本机或内网地址作为模型接口")
        return
    if not resolve:
        return
    try:
        answers = socket.getaddrinfo(host, parsed.port or None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AIProviderError(f"无法解析模型地址：{host}") from exc
    if not answers:
        raise AIProviderError(f"无法解析模型地址：{host}")
    for item in answers:
        ip = ipaddress.ip_address(item[4][0])
        if _ip_is_blocked(ip):
            raise AIProviderError("不能使用解析到内网的地址作为模型接口")


# --------------------------------------------------------------- 连接复用


_shared_client_instance: httpx.Client | None = None
_shared_client_lock = threading.Lock()

# 记下不支持 response_format 的接入方（按 signature 区分）。命中后不再每轮先发
# 一次注定 400 的请求再重试，省掉一次完整往返。
_json_mode_unsupported: set[str] = set()


def _shared_client() -> httpx.Client:
    """进程级共享连接池。

    模型调用是每轮对话最慢的一步。之前每次 complete_json 都新建 httpx.Client，
    等于每轮都重做一次 DNS + TLS 握手；共用连接池后 keep-alive 直接复用。
    超时按请求传入，见 _send。
    """
    global _shared_client_instance
    if _shared_client_instance is None:
        with _shared_client_lock:
            if _shared_client_instance is None:
                _shared_client_instance = httpx.Client(
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                )
    return _shared_client_instance


def close_shared_client() -> None:
    """关闭共享连接池，供测试与进程退出时调用。"""
    global _shared_client_instance, _shared_stream_client_instance
    if _shared_client_instance is not None:
        _shared_client_instance.close()
        _shared_client_instance = None
    if _shared_stream_client_instance is not None:
        _shared_stream_client_instance.close()
        _shared_stream_client_instance = None


_shared_stream_client_instance: httpx.Client | None = None


def _shared_stream_client() -> httpx.Client:
    """流式请求的共享客户端。

    以前每次 stream_text 都新建 client 再关掉，等于每轮对话都重做一次 DNS +
    TLS 握手——而一轮对话的「AI 开口时间」里这几百毫秒是白等的。连接池化之后
    只有进程启动后的第一轮付这笔钱。
    """
    global _shared_stream_client_instance
    if _shared_stream_client_instance is None:
        with _shared_client_lock:
            if _shared_stream_client_instance is None:
                _shared_stream_client_instance = httpx.Client(
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
                )
    return _shared_stream_client_instance


def _json_mode_unsupported_status(exc: Exception) -> bool:
    """这些状态码视为接入方不认 response_format，而不是回复内容有问题。"""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (400, 404, 415, 422)
    )


def _rejects_param(exc: Exception, param: str) -> bool:
    """接入方是否在报错里点名了某个请求参数。

    只有明确点名才做替换，避免把「内容不合法」误判成「参数不支持」。
    """
    if not _json_mode_unsupported_status(exc):
        return False
    try:
        return param in exc.response.text
    except Exception:  # noqa: BLE001 - 拿不到响应体就当没点名
        return False


def _swap_max_tokens(payload: dict[str, Any]) -> dict[str, Any]:
    """新版 OpenAI 模型只认 max_completion_tokens，报错时会点名 max_tokens。"""
    alt = {k: v for k, v in payload.items() if k != "max_tokens"}
    alt["max_completion_tokens"] = payload["max_tokens"]
    return alt


# --------------------------------------------------------------- HTTP provider


class HttpAIProvider(AIProvider):
    name = "http"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str,
        api_format: str = DEFAULT_API_FORMAT,
        name: str = "http",
        label: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if api_format not in API_FORMATS:
            raise AIProviderError(f"不支持的 API 格式：{api_format}")
        self.api_format = api_format
        self.base_url = normalize_base_url(base_url, api_format)
        assert_public_http_url(self.base_url, resolve=False)
        self.api_key = api_key if api_key is not None else settings.ai_api_key
        self.model = model or settings.ai_model
        self.timeout = settings.ai_timeout_seconds
        self.max_tokens = settings.ai_max_tokens
        self.name = name
        self._label = label
        self._transport = transport

    @property
    def label(self) -> str:
        return self._label or self.model or self.name

    @property
    def signature(self) -> str:
        # 含格式、地址与 Key 指纹：换模型、换格式或换 Key 后旧缓存自动失效
        return ":".join(
            [
                self.name,
                self.api_format,
                self.base_url,
                self.model,
                secret_fingerprint(self.api_key or ""),
            ]
        )

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        return self._complete_json(
            system_prompt,
            user_prompt,
            schema,
            max_tokens=max_tokens,
            attempts=COMPLETE_ATTEMPTS,
        )

    def complete_json_fast(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        return self._complete_json(
            system_prompt,
            user_prompt,
            schema,
            max_tokens=max_tokens,
            attempts=1,
        )

    def _complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        *,
        max_tokens: int | None = None,
        attempts: int,
    ) -> dict[str, Any] | None:
        if not self.api_key:
            raise AIProviderError("模型 API Key 未配置")
        if not self.base_url:
            raise AIProviderError("模型 API 地址未配置")

        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        system = system_prompt.replace("{schema}", schema_text)

        last_error: Exception | None = None
        # 已知不认 json mode 的接入方直接跳过第一种 payload，省掉一次注定失败的往返
        skip_json_mode = self.signature in _json_mode_unsupported
        # 模型偶尔会返回非法 JSON，或服务端不支持某个请求参数，重试即可，不做无限重试。
        # 用可增长的列表而非一次性生成器：某个参数被点名拒绝时，据此补一个替换写法。
        pending = list(self._payload_variants(system, user_prompt, skip_json_mode, max_tokens))
        index = 0
        # 调用方可将预算降为一次，用于需要尽快得到首个结果的流式场景。
        attempts_left = attempts
        while index < len(pending) and attempts_left > 0:
            payload = pending[index]
            index += 1
            try:
                content = self._send(payload)
                data = _extract_json(content)
                return schema.model_validate(data).model_dump()
            except (
                httpx.HTTPError,
                KeyError,
                IndexError,
                TypeError,
                json.JSONDecodeError,
                ValidationError,
                AIProviderError,
            ) as exc:
                last_error = exc
                attempts_left -= 1
                if "response_format" in payload and _json_mode_unsupported_status(exc):
                    # 只有接入方明确拒绝该字段时才记住，避免把内容问题误判成能力问题。
                    # 注入 transport 的是测试替身，签名会彼此撞车，不参与记忆。
                    if self._transport is None:
                        _json_mode_unsupported.add(self.signature)
                # 新版 OpenAI 模型只认 max_completion_tokens，报错时会点名 max_tokens
                if "max_tokens" in payload and _rejects_param(exc, "max_tokens"):
                    alt = _swap_max_tokens(payload)
                    if alt not in pending:
                        pending.append(alt)
                # 临时故障与模型输出的随机抖动值得原地再试；其余失败换写法
                if attempts_left and (
                    _is_transient_failure(exc)
                    or isinstance(exc, (json.JSONDecodeError, ValidationError))
                ):
                    index -= 1
                    # 429/503 尊重服务商的 Retry-After：免费额度的服务商限流
                    # 往往要等好几秒，固定 0.5 秒的三次重试全都是白试，最后
                    # 整轮对话被打回离线规则引擎，看着就像「AI 时好时坏」。
                    time.sleep(
                        _backoff_seconds(
                            exc,
                            attempts - attempts_left,
                            COMPLETE_RETRY_DELAY,
                        )
                    )
                logger.warning("AI 调用失败（%s）：%s", self.api_format, exc)

        raise AIProviderError(_format_error(last_error))

    def _payload_variants(
        self,
        system: str,
        user: str,
        skip_json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """按接入格式生成请求体，第一个失败就换下一个。

        每种格式都带上 max_tokens：结构化回复只有几百 token，限长能挡住跑题的
        模型把一轮对话拖到超时，也省掉为无用输出付的等待。批量调用通过
        max_tokens 覆盖默认值——一次分析多句时输出成倍增长，套用单句的 1500
        上限会被截断成非法 JSON。
        """
        tokens = self.max_tokens if max_tokens is None else max_tokens
        if self.api_format == FORMAT_ANTHROPIC:
            yield {
                "model": self.model,
                "max_tokens": tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        elif self.api_format == FORMAT_GEMINI:
            yield {
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "systemInstruction": {"parts": [{"text": system}]},
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": tokens,
                },
            }
        elif self.api_format == FORMAT_OPENAI_RESPONSES:
            yield {
                "model": self.model,
                "instructions": system,
                "input": user,
                "max_output_tokens": tokens,
            }
        else:
            base = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.7,
                "max_tokens": tokens,
            }
            if not skip_json_mode:
                yield {**base, "response_format": {"type": "json_object"}}
            # 部分服务端不认 response_format，去掉后再试一次
            yield dict(base)

    def _request(
        self, payload: dict[str, Any], timeout: httpx.Timeout | float | None = None
    ) -> httpx.Response:
        """按 api_format 拼好地址与鉴权，发一次请求并校验状态码。

        系统代理（Windows 上来自注册表）没开或挂掉时，httpx 默认会走代理而连不上。
        第一次走共享连接池（带代理）失败、且属于代理类失败时，立刻换一个绕过系统
        代理的直连客户端再试一次——这正是「信息都对却连不上、多试几次又行了」
        的主要来源，回退一次往往就通了。
        """
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self.api_format == FORMAT_ANTHROPIC:
            url = f"{self.base_url}/v1/messages"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        elif self.api_format == FORMAT_GEMINI:
            model_id = self.model.removeprefix("models/")
            url = f"{self.base_url}/models/{model_id}:generateContent"
            params = {"key": self.api_key}
        elif self.api_format == FORMAT_OPENAI_RESPONSES:
            url = f"{self.base_url}/responses"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        else:
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}

        request_timeout = self.timeout if timeout is None else timeout
        if self._transport is None:
            assert_public_http_url(self.base_url)
        # 生产路径复用共享连接池；测试注入的 MockTransport 单独建客户端，用完即关
        owns_client = self._transport is not None
        if owns_client:
            client = httpx.Client(
                timeout=request_timeout,
                transport=self._transport,
                follow_redirects=False,
            )
            try:
                resp = client.post(
                    url,
                    json=payload,
                    headers=headers,
                    params=params,
                    timeout=request_timeout,
                    follow_redirects=False,
                )
                resp.raise_for_status()
            finally:
                client.close()
            return resp

        try:
            resp = _shared_client().post(
                url,
                json=payload,
                headers=headers,
                params=params,
                timeout=request_timeout,
                follow_redirects=False,
            )
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            if not _is_proxy_eligible_failure(exc):
                raise
            logger.warning(
                "AI 请求经系统代理失败（%s），回退直连重试一次", type(exc).__name__
            )
        # 回退：绕过系统代理直连一次。失败就抛回调用方，由它的重试逻辑处理。
        with httpx.Client(
            timeout=request_timeout, trust_env=False, follow_redirects=False
        ) as direct:
            resp = direct.post(
                url,
                json=payload,
                headers=headers,
                params=params,
                timeout=request_timeout,
                follow_redirects=False,
            )
            resp.raise_for_status()
        return resp

    def _send(self, payload: dict[str, Any]) -> str:
        return _parse_response(self.api_format, self._request(payload).json())

    # ------------------------------------------------------- 纯文本补全

    def _text_payload(self, system: str, user: str, tokens: int) -> dict[str, Any]:
        """纯文本请求体：不带 response_format、不带 JSON schema。"""
        if self.api_format == FORMAT_ANTHROPIC:
            return {
                "model": self.model,
                "max_tokens": tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        if self.api_format == FORMAT_GEMINI:
            return {
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "systemInstruction": {"parts": [{"text": system}]},
                "generationConfig": {"maxOutputTokens": tokens},
            }
        if self.api_format == FORMAT_OPENAI_RESPONSES:
            return {
                "model": self.model,
                "instructions": system,
                "input": user,
                "max_output_tokens": tokens,
            }
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
            "max_tokens": tokens,
        }

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        """一次性纯文本补全。比 complete_json 少了 JSON 解析与校验。"""
        if not self.api_key:
            raise AIProviderError("模型 API Key 未配置")
        if not self.base_url:
            raise AIProviderError("模型 API 地址未配置")

        tokens = max_tokens or self.max_tokens
        payload = self._text_payload(system_prompt, user_prompt, tokens)

        last_error: Exception | None = None
        attempts_left = COMPLETE_ATTEMPTS
        # max_tokens 被点名拒绝时换 max_completion_tokens，逻辑同 complete_json
        pending = [payload]
        index = 0
        while index < len(pending) and attempts_left > 0:
            current = pending[index]
            index += 1
            try:
                content = self._send(current)
                text = content.strip()
                if text:
                    return text
                # 空回复也算失败，重试
                last_error = ValueError("空回复")
                attempts_left -= 1
                if attempts_left and _is_transient_failure(last_error):
                    index -= 1
                    time.sleep(
                        _backoff_seconds(
                            last_error,
                            COMPLETE_ATTEMPTS - attempts_left,
                            COMPLETE_RETRY_DELAY,
                        )
                    )
            except (
                httpx.HTTPError,
                KeyError,
                IndexError,
                TypeError,
                AIProviderError,
            ) as exc:
                last_error = exc
                attempts_left -= 1
                if "max_tokens" in current and _rejects_param(exc, "max_tokens"):
                    alt = _swap_max_tokens(current)
                    if alt not in pending:
                        pending.append(alt)
                if attempts_left and _is_transient_failure(exc):
                    index -= 1
                    time.sleep(
                        _backoff_seconds(
                            exc,
                            COMPLETE_ATTEMPTS - attempts_left,
                            COMPLETE_RETRY_DELAY,
                        )
                    )
                logger.warning("AI 纯文本调用失败（%s）：%s", self.api_format, exc)

        raise AIProviderError(_format_error(last_error))

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """流式纯文本补全。

        OpenAI 兼容格式走 stream:true 的 SSE；Anthropic 也支持 stream:true；
        其它格式退回 complete_text 一次性返回（仍 yield 一次，调用方无感知差异）。

        流式的好处是首 token 就能往前端推，用户不必等整句生成完才看到 AI
        开口——这是「AI 回复太慢」的主要体感来源。JSON 模式做不到流式：必须
        等整包 JSON 写完才能解析，所以回复这条路刻意不走 JSON。
        """
        if not self.api_key:
            raise AIProviderError("模型 API Key 未配置")
        if not self.base_url:
            raise AIProviderError("模型 API 地址未配置")

        tokens = max_tokens or self.max_tokens
        payload = self._text_payload(system_prompt, user_prompt, tokens)

        # OpenAI 与 Anthropic 都支持 stream:true，走真正的流式
        if self.api_format in (FORMAT_OPENAI, FORMAT_ANTHROPIC):
            payload = {**payload, "stream": True}
            got_any = False
            try:
                for chunk in self._stream_send(payload):
                    if chunk:
                        got_any = True
                        yield chunk
                return
            except httpx.HTTPError as exc:
                # 已经吐过内容的流式失败不能退回一次性：会导致前端收到重复文本。
                # 只在建连阶段就失败（一个 chunk 都没收到）时才退回。
                if got_any:
                    logger.warning("流式补全中途失败（已收到部分内容）：%s", exc)
                    return
                if _is_transient_failure(exc) or _json_mode_unsupported_status(exc):
                    logger.warning("流式补全建连失败，退回一次性：%s", exc)
                else:
                    raise

        # 其它格式 / 流式建连失败：一次性返回
        yield self.complete_text(system_prompt, user_prompt, max_tokens=max_tokens)

    def _stream_send(self, payload: dict[str, Any]) -> Iterator[str]:
        """发一个 stream:true 请求，逐块 yield 文本 delta。"""
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self.api_format == FORMAT_ANTHROPIC:
            url = f"{self.base_url}/v1/messages"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        else:
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}

        # 流式请求也复用长连接：每轮对话都要走一次，为它单独建 client 等于
        # 每轮都重做一次 DNS + TLS 握手（中转/海外服务上就是几百毫秒）。
        timeout = httpx.Timeout(self.timeout, connect=STREAM_CONNECT_TIMEOUT)
        if self._transport is None:
            assert_public_http_url(self.base_url)
        owns_client = self._transport is not None
        client = (
            httpx.Client(
                timeout=timeout, transport=self._transport, follow_redirects=False
            )
            if owns_client
            else _shared_stream_client()
        )
        try:
            with client.stream(
                "POST", url, json=payload, headers=headers, params=params, timeout=timeout
            ) as resp:
                resp.raise_for_status()
                for chunk in _iter_stream_chunks(
                    resp, self.api_format
                ):
                    if chunk:
                        yield chunk
        finally:
            if owns_client:
                client.close()

    # ------------------------------------------------------------- 语音转写

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.webm",
        content_type: str = "audio/webm",
        language: str = "en",
    ) -> str | None:
        """把一段录音丢给用户自己填的那套 API 转成文本。

        只用用户当前选中的地址、Key 和模型名，不另挑一份转写模型名单——
        否则录音会打到用户没填过的模型上，费用和结果都对不上。

        只有 OpenAI 兼容格式有 /audio/transcriptions：Anthropic / Gemini /
        Responses，以及对话模型本身不认这个端点时，返回 None，由调用方弹窗
        告诉用户换模型或改用本地识别。
        """
        if self.api_format != FORMAT_OPENAI or not self.api_key or not self.base_url:
            return None
        if not (self.model or "").strip():
            return None

        url = f"{self.base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        # 让模型补上标点与大小写。个别服务商不认 prompt 字段并回 400，
        # 那种 400 会点名 prompt，去掉再试一次即可。
        data = {
            "model": self.model,
            "language": language,
            "response_format": "json",
            "prompt": _STT_PROMPT,
        }
        while True:
            try:
                return self._post_audio(url, headers, data, audio, filename, content_type)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if "prompt" in data and _rejects_param(exc, "prompt"):
                    data = {k: v for k, v in data.items() if k != "prompt"}
                    continue
                if status in _STT_MODEL_REJECT_STATUS:
                    # 用户填的这个模型不认转写端点：这是能力问题，不是这次失败
                    return None
                raise AIProviderError(_format_error(exc)) from exc
            except httpx.HTTPError as exc:
                # 超时 / 断连 / 限流：属于临时故障，让调用方提示重试
                raise AIProviderError(_format_error(exc)) from exc

    def _post_audio(
        self,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        audio: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        """发一次 multipart 转写请求，返回文本（可能是空串）。

        和 `_request` 一样带一次「绕过系统代理直连」的回退：本机装了代理但
        代理没把上传放行时，走代理的请求会一直读到超时，而直连是通的。
        """
        files = {"file": (filename, audio, content_type or "application/octet-stream")}
        timeout = httpx.Timeout(STT_TIMEOUT_SECONDS, connect=STREAM_CONNECT_TIMEOUT)
        if self._transport is None:
            assert_public_http_url(self.base_url)
        owns_client = self._transport is not None
        if owns_client:
            client = httpx.Client(
                timeout=timeout, transport=self._transport, follow_redirects=False
            )
            try:
                response = client.post(
                    url,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=timeout,
                    follow_redirects=False,
                )
                response.raise_for_status()
                return _extract_transcript(response, data.get("language", "en"))
            finally:
                client.close()

        try:
            response = _shared_client().post(
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            return _extract_transcript(response, data.get("language", "en"))
        except httpx.HTTPError as exc:
            if not _is_proxy_eligible_failure(exc):
                raise
            logger.warning(
                "转写请求经系统代理失败（%s），回退直连重试一次", type(exc).__name__
            )

        with httpx.Client(
            timeout=timeout, trust_env=False, follow_redirects=False
        ) as direct:
            response = direct.post(
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            return _extract_transcript(response, data.get("language", "en"))

    # ------------------------------------------------------------- 探活
    def _probe_payloads(self) -> Iterator[dict[str, Any]]:
        """探活请求体：最短的一次往返，不要求任何结构化输出。

        不带 response_format / temperature，也不带 system prompt——模型答什么都
        无所谓，只要能拿到 2xx，就说明地址、Key、模型名三样都对。
        """
        if self.api_format == FORMAT_ANTHROPIC:
            yield {
                "model": self.model,
                "max_tokens": PROBE_MAX_TOKENS,
                "messages": [{"role": "user", "content": PROBE_USER_TEXT}],
            }
        elif self.api_format == FORMAT_GEMINI:
            yield {
                "contents": [{"role": "user", "parts": [{"text": PROBE_USER_TEXT}]}],
                "generationConfig": {"maxOutputTokens": PROBE_MAX_TOKENS},
            }
        elif self.api_format == FORMAT_OPENAI_RESPONSES:
            yield {
                "model": self.model,
                "input": PROBE_USER_TEXT,
                "max_output_tokens": PROBE_MAX_TOKENS,
            }
        else:
            yield {
                "model": self.model,
                "messages": [{"role": "user", "content": PROBE_USER_TEXT}],
                "max_tokens": PROBE_MAX_TOKENS,
            }

    def probe(self) -> ProbeOutcome:
        """验证这组凭据能不能用：只看这次往返成不成功。

        网络抖动与服务端 5xx/429 会重试几次，429 尊重 Retry-After 并带抖动；
        鉴权、地址、模型名这类确定性错误立刻返回，并给出可操作的中文说明。
        读超时是另一回事：请求已经被服务端收下了，说明地址与 Key 没问题，
        只是模型慢——这时去 GET /models 确认凭据，然后给一个 warn 而不是错误，
        否则思考型模型会让「测试连接」看起来永远在失败。
        """
        pending = list(self._probe_payloads())
        index = 0
        last_error: Exception | None = None
        deadline = time.monotonic() + PROBE_TOTAL_BUDGET_SECONDS
        timeout = httpx.Timeout(
            PROBE_TIMEOUT_SECONDS, connect=PROBE_CONNECT_TIMEOUT_SECONDS
        )
        while index < len(pending):
            payload = pending[index]
            index += 1
            for attempt in range(1, PROBE_ATTEMPTS + 1):
                if time.monotonic() >= deadline:
                    logger.info("探活预算用完，按最后一次失败收尾：%s", last_error)
                    return self._failure_outcome(last_error)
                if attempt > 1:
                    time.sleep(_backoff_seconds(last_error, attempt - 1))
                try:
                    self._request(payload, timeout=timeout)
                    return ProbeOutcome(
                        True, f"连接成功，{self.model} 响应正常", status="ok"
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                    # 服务端点名拒绝 max_tokens：换成 max_completion_tokens 再试
                    if "max_tokens" in payload and _rejects_param(exc, "max_tokens"):
                        alt = _swap_max_tokens(payload)
                        if alt not in pending:
                            pending.append(alt)
                    # 读超时：请求已被收下，重发大概率还是等这么久，直接判「模型慢」
                    if isinstance(exc, httpx.TimeoutException) and not isinstance(
                        exc, httpx.ConnectTimeout
                    ):
                        return self._slow_model_outcome()
                    # 429/5xx 这类临时故障原地退避重试；鉴权/地址错误立刻换写法
                    if not _is_transient_failure(exc):
                        if _is_proxy_eligible_failure(exc):
                            # 代理类失败：_request 内部已回退直连试过一次仍失败，
                            # 再原地重试一次意义不大，换下一种写法。
                            pass
                        break
                    logger.warning(
                        "探活失败（%s，第 %d 次），退避重试：%s",
                        self.api_format,
                        attempt,
                        exc,
                    )
        return self._failure_outcome(last_error)

    # ---------------------------------------------------- 探活结果的三种收尾

    def _failure_outcome(self, exc: Exception | None) -> ProbeOutcome:
        """确定性失败：给出能照着改的说明，并顺手带上真实可用的模型名。"""
        message = _probe_error_message(exc, self)
        suggested: list[str] = []
        if _looks_like_model_problem(exc):
            total, sample = self._available_models()
            if sample:
                suggested = sample
                shown = "、".join(sample[:5])
                message = (
                    f"{message}；这条地址下有 {total} 个可用模型，例如 {shown}"
                    "（点「自动获取模型列表」可以直接挑一个）"
                )
        return ProbeOutcome(False, message, status="fail", suggested_models=suggested)

    def _slow_model_outcome(self) -> ProbeOutcome:
        """读超时：地址与 Key 另有快路径可以确认，模型慢不该报成错误。"""
        status = _credential_status(
            base_url=self.base_url,
            api_key=self.api_key or "",
            api_format=self.api_format,
        )
        if status == "invalid":
            return ProbeOutcome(
                False,
                "连接失败（HTTP 401）：API Key 不被接受，确认是否复制完整、是否已过期",
                status="fail",
            )
        seconds = f"{PROBE_TIMEOUT_SECONDS:.0f}"
        if status == "ok":
            note = (
                f"地址与 Key 已通过校验，但 {self.model} 在 {seconds} 秒内没有返回内容："
                "多半是模型在排队，或这类「思考型」模型本来就要想很久。"
                "可以稍后再测，或换一个更快的模型。"
            )
        else:
            note = (
                f"服务端已收下请求，但 {seconds} 秒内没有返回内容：可能是模型排队/太慢，"
                "也可能是本地网络（含系统代理）不稳；地址与 Key 本身没有被服务商拒绝。"
            )
        return ProbeOutcome(True, note, status="warn")

    def _available_models(self, limit: int = 8) -> tuple[int, list[str]]:
        """该地址下真实存在的模型名，失败时用来告诉用户模型名该写什么。"""
        try:
            models = list_models(
                base_url=self.base_url,
                api_key=self.api_key or "",
                api_format=self.api_format,
                timeout=PROBE_CREDENTIAL_TIMEOUT_SECONDS,
            )
        except (AIProviderError, httpx.HTTPError, ValueError):
            return 0, []
        return len(models), _chat_like_models(models, limit)


# --------------------------------------------------------------- 响应解析


def _iter_stream_chunks(
    resp: httpx.Response, api_format: str
) -> Iterator[str]:
    """解析流式 SSE 响应，逐块 yield 文本 delta。

    OpenAI 兼容格式：每行 `data: {...}`，delta 在 choices[0].delta.content。
    结束标记 `data: [DONE]`。
    Anthropic 格式：event 类型 content_block_delta，delta.text。
    """
    for line in resp.iter_lines():
        if not line:
            continue
        # OpenAI: data: {...}
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                return
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if api_format == FORMAT_ANTHROPIC:
                # Anthropic: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield text
            else:
                # OpenAI: {"choices":[{"delta":{"content":"..."}}]}
                choices = data.get("choices") or []
                if choices:
                    content = choices[0].get("delta", {}).get("content")
                    if content:
                        yield content
        elif api_format == FORMAT_ANTHROPIC and line.startswith("event:"):
            # Anthropic 的 event 行，data 行紧随其后，上面已处理
            continue


def _parse_response(api_format: str, data: dict[str, Any]) -> str:
    if api_format == FORMAT_ANTHROPIC:
        return data["content"][0]["text"]
    if api_format == FORMAT_GEMINI:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    if api_format == FORMAT_OPENAI_RESPONSES:
        if isinstance(data.get("output_text"), str) and data["output_text"]:
            return data["output_text"]
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("text"):
                    return part["text"]
        raise KeyError("output_text")
    return _openai_message_content(data["choices"][0]["message"])


def _openai_message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # 新接口把 content 拆成 parts 列表
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    raise KeyError("content")


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("no json object found", text, 0)
    return json.loads(text[start : end + 1])


def _format_error(exc: Exception | None) -> str:
    if exc is None:
        return "模型调用失败"
    text = str(exc).strip()
    return f"模型调用失败：{text}" if text else "模型调用失败"


# --------------------------------------------------------------- 语音转写

# 明确要求标点与大小写：这是用户最在意的一点（浏览器自带的识别就没有）。
# whisper 系默认就会断句，写进 prompt 对不默认的服务商（SenseVoice 等）有用。
_STT_PROMPT = (
    "Transcribe the English speech verbatim, with correct punctuation, "
    "sentence casing and paragraph breaks."
)

# 服务商回这些状态码，说明用户填的这个模型不认转写端点。
# 400/404 最常见，422 是少数网关对未知模型的叫法。
_STT_MODEL_REJECT_STATUS = (400, 404, 422)

# signature -> 这个模型能不能转写（True/False）。没探测过的不在表里。
_stt_support_cache: dict[str, bool] = {}
_stt_cache_lock = threading.Lock()


def _silent_wav(seconds: float = STT_PROBE_SECONDS, rate: int = 16000) -> bytes:
    """造一段 16k 单声道静音 WAV，用于提前探出可用的转写模型。

    探测只关心这次调用成不成功（模型名/端点认不认），不关心转写内容，
    所以用静音最省事：不动麦克风，也不产生任何可听的输出。
    """
    data = b"\x00\x00" * int(seconds * rate)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        1,  # 单声道
        rate,
        rate * 2,  # 字节率
        2,  # 块对齐
        16,  # 位深
        b"data",
        len(data),
    )
    return header + data


def _extract_transcript(response: httpx.Response, language: str = "en") -> str:
    """从转写响应里取文本。

    OpenAI 兼容返回 `{"text": "..."}`；个别服务商（或 response_format=text）
    直接回纯文本。两种都认。取出来的文本还会顺手清一遍，见 `_clean_transcript`。
    """
    body = response.text or ""
    stripped = body.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return _clean_transcript(stripped, language)
        text = data.get("text")
        return _clean_transcript(text, language) if isinstance(text, str) else ""
    return _clean_transcript(stripped, language)


# 表情与其他非文字符号：转写结果里常见，输入框里不需要
_NON_WORD_SYMBOLS = re.compile(
    "[\U0001f000-\U0001faff\u2190-\u21ff\u2300-\u27bf\ufe0f\U0001f1e6-\U0001f1ff]"
)
# 中日韩文字与全角标点：中文口音、听不清的音频、双语模型都可能吐出来，
# 而我们要的是英文句子
_CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")


def _clean_transcript(text: str, language: str = "en") -> str:
    """把转写结果整成能直接放进输入框的英文。

    转写模型（尤其 Qwen3-ASR 这类中文为主的双语模型）听不清时会输出中文。
    英文场景下这种结果一点用都没有，反而让人困惑，所以先剥符号、再剥中日韩
    文字；剥完剩下不到一半的，说明这句基本是「听」成中文了，直接返回空串
    （前端会提示这句没听清，让用户重说），别往输入框里塞一句莫名其妙的中文。
    """
    cleaned = " ".join(_NON_WORD_SYMBOLS.sub("", text).split())
    if not language.lower().startswith("en"):
        return cleaned

    ascii_only = " ".join(_CJK.sub(" ", cleaned).split())
    if len(ascii_only) * 2 < len(cleaned):
        return ""
    return ascii_only


def detect_stt_model(provider: AIProvider, *, force: bool = False) -> str | None:
    """提前问出用户当前这个模型认不认转写。

    走的就是真实转写那条路（一段静音、用户自己的模型名）。认，就记住并返回
    模型名；不认，记一笔 False 并返回 None，前端据此弹窗。调用方应当把它放在
    后台线程里：冷启动的服务商首次可能要好几秒。
    """
    if provider.is_mock or not isinstance(provider, HttpAIProvider):
        return None
    if provider.api_format != FORMAT_OPENAI or not provider.api_key or not provider.base_url:
        return None
    model = (provider.model or "").strip()
    if not model:
        return None

    if not force:
        with _stt_cache_lock:
            known = _stt_support_cache.get(provider.signature)
        if known is True:
            return model
        if known is False:
            return None

    try:
        text = provider.transcribe(
            _silent_wav(), filename="probe.wav", content_type="audio/wav"
        )
    except (AIProviderError, httpx.HTTPError) as exc:
        # 超时、限流这类临时故障不记成「不支持」，下次按麦克风再试
        logger.info("语音转写探测失败（%s）：%s", provider.label, exc)
        return None

    with _stt_cache_lock:
        _stt_support_cache[provider.signature] = text is not None
    return model if text is not None else None


def stt_status(provider: AIProvider) -> dict:
    """给前端的语音输入能力说明：能不能用、用的是哪个模型。"""
    if provider.is_mock or not isinstance(provider, HttpAIProvider):
        return {"available": False, "model": "", "reason": "未配置 AI 模型"}
    if provider.api_format != FORMAT_OPENAI:
        return {
            "available": False,
            "model": "",
            "reason": f"{provider.api_format} 格式不支持语音转写",
        }
    if not provider.api_key or not provider.base_url:
        return {"available": False, "model": "", "reason": "模型凭据不完整"}
    model = (provider.model or "").strip()
    with _stt_cache_lock:
        known = _stt_support_cache.get(provider.signature)
    if known is False:
        return {
            "available": False,
            "model": model,
            "reason": f"你配置的模型 {model} 不支持语音转写",
        }
    return {"available": True, "model": model, "reason": ""}


def reset_stt_cache() -> None:
    """测试用：清空转写能力探测缓存。"""
    with _stt_cache_lock:
        _stt_support_cache.clear()


# --------------------------------------------------------------- 模型列表


def _extract_model_ids(api_format: str, data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    if api_format == FORMAT_GEMINI:
        for item in data.get("models", []) or []:
            name = item.get("name", "")
            if name:
                ids.append(name.split("/")[-1])
    else:
        for item in data.get("data", []) or []:
            model_id = item.get("id", "")
            if model_id:
                ids.append(model_id)
    return ids


# 明显不能用来聊天的模型名片段：向量、重排、语音、画图。失败提示里推荐模型时
# 排掉它们——硅基流动的模型列表按字母序排，前五个全是 BAAI/bge-* 向量模型。
_NON_CHAT_MODEL_HINTS = (
    "embed",
    "bge",  # BAAI 的向量模型家族（bge-large/m3…）
    "gte",  # 阿里的向量模型家族
    "rerank",
    "asr",
    "tts",
    "whisper",
    "moderation",
    "ocr",
    "sd3",
    "flux",
    "blip",
    "voice",
    "audio",
)
# 常见的对话模型名特征，排前面显示
_CHAT_MODEL_HINTS = (
    "chat",
    "instruct",
    "flash",
    "deepseek",
    "qwen",
    "glm",
    "kimi",
    "minimax",
    "gpt",
    "claude",
    "gemini",
    "grok",
    "llama",
    "mistral",
)


def _is_chat_like(name: str) -> bool:
    """像不像一个能聊天的模型：没有向量/重排/语音的特征，且有对话模型的常见特征。"""
    lowered = name.lower()
    if any(hint in lowered for hint in _NON_CHAT_MODEL_HINTS):
        return False
    return any(hint in lowered for hint in _CHAT_MODEL_HINTS)


def _chat_like_models(models: list[str], limit: int) -> list[str]:
    """从模型列表里挑出像对话模型的（排掉向量/重排/语音），供失败提示里推荐。"""
    kept = [name for name in models if not _is_non_chat(name)]
    preferred = [name for name in kept if _is_chat_like(name)]
    rest = [name for name in kept if name not in preferred]
    return (preferred + rest)[:limit]


def _is_non_chat(name: str) -> bool:
    return any(hint in name.lower() for hint in _NON_CHAT_MODEL_HINTS)


def chat_first_models(models: list[str]) -> list[str]:
    """把像对话模型的排前面，一个都不丢。

    「自动获取模型列表」拿到的是服务商原样顺序：硅基流动按字母序排，头八个
    全是 BAAI/bge-* 向量、重排、语音模型，想挑个能聊天的得往下翻半天。
    """
    preferred = [name for name in models if _is_chat_like(name)]
    rest = [name for name in models if name not in preferred]
    return preferred + rest


def _models_endpoint(
    base: str, api_key: str, api_format: str
) -> tuple[str, dict[str, str], dict[str, str]]:
    """模型列表的地址与鉴权（OpenAI 兼容 / Anthropic / Gemini 各一套）。"""
    if api_format == FORMAT_ANTHROPIC:
        return (
            f"{base}/v1/models",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {},
        )
    if api_format == FORMAT_GEMINI:
        return f"{base}/models", {}, {"key": api_key}
    return f"{base}/models", {"Authorization": f"Bearer {api_key}"}, {}


def _credential_status(*, base_url: str, api_key: str, api_format: str) -> str:
    """只验「地址 + Key」能不能过：GET /models，不惊动模型。

    给探活读超时用：模型慢半分钟不代表凭据有问题，而 /models 是秒级的。
    返回 ok（服务商认这把 Key）/ invalid（服务商明确说 Key 不对）/ unknown
    （这个接入方没有模型列表接口，或网络这次也不通，判断不了）。
    """
    if not api_key:
        return "invalid"
    try:
        base = normalize_base_url(base_url, api_format)
        assert_public_http_url(base)
    except AIProviderError:
        return "unknown"
    if not base:
        return "unknown"

    url, headers, params = _models_endpoint(base, api_key, api_format)
    timeout = httpx.Timeout(
        PROBE_CREDENTIAL_TIMEOUT_SECONDS, connect=PROBE_CONNECT_TIMEOUT_SECONDS
    )

    def _do(client: httpx.Client) -> httpx.Response:
        return client.get(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
            follow_redirects=False,
        )

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            try:
                resp = _do(client)
            except httpx.HTTPError as exc:
                if not _is_proxy_eligible_failure(exc):
                    raise
                with httpx.Client(
                    timeout=timeout, trust_env=False, follow_redirects=False
                ) as direct:
                    resp = _do(direct)
    except httpx.HTTPError:
        return "unknown"

    if resp.status_code in (401, 403):
        return "invalid"
    return "ok" if resp.status_code < 400 else "unknown"


def list_models(
    *,
    base_url: str,
    api_key: str,
    api_format: str = DEFAULT_API_FORMAT,
    transport: httpx.BaseTransport | None = None,
    timeout: float | None = None,
) -> list[str]:
    """拉取该接入地址下可用的模型名，供前端下拉选择。

    多数服务兼容 OpenAI 的 GET /v1/models；Anthropic 与 Gemini 走各自端点。
    """
    if not api_key:
        raise AIProviderError("模型 API Key 未配置")
    if api_format not in API_FORMATS:
        raise AIProviderError(f"不支持的 API 格式：{api_format}")

    base = normalize_base_url(base_url, api_format)
    if not base:
        raise AIProviderError("模型 API 地址未配置")

    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    url, headers, params = _models_endpoint(base, api_key, api_format)

    assert_public_http_url(base, resolve=transport is None)

    def _do(client: httpx.Client) -> httpx.Response:
        resp = client.get(url, headers=headers, params=params, follow_redirects=False)
        resp.raise_for_status()
        return resp

    try:
        with httpx.Client(
            timeout=timeout or settings.ai_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        ) as client:
            try:
                resp = _do(client)
            except httpx.HTTPError as exc:
                if transport is not None or not _is_proxy_eligible_failure(exc):
                    raise
                logger.warning(
                    "拉取模型列表经系统代理失败（%s），回退直连重试一次",
                    type(exc).__name__,
                )
                with httpx.Client(
                    timeout=timeout or settings.ai_timeout_seconds,
                    trust_env=False,
                    follow_redirects=False,
                ) as direct:
                    resp = _do(direct)
        data = resp.json()
    except httpx.HTTPError as exc:
        raise AIProviderError(_format_error(exc)) from exc
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"模型列表返回的不是合法 JSON：{exc}") from exc

    return sorted(set(_extract_model_ids(api_format, data)))


# --------------------------------------------------------------- 探活与兜底


def _looks_like_model_problem(exc: Exception | None) -> bool:
    """这次失败像不像「模型名不对」。

    是的话，失败文案里会补上该地址下真实存在的模型名——早先用户看到
    「HTTP 400 服务商认为请求不合法」，只能自己猜模型名该怎么写。
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    # 404 分不清是地址错还是模型错，两种情况下列一遍可用模型都有帮助
    if status == 404:
        return True
    if status not in (400, 422):
        return False
    try:
        return "model" in exc.response.text.lower()
    except Exception:  # noqa: BLE001 - 读不到响应体就当不是模型问题
        return False


def _is_transient_failure(exc: Exception) -> bool:
    """这次失败值不值得重试。

    网络抖动、连接超时、服务端 5xx 算临时；408（请求超时）与 429（限流）
    也是「等一下就好」的临时故障——尤其 429，免费额度的服务商（硅基流动等）
    很常见，正是「信息都对却报错、多试几次又行了」的主要来源。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in (408, 429) or status >= 500
    return isinstance(exc, _TRANSIENT_TRANSPORT_ERRORS)


def _response_snippet(resp: httpx.Response, limit: int = 160) -> str:
    """把服务商的错误响应压成一行，让用户直接看到它到底在抱怨什么。"""
    try:
        raw = resp.text
    except Exception:  # noqa: BLE001 - 响应体拿不到就不展示
        return ""
    if not raw or not raw.strip():
        return ""
    text = raw.strip()
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 - 不是 JSON 就原样截断
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            text = str(error["message"])
        elif isinstance(error, str):
            text = error
        elif data.get("message"):
            text = str(data["message"])
    text = " ".join(text.split())
    if not text:
        return ""
    return text[:limit] + ("…" if len(text) > limit else "")


def _proxy_hint() -> str:
    """连不上时先怀疑本机代理。

    系统里配了代理（Windows 上来自 IE 设置/注册表）时，httpx 默认会先绕一圈
    代理，代理没开或不稳就会表现为「信息都对却连不上」。这里把它点出来。
    """
    proxy = _system_proxy_url()
    if proxy:
        return (
            f"本机配置了系统代理 {proxy}，AI 请求会先经过它；"
            "代理没开或不稳定时就会连不上，可在系统代理里把该地址设为直连例外"
        )
    return "检查网络是否通，或确认服务商地址是否写对"


def _system_proxy_url() -> str:
    """本机配置的系统代理（Windows 上来自 IE/注册表，httpx 默认会读）。"""
    try:
        proxies = getproxies()
    except Exception:  # noqa: BLE001 - 拿不到代理配置就当没有
        return ""
    return proxies.get("https") or proxies.get("http") or ""


def _is_proxy_eligible_failure(exc: Exception) -> bool:
    """这次失败要不要换「直连（绕过系统代理）」再试一次。

    只在配了系统代理时才回退直连——没配代理时直连本来就是默认路径，再试一遍
    没意义。ProxyError 一定是代理本身的问题，回退；ConnectError/ConnectTimeout
    在配了代理时也很可能是代理没开/挂了，回退一次直连往往就通了。这正是
    「信息都对却连不上、多试几次又行了」的主要来源。
    """
    if isinstance(exc, httpx.ProxyError):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return bool(_system_proxy_url())
    return False


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """解析 Retry-After：整数秒或 HTTP-date；解析失败返回 None。"""
    value = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return max(float(int(text)), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delay = (when - datetime.now(timezone.utc)).total_seconds()
    return max(delay, 0.0)


def _rate_limit_delay(
    resp: httpx.Response, attempt: int, base: float = PROBE_RETRY_DELAY
) -> float:
    """429/503 的退避时长：优先 Retry-After，否则指数 + 抖动，封顶。"""
    asked = _retry_after_seconds(resp)
    if asked is not None:
        return min(max(asked, 0.0), PROBE_RATE_LIMIT_CAP)
    delay = base * (2 ** (attempt - 1))
    jitter = random.uniform(0, base)
    return min(delay + jitter, PROBE_RATE_LIMIT_CAP)


def _backoff_seconds(
    exc: Exception | None, attempt: int, base: float = PROBE_RETRY_DELAY
) -> float:
    """根据上次失败给重试前的等待时长。

    429/503 用限流退避（尊重 Retry-After）；其它临时故障用线性退避即可，
    不必太长——探活按钮本来就想要「按一下、自己扛过去」的体验。

    base 是退避基数：探活用 PROBE_RETRY_DELAY，业务调用传 COMPLETE_RETRY_DELAY。
    """
    if (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (429, 503)
        and exc.response is not None
    ):
        return _rate_limit_delay(exc.response, attempt, base)
    return base * attempt


def _probe_error_message(exc: Exception | None, provider: HttpAIProvider) -> str:
    """把探活失败翻译成用户能照着改的中文说明。"""
    if exc is None:
        return "连接失败：没有收到任何响应"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        hint = _PROBE_STATUS_HINTS.get(status, "服务商返回了错误状态码")
        message = f"连接失败（HTTP {status}）：{hint}"
        detail = _response_snippet(exc.response)
        if detail:
            message = f"{message}；服务商说：{detail}"
        return message
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError)):
        return f"连不上 {urlparse(provider.base_url).netloc}：{_proxy_hint()}"
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"已连上 {urlparse(provider.base_url).netloc}，但等响应超过 "
            f"{PROBE_TIMEOUT_SECONDS:.0f} 秒：这个模型这次太慢（思考型模型或排队），"
            "稍后再测或换一个更快的模型"
        )
    if isinstance(exc, httpx.HTTPError):
        return f"连接被中断：{exc}"
    return f"连接失败：{exc}"


def probe_provider(provider: AIProvider) -> tuple[bool, str]:
    """兼容旧签名：只要「成功与否 + 文案」。"""
    outcome = probe_provider_detail(provider)
    return outcome.success, outcome.message


def probe_provider_detail(provider: AIProvider) -> ProbeOutcome:
    """验证接入信息是否可用，供「测试连接」按钮调用。

    HttpAIProvider 只做一次最小往返，不要求模型返回符合业务 Schema 的内容，
    因此结果稳定可复现；Mock 之外的自定义 provider 退回一次完整调用。
    返回三档结论（ok / warn / fail），见 ProbeOutcome。
    """
    if provider.is_mock:
        return ProbeOutcome(True, "当前离线模式，无需凭据即可运行", status="ok")

    if isinstance(provider, HttpAIProvider):
        if not provider.api_key:
            return ProbeOutcome(False, "还没有填 API Key", status="fail")
        if not provider.base_url:
            return ProbeOutcome(False, "还没有填 Base URL", status="fail")
        return provider.probe()

    from app.ai.schemas import WordExplanation

    try:
        provider.complete_json(
            "Return a JSON object describing the word. {schema}",
            "Word: hello",
            WordExplanation,
        )
        return ProbeOutcome(True, "连接成功", status="ok")
    except AIProviderError as exc:
        return ProbeOutcome(False, str(exc), status="fail")
    except Exception as exc:  # noqa: BLE001 - 网络异常也归为连接失败
        return ProbeOutcome(False, f"连接失败：{exc}", status="fail")


_provider: AIProvider | None = None


def get_provider() -> AIProvider:
    """环境变量兜底 provider，也是没有用户级配置时的站点基线。"""
    global _provider
    if _provider is None:
        if settings.ai_provider == "openai" and settings.ai_api_key:
            try:
                _provider = HttpAIProvider(
                    base_url=settings.ai_base_url,
                    api_key=settings.ai_api_key,
                    model=settings.ai_model,
                    api_format=getattr(settings, "ai_api_format", DEFAULT_API_FORMAT),
                    name="env",
                    label=settings.ai_model,
                )
            except AIProviderError as exc:
                # 环境变量里的地址填坏了：退回离线规则引擎，而不是让每个
                # 请求都 500——兜底这一层不该成为新的故障点。
                logger.error("站点默认模型地址不可用（%s）：%s", settings.ai_base_url, exc)
        if _provider is None:
            _provider = MockAIProvider()
    return _provider


def reset_provider() -> None:
    """测试用：清空缓存的 provider。"""
    global _provider
    _provider = None
