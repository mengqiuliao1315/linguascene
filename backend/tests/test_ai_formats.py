"""多 API 格式接入：地址归一化、请求构造、响应解析、模型列表、接口行为。

全部用 httpx.MockTransport 拦截，不发起真实网络请求。
"""

import json
from urllib.parse import urlparse

import httpx
import pytest
from pydantic import BaseModel

from app.ai import provider as P
from app.core.config import settings


class Answer(BaseModel):
    word: str
    meaning: str


def _provider(handler, **kwargs) -> P.HttpAIProvider:
    transport = httpx.MockTransport(handler)
    return P.HttpAIProvider(
        base_url=kwargs.pop("base_url", "https://api.example.com"),
        api_key=kwargs.pop("api_key", "sk-test"),
        model=kwargs.pop("model", "test-model"),
        api_format=kwargs.pop("api_format", P.FORMAT_OPENAI),
        transport=transport,
        **kwargs,
    )


# ------------------------------------------------------------------ 地址归一化


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://api.openai.com", "https://api.openai.com/v1"),
        ("https://api.openai.com/", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1"),
        ("api.deepseek.com", "https://api.deepseek.com/v1"),
        ("https://relay.example.com/v1/", "https://relay.example.com/v1"),
        ("https://relay.example.com/api/v1", "https://relay.example.com/api/v1"),
        ("https://relay.example.com/v1/models", "https://relay.example.com/v1"),
    ],
)
def test_normalize_openai(raw, expected):
    assert P.normalize_base_url(raw, P.FORMAT_OPENAI) == expected


def test_normalize_anthropic():
    assert (
        P.normalize_base_url("https://api.anthropic.com", P.FORMAT_ANTHROPIC)
        == "https://api.anthropic.com"
    )
    assert (
        P.normalize_base_url("https://api.anthropic.com/v1", P.FORMAT_ANTHROPIC)
        == "https://api.anthropic.com"
    )
    assert (
        P.normalize_base_url(
            "https://api.anthropic.com/v1/messages", P.FORMAT_ANTHROPIC
        )
        == "https://api.anthropic.com"
    )


def test_normalize_gemini():
    assert (
        P.normalize_base_url(
            "https://generativelanguage.googleapis.com", P.FORMAT_GEMINI
        )
        == "https://generativelanguage.googleapis.com/v1beta"
    )
    assert (
        P.normalize_base_url(
            "https://generativelanguage.googleapis.com/v1beta", P.FORMAT_GEMINI
        )
        == "https://generativelanguage.googleapis.com/v1beta"
    )


def test_normalize_empty():
    assert P.normalize_base_url("", P.FORMAT_OPENAI) == ""
    assert P.normalize_base_url("   ", P.FORMAT_OPENAI) == ""


def test_unknown_format_rejected():
    with pytest.raises(P.AIProviderError):
        P.HttpAIProvider(base_url="https://x.com", api_key="k", model="m", api_format="nope")


# ------------------------------------------------------------------ 请求构造与解析


def test_openai_chat_request_and_parse():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"word": "hello", "meaning": "你好"}'}}
                ]
            },
        )

    provider = _provider(handler)
    out = provider.complete_json("sys {schema}", "user", Answer)

    assert out == {"word": "hello", "meaning": "你好"}
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    # 输出上限必须带上，否则跑题的模型能把一轮对话拖到超时
    assert seen["body"]["max_tokens"] == settings.ai_max_tokens
    assert seen["body"]["messages"][0]["role"] == "system"
    # schema 必须被替换进系统提示
    assert '"properties"' in seen["body"]["messages"][0]["content"]


def test_openai_content_as_parts_list():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [{"type": "text", "text": '{"word":"a","meaning":"b"}'}]
                        }
                    }
                ]
            },
        )

    provider = _provider(handler)
    assert provider.complete_json("s {schema}", "u", Answer)["word"] == "a"


