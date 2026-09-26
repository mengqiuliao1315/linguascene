"""整句朗读与语音识别接口。"""

import json
import re
import time
import urllib.parse
from pathlib import Path

import httpx

from app.ai import provider as P
from app.services import audio_service


def test_audio_capability_reports_tts(client):
    response = client.get("/api/audio/capability")
    assert response.status_code == 200
    assert response.json()["tts"] is True


def test_tts_rejects_empty_text(client):
    """空文本没有意义，直接 422，不要白跑一次合成。"""
    assert client.get("/api/audio/tts?text=").status_code == 422


def test_tts_returns_mp3_or_404(client):
    """装了 edge-tts 就返回音频，没装就 404 让前端回退浏览器朗读。

    两条路径都算通过：测试环境不保证能联外网，这里不把网络当成断言前提。
    """
    text = urllib.parse.quote("Hello there, this is a test.")
    response = client.get(f"/api/audio/tts?text={text}&lang=en-US")
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 0


def test_synthesize_text_is_cached():
    """同一句话第二次必须命中缓存，不再调用 edge-tts。"""
    text = "Cache probe sentence for the audio service."
    first = audio_service.synthesize_text(text, "en-US")
    if first is None:
        return  # 没网/没装 edge-tts 时跳过，不作为失败
    assert first.exists()

    start = time.time()
    second = audio_service.synthesize_text(text, "en-US")
    assert second == first
    assert time.time() - start < 1.0


# ------------------------------------------------- 开场白静态音频（前端资源）

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _read_manifest() -> dict[str, str]:
    """从生成的清单里读 slug -> 原文（清单由 build_opening_audio.py 写出）。"""
    src = (_FRONTEND_DIR / "lib" / "openingAudio.ts").read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for block in re.split(r'\n  "', src):
        slug = re.match(r"([a-z\-]+)\":", block)
        text = re.search(r'text:\s*("(?:[^"\\]|\\.)*")', block)
        if slug and text:
            result[slug.group(1)] = json.loads(text.group(1))
    return result


def test_opening_audio_in_sync_with_scenarios():
    """开场白必须有对应静态音频，且音频是按当前这句原文合成的。

    护的是这个失败形态：改了开场白却忘了重跑 build_opening_audio.py，于是
    staticOpeningUrl 返回 null，用户进场景又得等现场合成——感觉就是「又变慢了」。
    前端目录不在（只部署后端）时跳过。
    """
    if not _FRONTEND_DIR.exists():
        import pytest

        pytest.skip("前端目录不在，跳过静态音频检查")

    from app.data.scenarios import SCENARIOS

    manifest = _read_manifest()
    audio_dir = _FRONTEND_DIR / "public" / "audio" / "openings"

    for scenario in SCENARIOS:
        slug = scenario["slug"]
        assert slug in manifest, f"{slug} 没有静态开场白，重跑 build_opening_audio.py"
        assert manifest[slug] == scenario["opening_line"], (
            f"{slug} 的开场白改过了但音频没重新生成，重跑 build_opening_audio.py"
        )
        mp3 = audio_dir / f"{slug}.mp3"
        assert mp3.exists() and mp3.stat().st_size > 0, f"{slug} 的音频文件缺失或为空"


def test_free_talk_opening_audio_present():
    """自由对话的开场句不在 SCENARIOS 里，单独兜一条，别漏。"""
    if not _FRONTEND_DIR.exists():
        import pytest

        pytest.skip("前端目录不在，跳过静态音频检查")

    from app.services.conversation_service import FREE_TALK_OPENING

    manifest = _read_manifest()
    assert manifest.get("free-talk") == FREE_TALK_OPENING
    mp3 = _FRONTEND_DIR / "public" / "audio" / "openings" / "free-talk.mp3"
    assert mp3.exists() and mp3.stat().st_size > 0


# ------------------------------------------------------------ 语音识别（STT）

