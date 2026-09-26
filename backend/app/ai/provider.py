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

_STRIP_SUFFIXES = ("/chat/completions", "/responses", "/messages", "/models")

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
    pass


@dataclass
class ProbeOutcome:

    success: bool
    message: str
    status: str = "ok"
    suggested_models: list[str] = field(default_factory=list)


STREAM_CONNECT_TIMEOUT = 10.0

STT_PROBE_SECONDS = 0.8
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
        return self.name

    @property
    def label(self) -> str:
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
        pass

    def complete_json_fast(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        return self.complete_json(system_prompt, user_prompt, schema)

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        raise AIProviderError("当前 provider 不支持纯文本补全")

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        yield self.complete_text(system_prompt, user_prompt, max_tokens=max_tokens)

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.webm",
        content_type: str = "audio/webm",
        language: str = "en",
    ) -> str | None:
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
        return None

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        return ""

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.webm",
        content_type: str = "audio/webm",
        language: str = "en",
    ) -> str | None:
        return None


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
    raw = _ensure_scheme(raw)
    if not raw:
        return ""
    if re.search(r"\s", raw):
        raise AIProviderError("Base URL 里有空格，检查一下是不是复制时带进了多余字符")
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
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


_shared_client_instance: httpx.Client | None = None
_shared_client_lock = threading.Lock()

_json_mode_unsupported: set[str] = set()


def _shared_client() -> httpx.Client:
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
    global _shared_client_instance, _shared_stream_client_instance
    if _shared_client_instance is not None:
        _shared_client_instance.close()
        _shared_client_instance = None
    if _shared_stream_client_instance is not None:
        _shared_stream_client_instance.close()
        _shared_stream_client_instance = None


_shared_stream_client_instance: httpx.Client | None = None


def _shared_stream_client() -> httpx.Client:
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
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (400, 404, 415, 422)
    )


def _rejects_param(exc: Exception, param: str) -> bool:
    if not _json_mode_unsupported_status(exc):
        return False
    try:
        return param in exc.response.text
    except Exception:  # noqa: BLE001 - 拿不到响应体就当没点名
        return False


def _swap_max_tokens(payload: dict[str, Any]) -> dict[str, Any]:
    alt = {k: v for k, v in payload.items() if k != "max_tokens"}
    alt["max_completion_tokens"] = payload["max_tokens"]
    return alt


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
        skip_json_mode = self.signature in _json_mode_unsupported
        pending = list(self._payload_variants(system, user_prompt, skip_json_mode, max_tokens))
        index = 0
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
                    if self._transport is None:
                        _json_mode_unsupported.add(self.signature)
                if "max_tokens" in payload and _rejects_param(exc, "max_tokens"):
                    alt = _swap_max_tokens(payload)
                    if alt not in pending:
                        pending.append(alt)
                if attempts_left and (
                    _is_transient_failure(exc)
                    or isinstance(exc, (json.JSONDecodeError, ValidationError))
                ):
                    index -= 1
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
            yield dict(base)

    def _request(
        self, payload: dict[str, Any], timeout: httpx.Timeout | float | None = None
    ) -> httpx.Response:
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


    def _text_payload(self, system: str, user: str, tokens: int) -> dict[str, Any]:
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
        if not self.api_key:
            raise AIProviderError("模型 API Key 未配置")
        if not self.base_url:
            raise AIProviderError("模型 API 地址未配置")

        tokens = max_tokens or self.max_tokens
        payload = self._text_payload(system_prompt, user_prompt, tokens)

        last_error: Exception | None = None
        attempts_left = COMPLETE_ATTEMPTS
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
        if not self.api_key:
            raise AIProviderError("模型 API Key 未配置")
        if not self.base_url:
            raise AIProviderError("模型 API 地址未配置")

        tokens = max_tokens or self.max_tokens
        payload = self._text_payload(system_prompt, user_prompt, tokens)

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
                if got_any:
                    logger.warning("流式补全中途失败（已收到部分内容）：%s", exc)
                    return
                if _is_transient_failure(exc) or _json_mode_unsupported_status(exc):
                    logger.warning("流式补全建连失败，退回一次性：%s", exc)
                else:
                    raise

        yield self.complete_text(system_prompt, user_prompt, max_tokens=max_tokens)

    def _stream_send(self, payload: dict[str, Any]) -> Iterator[str]:
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self.api_format == FORMAT_ANTHROPIC:
            url = f"{self.base_url}/v1/messages"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        else:
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}

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


    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.webm",
        content_type: str = "audio/webm",
        language: str = "en",
    ) -> str | None:
        if self.api_format != FORMAT_OPENAI or not self.api_key or not self.base_url:
            return None
        if not (self.model or "").strip():
            return None

        url = f"{self.base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
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
                    return None
                raise AIProviderError(_format_error(exc)) from exc
            except httpx.HTTPError as exc:
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

    def _probe_payloads(self) -> Iterator[dict[str, Any]]:
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
                    if "max_tokens" in payload and _rejects_param(exc, "max_tokens"):
                        alt = _swap_max_tokens(payload)
                        if alt not in pending:
                            pending.append(alt)
                    if isinstance(exc, httpx.TimeoutException) and not isinstance(
                        exc, httpx.ConnectTimeout
                    ):
                        return self._slow_model_outcome()
                    if not _is_transient_failure(exc):
                        if _is_proxy_eligible_failure(exc):
                            pass
                        break
                    logger.warning(
                        "探活失败（%s，第 %d 次），退避重试：%s",
                        self.api_format,
                        attempt,
                        exc,
                    )
        return self._failure_outcome(last_error)


    def _failure_outcome(self, exc: Exception | None) -> ProbeOutcome:
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


