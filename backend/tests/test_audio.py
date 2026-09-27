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
    assert client.get("/api/audio/tts?text=").status_code == 422


def test_tts_returns_mp3_or_404(client):
    text = urllib.parse.quote("Hello there, this is a test.")
    response = client.get(f"/api/audio/tts?text={text}&lang=en-US")
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 0


def test_synthesize_text_is_cached():
    text = "Cache probe sentence for the audio service."
    first = audio_service.synthesize_text(text, "en-US")
    if first is None:
        return
    assert first.exists()

    start = time.time()
    second = audio_service.synthesize_text(text, "en-US")
    assert second == first
    assert time.time() - start < 1.0


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _read_manifest() -> dict[str, str]:
    src = (_FRONTEND_DIR / "lib" / "openingAudio.ts").read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for block in re.split(r'\n  "', src):
        slug = re.match(r"([a-z\-]+)\":", block)
        text = re.search(r'text:\s*("(?:[^"\\]|\\.)*")', block)
        if slug and text:
            result[slug.group(1)] = json.loads(text.group(1))
    return result


def test_opening_audio_in_sync_with_scenarios():
    if not _FRONTEND_DIR.exists():
        import pytest

        pytest.skip("前端目录不在，跳过静态音频检查")

    from app.data.scenarios import SCENARIOS

    manifest = _read_manifest()
    audio_dir = _FRONTEND_DIR / "public" / "audio" / "openings"

    for scenario in SCENARIOS:
        slug = scenario["slug"]
        assert slug in manifest, f"{slug} 没有静态开场白"
        assert manifest[slug] == scenario["opening_line"], (
            f"{slug} 的开场白与静态音频不一致"
        )
        mp3 = audio_dir / f"{slug}.mp3"
        assert mp3.exists() and mp3.stat().st_size > 0, f"{slug} 的音频文件缺失或为空"


def test_free_talk_opening_audio_present():
    if not _FRONTEND_DIR.exists():
        import pytest

        pytest.skip("前端目录不在，跳过静态音频检查")

    from app.services.conversation_service import FREE_TALK_OPENING

    manifest = _read_manifest()
    assert manifest.get("free-talk") == FREE_TALK_OPENING
    mp3 = _FRONTEND_DIR / "public" / "audio" / "openings" / "free-talk.mp3"
    assert mp3.exists() and mp3.stat().st_size > 0


def test_transcribe_requires_login(client):
    response = client.post(
        "/api/audio/transcribe",
        files={"file": ("a.webm", b"fake-audio", "audio/webm")},
    )
    assert response.status_code in (401, 403)


def test_transcribe_offline_provider_is_unavailable(auth_client):
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


from app.services import local_asr  # noqa: E402


def _enable_local(monkeypatch, text: str = "I would like a latte.") -> dict:
    calls = {"count": 0}

    def fake_transcribe(audio, *, filename="speech.webm", hotwords=""):
        calls["count"] += 1
        calls["hotwords"] = hotwords
        return text

    monkeypatch.setattr(local_asr, "available", lambda: True)
    monkeypatch.setattr(local_asr, "model_name", lambda: "base.en")
    monkeypatch.setattr(local_asr, "transcribe", fake_transcribe)
    return calls


def test_transcribe_feeds_scenario_words_to_local_engine(auth_client, monkeypatch):
    """场景自带的句式和词汇要真的传进本地识别，否则本地小模型听不出专有名词。"""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.learning import Scenario

    db = SessionLocal()
    try:
        scenario = db.execute(
            select(Scenario).where(Scenario.slug == "ordering-coffee")
        ).scalar_one()
        scenario_id = scenario.id
    finally:
        db.close()

    calls = _enable_local(monkeypatch)
    response = auth_client.post(
        "/api/audio/transcribe",
        data={"engine": "local", "scenario_id": str(scenario_id)},
        files={"file": ("a.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["engine"] == "local"
    hotwords = calls["hotwords"]
    assert "oat milk" in hotwords
    assert "Can I have it with oat milk?" in hotwords


def test_transcribe_without_scenario_sends_no_hotwords(auth_client, monkeypatch):
    calls = _enable_local(monkeypatch)
    response = auth_client.post(
        "/api/audio/transcribe",
        data={"engine": "local"},
        files={"file": ("a.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 200, response.text
    assert calls["hotwords"] == ""


def test_transcribe_falls_back_to_local_when_model_fails(auth_client, monkeypatch):
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
        assert calls["count"] == 0
    finally:
        _clear_override(key)
        P.reset_stt_cache()


def test_transcribe_unsupported_model_reports_503(auth_client, monkeypatch):
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
    _enable_local(monkeypatch)
    body = auth_client.get("/api/audio/stt").json()
    ids = [item["id"] for item in body["engines"]]
    assert "local" in ids
    assert body["available"] is False
    assert body["engine"] == ""
    assert body["local_model"] == "base.en"


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


_PROVIDER_OVERRIDE_KEY = None


def _fake_provider(handler, **kwargs):
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
    assert P._clean_transcript("我想点一杯拿铁。", "en") == ""
    assert P._clean_transcript("嗯，那个我觉得。", "en") == ""


def test_transcript_cleaning_keeps_english_part_of_mixed():
    assert (
        P._clean_transcript("你好，I would like a coffee", "en")
        == "I would like a coffee"
    )


def test_transcript_cleaning_respects_non_english_language():
    assert P._clean_transcript("你好，我想点一杯拿铁。", "zh") == "你好，我想点一杯拿铁。"


def test_stt_status_names_the_users_model():
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
    body = request.read().decode("utf-8", errors="ignore")
    marker = f'name="{name}"'
    index = body.find(marker)
    if index == -1:
        return ""
    rest = body[index + len(marker) :]
    return rest.split("\r\n\r\n", 1)[1].split("\r\n", 1)[0]