def test_anthropic_request_and_parse():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": '{"word":"hi","meaning":"嗨"}'}]}
        )

    provider = _provider(
        handler,
        base_url="https://api.anthropic.com",
        api_format=P.FORMAT_ANTHROPIC,
        model="claude-3-5-sonnet",
    )
    out = provider.complete_json("sys {schema}", "user", Answer)

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["system"].startswith("sys")
    assert seen["body"]["max_tokens"] == settings.ai_max_tokens
    assert "response_format" not in seen["body"]
    assert out["meaning"] == "嗨"


def test_gemini_request_and_parse():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"word":"go","meaning":"去"}'}]}}
                ]
            },
        )

    provider = _provider(
        handler,
        base_url="https://generativelanguage.googleapis.com",
        api_format=P.FORMAT_GEMINI,
        model="models/gemini-1.5-flash",
    )
    out = provider.complete_json("sys {schema}", "user", Answer)

    # 模型名里的 models/ 前缀不能重复拼进 URL；key 走 query 参数
    assert urlparse(seen["url"]).path == (
        "/v1beta/models/gemini-1.5-flash:generateContent"
    )
    assert "key=sk-test" in seen["url"]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["generationConfig"]["maxOutputTokens"] == settings.ai_max_tokens
    assert out["word"] == "go"


def test_openai_responses_request_and_parse():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"output_text": '{"word":"up","meaning":"上"}'})

    provider = _provider(handler, api_format=P.FORMAT_OPENAI_RESPONSES)
    out = provider.complete_json("sys {schema}", "user", Answer)

    assert seen["url"] == "https://api.example.com/v1/responses"
    assert seen["body"]["instructions"].startswith("sys")
    assert seen["body"]["max_output_tokens"] == settings.ai_max_tokens
    assert out["word"] == "up"


def test_code_fence_json_is_extracted():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '```json\n{"word":"a","meaning":"b"}\n```'}}
                ]
            },
        )

    provider = _provider(handler)
    assert provider.complete_json("s {schema}", "u", Answer)["word"] == "a"


def test_retries_without_json_mode_on_failure():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format not supported")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"word":"x","meaning":"y"}'}}]}
        )

    provider = _provider(handler)
    out = provider.complete_json("s {schema}", "u", Answer)

    assert len(calls) == 2
    assert "response_format" not in calls[1]
    assert out["meaning"] == "y"


def test_retries_with_max_completion_tokens_when_max_tokens_rejected():
    """新版 OpenAI 模型只认 max_completion_tokens：被点名时自动换写法重试。"""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "max_tokens" in body:
            return httpx.Response(
                400,
                text="Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"word":"z","meaning":"末"}'}}]}
        )

    provider = _provider(handler)
    out = provider.complete_json("s {schema}", "u", Answer)

    assert calls[0]["max_tokens"] == settings.ai_max_tokens
    # 前两次都带 max_tokens 被拒，最后一次换成 max_completion_tokens 才成功
    assert calls[-1].get("max_completion_tokens") == settings.ai_max_tokens
    assert "max_tokens" not in calls[-1]
    assert out["word"] == "z"


def test_http_error_message_includes_status():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    provider = _provider(handler)
    with pytest.raises(P.AIProviderError) as exc:
        provider.complete_json("s {schema}", "u", Answer)
    assert "401" in str(exc.value)


def test_complete_json_retries_transient_network_error(monkeypatch):
    """网络抖动不该把整轮调用打死：连接被拒一次后自愈。"""
    monkeypatch.setattr(P, "COMPLETE_RETRY_DELAY", 0)
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"word":"a","meaning":"b"}'}}]}
        )

    provider = _provider(handler)
    out = provider.complete_json("s {schema}", "u", Answer)

    assert out["word"] == "a"
    assert len(calls) == 2


def test_complete_json_retries_rate_limit_429(monkeypatch):
    """429 限流是临时的：免费额度的服务商很常见，应自动重试而不是报错。"""
    monkeypatch.setattr(P, "COMPLETE_RETRY_DELAY", 0)
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) <= 2:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"word":"a","meaning":"b"}'}}]}
        )

    provider = _provider(handler)
    out = provider.complete_json("s {schema}", "u", Answer)

    assert out["meaning"] == "b"
    assert len(calls) == 3