def _iter_stream_chunks(
    resp: httpx.Response, api_format: str
) -> Iterator[str]:
    for line in resp.iter_lines():
        if not line:
            continue
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                return
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if api_format == FORMAT_ANTHROPIC:
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield text
            else:
                choices = data.get("choices") or []
                if choices:
                    content = choices[0].get("delta", {}).get("content")
                    if content:
                        yield content
        elif api_format == FORMAT_ANTHROPIC and line.startswith("event:"):
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


_STT_PROMPT = (
    "Transcribe the English speech verbatim, with correct punctuation, "
    "sentence casing and paragraph breaks."
)

_STT_MODEL_REJECT_STATUS = (400, 404, 422)

_stt_support_cache: dict[str, bool] = {}
_stt_cache_lock = threading.Lock()


def _silent_wav(seconds: float = STT_PROBE_SECONDS, rate: int = 16000) -> bytes:
    data = b"\x00\x00" * int(seconds * rate)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        len(data),
    )
    return header + data


def _extract_transcript(response: httpx.Response, language: str = "en") -> str:
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


_NON_WORD_SYMBOLS = re.compile(
    "[\U0001f000-\U0001faff\u2190-\u21ff\u2300-\u27bf\ufe0f\U0001f1e6-\U0001f1ff]"
)
_CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")


def _clean_transcript(text: str, language: str = "en") -> str:
    cleaned = " ".join(_NON_WORD_SYMBOLS.sub("", text).split())
    if not language.lower().startswith("en"):
        return cleaned

    ascii_only = " ".join(_CJK.sub(" ", cleaned).split())
    if len(ascii_only) * 2 < len(cleaned):
        return ""
    return ascii_only


def detect_stt_model(provider: AIProvider, *, force: bool = False) -> str | None:
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
        logger.info("语音转写探测失败（%s）：%s", provider.label, exc)
        return None

    with _stt_cache_lock:
        _stt_support_cache[provider.signature] = text is not None
    return model if text is not None else None


def stt_status(provider: AIProvider) -> dict:
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
    with _stt_cache_lock:
        _stt_support_cache.clear()


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


_NON_CHAT_MODEL_HINTS = (
    "embed",
    "bge",
    "gte",
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
    lowered = name.lower()
    if any(hint in lowered for hint in _NON_CHAT_MODEL_HINTS):
        return False
    return any(hint in lowered for hint in _CHAT_MODEL_HINTS)


def _chat_like_models(models: list[str], limit: int) -> list[str]:
    kept = [name for name in models if not _is_non_chat(name)]
    preferred = [name for name in kept if _is_chat_like(name)]
    rest = [name for name in kept if name not in preferred]
    return (preferred + rest)[:limit]


def _is_non_chat(name: str) -> bool:
    return any(hint in name.lower() for hint in _NON_CHAT_MODEL_HINTS)


def chat_first_models(models: list[str]) -> list[str]:
    preferred = [name for name in models if _is_chat_like(name)]
    rest = [name for name in models if name not in preferred]
    return preferred + rest


def _models_endpoint(
    base: str, api_key: str, api_format: str
) -> tuple[str, dict[str, str], dict[str, str]]:
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


def _looks_like_model_problem(exc: Exception | None) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    if status == 404:
        return True
    if status not in (400, 422):
        return False
    try:
        return "model" in exc.response.text.lower()
    except Exception:  # noqa: BLE001 - 读不到响应体就当不是模型问题
        return False


def _is_transient_failure(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in (408, 429) or status >= 500
    return isinstance(exc, _TRANSIENT_TRANSPORT_ERRORS)


def _response_snippet(resp: httpx.Response, limit: int = 160) -> str:
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
    proxy = _system_proxy_url()
    if proxy:
        return (
            f"本机配置了系统代理 {proxy}，AI 请求会先经过它；"
            "代理没开或不稳定时就会连不上，可在系统代理里把该地址设为直连例外"
        )
    return "检查网络是否通，或确认服务商地址是否写对"


def _system_proxy_url() -> str:
    try:
        proxies = getproxies()
    except Exception:  # noqa: BLE001 - 拿不到代理配置就当没有
        return ""
    return proxies.get("https") or proxies.get("http") or ""


def _is_proxy_eligible_failure(exc: Exception) -> bool:
    if isinstance(exc, httpx.ProxyError):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return bool(_system_proxy_url())
    return False


def _retry_after_seconds(resp: httpx.Response) -> float | None:
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
    asked = _retry_after_seconds(resp)
    if asked is not None:
        return min(max(asked, 0.0), PROBE_RATE_LIMIT_CAP)
    delay = base * (2 ** (attempt - 1))
    jitter = random.uniform(0, base)
    return min(delay + jitter, PROBE_RATE_LIMIT_CAP)


def _backoff_seconds(
    exc: Exception | None, attempt: int, base: float = PROBE_RETRY_DELAY
) -> float:
    if (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (429, 503)
        and exc.response is not None
    ):
        return _rate_limit_delay(exc.response, attempt, base)
    return base * attempt


def _probe_error_message(exc: Exception | None, provider: HttpAIProvider) -> str:
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
    outcome = probe_provider_detail(provider)
    return outcome.success, outcome.message


def probe_provider_detail(provider: AIProvider) -> ProbeOutcome:
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
                logger.error("站点默认模型地址不可用（%s）：%s", settings.ai_base_url, exc)
        if _provider is None:
            _provider = MockAIProvider()
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None