def test_transcribe_requires_login(client):
    response = client.post(
        "/api/audio/transcribe",
        files={"file": ("a.webm", b"fake-audio", "audio/webm")},
    )
    assert response.status_code in (401, 403)


def test_transcribe_offline_provider_is_unavailable(auth_client):
    """用户没接模型、服务端也没开本地识别时明确回 503，前端据此改用浏览器识别。"""
    response = auth_client.post(
        "/api/audio/transcribe",
        files={"file": ("a.webm", b"fake-audio", "audio/webm")},
    )
    assert response.status_code == 503


def test_stt_capability_offline(auth_client):
    body = auth_client.get("/api/audio/stt").json()
    assert body["available"] is False
    assert body["reason"]
    assert body["engine"] == ""


# ------------------------------------------------- 本地识别（不需要 Key 的那条）

from app.services import local_asr  # noqa: E402


def _enable_local(monkeypatch, text: str = "I would like a latte.") -> dict:
    """把本地识别通道接上（测试环境默认是关的，见 conftest）。"""
    calls = {"count": 0}

    def fake_transcribe(audio, *, filename="speech.webm"):
        calls["count"] += 1
        return text

    monkeypatch.setattr(local_asr, "available", lambda: True)
    monkeypatch.setattr(local_asr, "model_name", lambda: "base.en")
    monkeypatch.setattr(local_asr, "transcribe", fake_transcribe)
    return calls


