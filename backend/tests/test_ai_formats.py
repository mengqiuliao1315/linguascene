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
    assert seen["body"]["max_tokens"] == settings.ai_max_tokens
    assert seen["body"]["messages"][0]["role"] == "system"
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


def test_probe_succeeds_on_plain_text_reply():
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
    assert "response_format" not in seen["body"]
    assert "temperature" not in seen["body"]
    assert seen["body"]["max_tokens"] == P.PROBE_MAX_TOKENS
    assert [m["role"] for m in seen["body"]["messages"]] == ["user"]


def test_probe_succeeds_when_model_echoes_schema():
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
    assert "Invalid token" in message


def test_probe_reports_unknown_model():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    ok, message = P.probe_provider(_provider(handler))

    assert ok is False
    assert "404" in message
    assert "model not found" in message


def test_probe_retries_transient_server_error():
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


@pytest.mark.parametrize(
    "raw",
    [
        "http://[::1/v1",
        "https://",
        "https://api.deepseek.com /v1",
        "https:// api.deepseek.com/v1",
    ],
)
def test_normalize_rejects_unusable_url(raw):
    with pytest.raises(P.AIProviderError):
        P.normalize_base_url(raw)


def test_probe_endpoint_reports_bad_base_url(auth_client):
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
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0)
    monkeypatch.setattr(P, "_credential_status", lambda **_kw: "ok")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("model is thinking")

    outcome = P.probe_provider_detail(_provider(handler))

    assert outcome.success is True
    assert outcome.status == "warn"
    assert "模型" in outcome.message


def test_probe_timeout_with_bad_key_is_still_a_failure(monkeypatch):
    monkeypatch.setattr(P, "PROBE_RETRY_DELAY", 0)
    monkeypatch.setattr(P, "_credential_status", lambda **_kw: "invalid")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("hanging behind a dead proxy")

    outcome = P.probe_provider_detail(_provider(handler))

    assert outcome.success is False
    assert outcome.status == "fail"
    assert "API Key" in outcome.message


def test_probe_suggests_real_models_when_model_name_is_rejected(monkeypatch):
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
    assert picked[:2] == ["deepseek-ai/DeepSeek-V4-Flash", "Qwen/Qwen3.8-27B"]
    assert picked[-1] == "acme/coder-7b"
    assert len(P._chat_like_models(models, 3)) == 3


def test_models_endpoint_lists_chat_models_first(auth_client, monkeypatch):
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
    assert resp.json()["models"] == [
        "Qwen/Qwen3.8-27B",
        "BAAI/bge-m3",
        "FunAudioLLM/SenseVoiceSmall",
    ]