def test_complete_json_retries_invalid_model_json(monkeypatch):
    """模型偶尔返回非法 JSON：temperature>0，再采样一次通常就好了。"""
    monkeypatch.setattr(P, "COMPLETE_RETRY_DELAY", 0)
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "抱歉，我做不到"}}]}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"word":"a","meaning":"b"}'}}]}
        )

    provider = _provider(handler)
    out = provider.complete_json("s {schema}", "u", Answer)

    assert out["word"] == "a"
    assert len(calls) == 2


def test_complete_json_does_not_retry_auth_error(monkeypatch):
    """鉴权错误是确定性的：不浪费重试预算原地重试。

    openai 格式有 json_mode / 纯文本两种请求体，各试一次即止（不带
    response_format 的写法有可能成功）；同一个 payload 绝不打第二遍。
    """
    monkeypatch.setattr(P, "COMPLETE_RETRY_DELAY", 0)
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(401, text="bad key")

    provider = _provider(handler)
    with pytest.raises(P.AIProviderError):
        provider.complete_json("s {schema}", "u", Answer)

    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_missing_key_raises():
    provider = _provider(lambda _r: httpx.Response(200, json={}), api_key="")
    with pytest.raises(P.AIProviderError):
        provider.complete_json("s {schema}", "u", Answer)


def test_signature_separates_formats_and_keys():
    a = _provider(lambda _r: httpx.Response(200, json={}), api_key="k1")
    b = _provider(lambda _r: httpx.Response(200, json={}), api_key="k2")
    c = _provider(
        lambda _r: httpx.Response(200, json={}),
        api_key="k1",
        api_format=P.FORMAT_ANTHROPIC,
    )
    assert a.signature != b.signature
    assert a.signature != c.signature


# ------------------------------------------------------------------ 模型列表


def test_list_models_openai():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.com/v1/models"
        return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}]})

    models = P.list_models(
        base_url="https://api.example.com",
        api_key="k",
        api_format=P.FORMAT_OPENAI,
        transport=httpx.MockTransport(handler),
    )
    assert models == ["a", "b"]


def test_list_models_anthropic():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.anthropic.com/v1/models"
        assert request.headers.get("x-api-key") == "k"
        return httpx.Response(200, json={"data": [{"id": "claude-3-5-sonnet"}]})

    models = P.list_models(
        base_url="https://api.anthropic.com",
        api_key="k",
        api_format=P.FORMAT_ANTHROPIC,
        transport=httpx.MockTransport(handler),
    )
    assert models == ["claude-3-5-sonnet"]


def test_list_models_gemini():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemini-1.5-pro"},
                    {"name": "models/gemini-1.5-flash"},
                ]
            },
        )

    models = P.list_models(
        base_url="https://generativelanguage.googleapis.com",
        api_key="k",
        api_format=P.FORMAT_GEMINI,
        transport=httpx.MockTransport(handler),
    )
    assert models == ["gemini-1.5-flash", "gemini-1.5-pro"]


def test_list_models_error_surfaces():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(P.AIProviderError) as exc:
        P.list_models(
            base_url="https://api.example.com",
            api_key="k",
            transport=httpx.MockTransport(handler),
        )
    assert "500" in str(exc.value)


def test_list_models_requires_key():
    with pytest.raises(P.AIProviderError):
        P.list_models(base_url="https://api.example.com", api_key="")


# ------------------------------------------------------------------ 接口行为


def test_models_endpoint_requires_auth(client):
    resp = client.post(
        "/api/ai-settings/models",
        json={"base_url": "https://api.example.com/v1", "api_format": "openai"},
    )
    assert resp.status_code == 401