def test_transcribe_falls_back_to_local_when_model_fails(auth_client, monkeypatch):
    """用户那把 Key 失效时接口如实报错，**不偷偷换通道**：换哪条要用户自己同意。"""
    calls = _enable_local(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("key expired", request=request)

    P.reset_stt_cache()
    provider = _fake_provider(handler)
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 502
        assert calls["count"] == 0  # 本地识别没被悄悄调用
    finally:
        _clear_override(key)
        P.reset_stt_cache()


def test_transcribe_unsupported_model_reports_503(auth_client, monkeypatch):
    """模型不支持转写：503 让前端弹窗问用户，而不是自己换一条。"""
    calls = _enable_local(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Model does not exist"}})

    P.reset_stt_cache()
    provider = _fake_provider(handler)
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 503
        assert calls["count"] == 0
    finally:
        _clear_override(key)
        P.reset_stt_cache()


def test_transcribe_local_engine_never_touches_provider(auth_client, monkeypatch):
    """选「本地识别」就不该动用户的 API 额度：一次模型请求都不发。"""
    hit = {"provider": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hit["provider"] += 1
        return httpx.Response(200, json={"text": "should not be used"})

    _enable_local(monkeypatch, text="A medium latte, please.")
    provider = _fake_provider(handler)
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            data={"engine": "local"},
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["engine"] == "local"
        assert hit["provider"] == 0
    finally:
        _clear_override(key)


def test_stt_capability_lists_local_but_keeps_model_default(auth_client, monkeypatch):
    """用户没接模型时默认通道留空：由前端弹窗问，不替他挑。"""
    _enable_local(monkeypatch)
    body = auth_client.get("/api/audio/stt").json()
    ids = [item["id"] for item in body["engines"]]
    assert "local" in ids
    # 测试环境是 mock provider：没有可用的用户模型
    assert body["available"] is False
    assert body["engine"] == ""
    assert body["local_model"] == "base.en"  # _enable_local 把模型名钉在 base.en


def test_stt_capability_prefers_user_model(auth_client, monkeypatch):
    _enable_local(monkeypatch)
    provider = _fake_provider(lambda request: httpx.Response(200, json={"text": "hi"}))
    key = _override_provider(provider)
    try:
        body = auth_client.get("/api/audio/stt").json()
        assert body["engine"] == "model"
        assert [item["id"] for item in body["engines"]] == ["local"]
    finally:
        _clear_override(key)


# ------------------------------------------------------- 转写：模型名与回退

_PROVIDER_OVERRIDE_KEY = None


def _fake_provider(handler, **kwargs):
    """用 MockTransport 造一个 provider，替换掉按用户配置解析出来的那个。"""
    kwargs.setdefault("base_url", "https://api.example.com")
    return P.HttpAIProvider(
        api_key="sk-test",
        model="test-chat-model",
        api_format=P.FORMAT_OPENAI,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _override_provider(provider):
    from app.api.deps import get_user_provider
    from app.main import app

    app.dependency_overrides[get_user_provider] = lambda: provider
    return get_user_provider


def _clear_override(key):
    from app.main import app

    app.dependency_overrides.pop(key, None)


def test_transcribe_uses_the_users_own_model(auth_client):
    """转写必须打到用户填的那个模型，不能另挑一份名单。"""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/audio/transcriptions")
        seen.append(_form_field(request, "model"))
        return httpx.Response(200, json={"text": "I'd like a latte, please."})

    P.reset_stt_cache()
    provider = _fake_provider(handler)
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "I'd like a latte, please."
        # 两次都只用用户配置里的模型名，不试别的
        auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert seen == ["test-chat-model", "test-chat-model"]
    finally:
        _clear_override(key)
        P.reset_stt_cache()


def test_transcribe_returns_503_when_no_model_works(auth_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Model does not exist"}})

    P.reset_stt_cache()
    provider = _fake_provider(handler)
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 503
    finally:
        _clear_override(key)
        P.reset_stt_cache()


def test_transcribe_maps_timeouts_to_502(auth_client):
    """超时是「这次没成」而不是「不支持」：报 502 让前端提示重试。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    P.reset_stt_cache()
    provider = _fake_provider(handler)
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 502
    finally:
        _clear_override(key)
        P.reset_stt_cache()


def test_transcribe_rejects_empty_audio(auth_client):
    provider = _fake_provider(lambda request: httpx.Response(200, json={"text": ""}))
    key = _override_provider(provider)
    try:
        response = auth_client.post(
            "/api/audio/transcribe",
            files={"file": ("a.webm", b"", "audio/webm")},
        )
        assert response.status_code == 400
    finally:
        _clear_override(key)


def test_transcript_cleaning_strips_emoji_and_extra_space():
    assert (
        P._clean_transcript("Hi there.  Could I get a latte? 😊")
        == "Hi there. Could I get a latte?"
    )


def test_transcript_cleaning_drops_stray_chinese():
    """英文场景下模型听出中文：整句丢掉，别往输入框里塞莫名其妙的中文。"""
    assert P._clean_transcript("我想点一杯拿铁。", "en") == ""
    assert P._clean_transcript("嗯，那个我觉得。", "en") == ""


def test_transcript_cleaning_keeps_english_part_of_mixed():
    assert (
        P._clean_transcript("你好，I would like a coffee", "en")
        == "I would like a coffee"
    )


def test_transcript_cleaning_respects_non_english_language():
    """非英文场景不做这层过滤（同一段话该原样留着）。"""
    assert P._clean_transcript("你好，我想点一杯拿铁。", "zh") == "你好，我想点一杯拿铁。"


def test_stt_status_names_the_users_model():
    """能力探测报的是用户自己填的模型，不是另选的转写模型。"""
    provider = P.HttpAIProvider(
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-test",
        model="deepseek-ai/DeepSeek-V3",
        api_format=P.FORMAT_OPENAI,
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    status = P.stt_status(provider)
    assert status["available"] is True
    assert status["model"] == "deepseek-ai/DeepSeek-V3"


def _form_field(request: httpx.Request, name: str) -> str:
    """从 multipart 请求体里抠出一个字段的值（测试用，够简单即可）。"""
    body = request.read().decode("utf-8", errors="ignore")
    marker = f'name="{name}"'
    index = body.find(marker)
    if index == -1:
        return ""
    rest = body[index + len(marker) :]
    return rest.split("\r\n\r\n", 1)[1].split("\r\n", 1)[0]