def test_create_config_with_format(auth_client):
    resp = auth_client.post(
        "/api/ai-settings/configs",
        json={
            "name": "Anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-anthropic",
            "api_format": "anthropic",
            "models": ["claude-3-5-sonnet"],
            "active_model": "claude-3-5-sonnet",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    config = body["configs"][-1]
    assert config["api_format"] == "anthropic"
    assert body["active_source"] == "user"
    auth_client.delete(f"/api/ai-settings/configs/{config['id']}")


def test_invalid_format_rejected(auth_client):
    resp = auth_client.post(
        "/api/ai-settings/configs",
        json={
            "base_url": "https://api.example.com/v1",
            "api_key": "k",
            "api_format": "not-a-format",
            "models": ["m"],
        },
    )
    assert resp.status_code == 422


def test_models_endpoint_returns_list(auth_client, monkeypatch):
    from app.services import ai_config_service

    monkeypatch.setattr(
        ai_config_service, "list_provider_models", lambda **kw: ["m1", "m2"]
    )
    resp = auth_client.post(
        "/api/ai-settings/models",
        json={
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1",
            "api_format": "openai",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["models"] == ["m1", "m2"]


def test_models_endpoint_reports_provider_error(auth_client, monkeypatch):
    from app.services import ai_config_service

    def boom(**_kw):
        raise P.AIProviderError("HTTP 401：invalid api key")

    monkeypatch.setattr(ai_config_service, "list_provider_models", boom)
    resp = auth_client.post(
        "/api/ai-settings/models",
        json={
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1",
            "api_format": "openai",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "401" in body["message"]


# ------------------------------------------------------------------ 测试连接（探活）


def test_probe_succeeds_on_plain_text_reply():
    """探活只验证「地址 + Key + 模型名」能不能走通，不看模型答了什么。

    回归：早先探活要求模型按业务 Schema 返回 JSON，模型偶尔会把 Schema 本身
    回显回来，于是「信息都填对了却随机报错」。这里返回一段纯文本也必须算成功。
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]}
        )

    provider = _provider(handler)
    ok, message = P.probe_provider(provider)

    assert ok is True
    assert "test-model" in message
    # 探活请求要尽量小：不带 response_format / temperature，也不带 system 提示
    assert "response_format" not in seen["body"]
    assert "temperature" not in seen["body"]
    assert seen["body"]["max_tokens"] == P.PROBE_MAX_TOKENS
    assert [m["role"] for m in seen["body"]["messages"]] == ["user"]


def test_probe_succeeds_when_model_echoes_schema():
    """模型把 JSON Schema 回显回来时，探活不该判失败（历史 bug 的直接回归）。"""
    echoed = {
        "properties": {"word": {"title": "Word", "type": "string"}},
        "cefr_level": "A1",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(echoed)}}]}
        )

    ok, _message = P.probe_provider(_provider(handler))
    assert ok is True


def test_probe_reports_invalid_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Invalid token"}}
        )

    ok, message = P.probe_provider(_provider(handler))

    assert ok is False
    assert "401" in message
    assert "API Key" in message
    # 服务商自己的说明要带出来，方便定位
    assert "Invalid token" in message


def test_probe_reports_unknown_model():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    ok, message = P.probe_provider(_provider(handler))

    assert ok is False
    assert "404" in message
    assert "model not found" in message


def test_probe_retries_transient_server_error():
    """服务端 5xx 是临时的，应当自动重试而不是直接把失败甩给用户。"""
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, text="upstream busy")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]}
        )

    ok, _message = P.probe_provider(_provider(handler))

    assert ok is True
    assert len(calls) == 2


def test_probe_does_not_retry_auth_error():
    """鉴权类错误重试没有意义，只发一次，省得白等。"""
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, text="bad key")

    ok, _message = P.probe_provider(_provider(handler))

    assert ok is False
    assert len(calls) == 1


def test_probe_swaps_max_tokens_when_rejected():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "max_tokens" in body:
            return httpx.Response(
                400,
                text="Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]}
        )

    ok, _message = P.probe_provider(_provider(handler))

    assert ok is True
    assert calls[-1].get("max_completion_tokens") == P.PROBE_MAX_TOKENS
    assert "max_tokens" not in calls[-1]


@pytest.mark.parametrize(
    "api_format,path",
    [
        (P.FORMAT_ANTHROPIC, "/v1/messages"),
        (P.FORMAT_GEMINI, "/v1beta/models/test-model:generateContent"),
        (P.FORMAT_OPENAI_RESPONSES, "/v1/responses"),
        (P.FORMAT_OPENAI, "/v1/chat/completions"),
    ],
)
def test_probe_hits_each_format_endpoint(api_format, path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    ok, _message = P.probe_provider(_provider(handler, api_format=api_format))

    assert ok is True
    assert urlparse(seen["url"]).path == path


def test_probe_requires_key_and_base_url():
    provider = _provider(lambda _r: httpx.Response(200, json={}), api_key="")
    assert P.probe_provider(provider) == (False, "还没有填 API Key")

    empty_base = P.HttpAIProvider(
        base_url="", api_key="sk-test", model="m", api_format=P.FORMAT_OPENAI
    )
    assert P.probe_provider(empty_base) == (False, "还没有填 Base URL")


def test_probe_endpoint_reports_success(auth_client, monkeypatch):
    """接口层：探活成功/失败都要以 200 + success 字段返回，而不是抛异常。"""
    from app.services import ai_config_service

    monkeypatch.setattr(
        ai_config_service,
        "build_provider",
        lambda **kw: P.MockAIProvider(),
    )
    resp = auth_client.post(
        "/api/ai-settings/test",
        json={
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1",
            "api_format": "openai",
            "model": "m1",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_probe_endpoint_surfaces_failure_message(auth_client, monkeypatch):
    from app.services import ai_config_service

    monkeypatch.setattr(
        ai_config_service,
        "build_provider",
        lambda **kw: _provider(lambda _r: httpx.Response(401, text="bad key")),
    )
    resp = auth_client.post(
        "/api/ai-settings/test",
        json={
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1",
            "api_format": "openai",
            "model": "m1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "401" in body["message"]


# ------------------------------------------- 填错/填对却被判失败的地址与超时


@pytest.mark.parametrize(
    "raw",
    [
        "http://[::1/v1",  # 方括号没配对，urlparse 直接抛 ValueError
        "https://",  # 只有协议没有域名
        "https://api.deepseek.com /v1",  # 复制时带进了空格
        "https:// api.deepseek.com/v1",
    ],
)
def test_normalize_rejects_unusable_url(raw):
    """填坏的地址要在归一化这一步就说清楚。

    回归：`http://[::1/v1` 以前会一路抛到接口层变成 500「服务器内部错误」，
    `https://` 则报一句英文的 URL 缺协议，用户根本不知道要改哪里。
    """
    with pytest.raises(P.AIProviderError):
        P.normalize_base_url(raw)


def test_probe_endpoint_reports_bad_base_url(auth_client):
    """接口层：坏地址返回 200 + 可读说明，而不是 500。"""
    resp = auth_client.post(
        "/api/ai-settings/test",
        json={
            "base_url": "http://[::1/v1",
            "api_key": "sk-1",
            "api_format": "openai",
            "model": "m1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["status"] == "fail"
    assert "Base URL" in body["message"]


def test_probe_timeout_reports_warn_when_credentials_are_ok(monkeypatch):
    """思考型模型回一个 ping 要好几十秒：那是「慢」，不是「信息填错了」。

    回归：读超时曾被当成失败，于是「信息都填对了却一直报错、要多试几次」。
    """
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0)
    monkeypatch.setattr(P, "_credential_status", lambda **_kw: "ok")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("model is thinking")

    outcome = P.probe_provider_detail(_provider(handler))

    assert outcome.success is True
    assert outcome.status == "warn"
    assert "模型" in outcome.message


def test_probe_timeout_with_bad_key_is_still_a_failure(monkeypatch):
    """但超时后如果 /models 明确说 Key 不对，就不该给绿色。"""
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0)
    monkeypatch.setattr(P, "_credential_status", lambda **_kw: "invalid")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("hanging behind a dead proxy")

    outcome = P.probe_provider_detail(_provider(handler))

    assert outcome.success is False
    assert outcome.status == "fail"
    assert "API Key" in outcome.message


def test_probe_suggests_real_models_when_model_name_is_rejected(monkeypatch):
    """模型名被服务商否掉时，顺手把这条地址下真实存在的模型名带上。

    预设里的默认模型名会随服务商下架而过时（返回 400 Model does not exist），
    用户对着「多半是模型名写错了」只能瞎猜——这里直接给出可用清单。
    """
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0)
    monkeypatch.setattr(
        P, "list_models", lambda **_kw: ["deepseek-chat", "Qwen/Qwen3-8B"]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"message": "Model does not exist. Please check it carefully."}
        )

    outcome = P.probe_provider_detail(_provider(handler))

    assert outcome.success is False
    assert outcome.suggested_models == ["deepseek-chat", "Qwen/Qwen3-8B"]
    assert "deepseek-chat" in outcome.message
    assert "自动获取模型列表" in outcome.message


def test_complete_json_waits_out_retry_after(monkeypatch):
    """429 带着 Retry-After 时要等够，不能固定半秒就重试。

    免费额度的服务商（硅基流动等）限流往往要等好几秒，三次固定半秒的重试
    全是白试，最后整轮对话被打回离线规则引擎，看着就是「AI 时好时坏」。
    """
    sleeps: list[float] = []
    monkeypatch.setattr(P.time, "sleep", sleeps.append)
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"word":"a","meaning":"b"}'}}]}
        )

    out = _provider(handler).complete_json("s {schema}", "u", Answer)

    assert out["word"] == "a"
    assert sleeps and sleeps[0] == pytest.approx(3.0)


def test_chat_like_models_skips_embeddings_and_rerankers():
    """失败提示里推荐的模型必须是能聊天的。

    回归：硅基流动的模型列表按字母序排，前五个全是 BAAI/bge-* 向量模型，
    直接列表头推荐等于把用户往沟里带。
    """
    models = [
        "BAAI/bge-large-en-v1.5",
        "BAAI/bge-reranker-v2-m3",
        "FunAudioLLM/SenseVoiceSmall",
        "deepseek-ai/DeepSeek-V4-Flash",
        "Qwen/Qwen3.8-27B",
        "acme/coder-7b",
    ]
    picked = P._chat_like_models(models, 8)

    assert "BAAI/bge-large-en-v1.5" not in picked
    assert "BAAI/bge-reranker-v2-m3" not in picked
    assert "FunAudioLLM/SenseVoiceSmall" not in picked
    # 常见对话模型排前面，其余能聊的跟在后面
    assert picked[:2] == ["deepseek-ai/DeepSeek-V4-Flash", "Qwen/Qwen3.8-27B"]
    assert picked[-1] == "acme/coder-7b"
    assert len(P._chat_like_models(models, 3)) == 3


def test_models_endpoint_lists_chat_models_first(auth_client, monkeypatch):
    """拉模型列表是给人挑对话模型的，别让向量/语音模型堵在最前面。

    回归：硅基流动按字母序返回，前八个全是 BAAI/bge-*、FunAudioLLM/*
    这些不能聊天的模型，用户得自己往下翻。
    """
    from app.services import ai_config_service

    monkeypatch.setattr(
        ai_config_service,
        "list_models",
        lambda **_kw: ["BAAI/bge-m3", "Qwen/Qwen3.8-27B", "FunAudioLLM/SenseVoiceSmall"],
    )
    resp = auth_client.post(
        "/api/ai-settings/models",
        json={
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1",
            "api_format": "openai",
        },
    )
    assert resp.status_code == 200
    # 能聊天的排前面，其余一个不丢
    assert resp.json()["models"] == [
        "Qwen/Qwen3.8-27B",
        "BAAI/bge-m3",
        "FunAudioLLM/SenseVoiceSmall",
    ]
