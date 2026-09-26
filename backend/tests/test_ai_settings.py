"""AI 模型配置：多供应商接入、切换与回落。

一个用户可以添加多个供应商，每个供应商各含多个模型；
这里只验证配置解析与接口行为，不发起真实模型请求。
"""

from app.ai.provider import MockAIProvider
from app.core.crypto import decrypt_secret, encrypt_secret
from app.services import ai_config_service


def _payload(**over) -> dict:
    payload = {
        "name": "我的供应商",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-secret-value",
        "api_format": "openai",
        "models": ["example-model"],
        "active_model": "example-model",
    }
    payload.update(over)
    return payload


# ------------------------------------------------------------------ 加密


def test_secret_roundtrip():
    token = encrypt_secret("sk-abc123")
    assert token != "sk-abc123"
    assert decrypt_secret(token) == "sk-abc123"


def test_decrypt_returns_none_on_garbage():
    assert decrypt_secret("not-a-valid-token") is None
    assert decrypt_secret("") is None


# ------------------------------------------------------------------ 接口


def test_status_defaults_to_no_config(auth_client):
    body = auth_client.get("/api/ai-settings").json()
    assert body["configs"] == []
    # 测试环境 AI_PROVIDER=mock，没有自己的配置时走离线规则引擎
    assert body["active_source"] == "mock"


def test_create_config_never_returns_key(auth_client):
    resp = auth_client.post("/api/ai-settings/configs", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    config = body["configs"][-1]
    assert config["active_model"] == "example-model"
    assert config["models"] == ["example-model"]
    # 明文 Key 绝不能出现在响应里
    assert "sk-secret-value" not in resp.text
    assert config["key_hint"]
    # 新加的供应商自动成为当前使用的那条
    assert body["active_source"] == "user"
    assert body["active_config_id"] == config["id"]

    auth_client.delete(f"/api/ai-settings/configs/{config['id']}")


def test_config_stored_encrypted(auth_client):
    auth_client.post("/api/ai-settings/configs", json=_payload())

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.ai_config import AiProviderConfig

    db = SessionLocal()
    try:
        config = db.execute(
            select(AiProviderConfig).order_by(AiProviderConfig.id.desc())
        ).scalars().first()
        assert config is not None
        assert "sk-secret-value" not in config.api_key_encrypted
        assert decrypt_secret(config.api_key_encrypted) == "sk-secret-value"
    finally:
        db.close()


def test_can_add_multiple_configs(auth_client):
    """每个人都可以添加多个模型供应商。"""
    first = auth_client.post(
        "/api/ai-settings/configs",
        json=_payload(name="DeepSeek", models=["deepseek-chat"], active_model="deepseek-chat"),
    ).json()
    second = auth_client.post(
        "/api/ai-settings/configs",
        json=_payload(name="Kimi", models=["moonshot-v1-8k"], active_model="moonshot-v1-8k"),
    ).json()

    assert len(second["configs"]) == len(first["configs"]) + 1
    names = [c["name"] for c in second["configs"]]
    assert "DeepSeek" in names and "Kimi" in names
    # 最近添加的成为当前使用
    assert second["active_config_id"] == second["configs"][-1]["id"]

    for config in second["configs"]:
        auth_client.delete(f"/api/ai-settings/configs/{config['id']}")


def test_config_holds_multiple_models(auth_client):
    """一个供应商下可以存多个模型，并指定当前用哪个。"""
    body = auth_client.post(
        "/api/ai-settings/configs",
        json=_payload(
            models=["deepseek-chat", "deepseek-reasoner"],
            active_model="deepseek-reasoner",
        ),
    ).json()
    config = body["configs"][-1]
    assert config["models"] == ["deepseek-chat", "deepseek-reasoner"]
    assert config["active_model"] == "deepseek-reasoner"

    # 切到另一个模型不用改 Key
    updated = auth_client.put(
        f"/api/ai-settings/configs/{config['id']}",
        json=_payload(
            models=["deepseek-chat", "deepseek-reasoner"],
            active_model="deepseek-chat",
            api_key="",
        ),
    ).json()
    assert updated["configs"][-1]["active_model"] == "deepseek-chat"

    auth_client.delete(f"/api/ai-settings/configs/{config['id']}")


def test_empty_key_on_edit_keeps_existing(auth_client):
    body = auth_client.post("/api/ai-settings/configs", json=_payload()).json()
    config = body["configs"][-1]

    # 只改模型名，Key 留空
    auth_client.put(
        f"/api/ai-settings/configs/{config['id']}",
        json=_payload(models=["m2"], active_model="m2", api_key=""),
    )

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.ai_config import AiProviderConfig

    db = SessionLocal()
    try:
        row = db.execute(
            select(AiProviderConfig).where(AiProviderConfig.id == config["id"])
        ).scalar_one()
        assert decrypt_secret(row.api_key_encrypted) == "sk-secret-value"
    finally:
        db.close()

    auth_client.delete(f"/api/ai-settings/configs/{config['id']}")


def test_create_config_requires_key_and_model(auth_client):
    assert (
        auth_client.post(
            "/api/ai-settings/configs", json=_payload(api_key="")
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            "/api/ai-settings/configs", json=_payload(models=[], active_model="")
        ).status_code
        == 400
    )


def test_switch_active_between_configs(auth_client):
    first = auth_client.post(
        "/api/ai-settings/configs",
        json=_payload(name="A", models=["a-model"], active_model="a-model"),
    ).json()
    a_id = first["configs"][-1]["id"]
    second = auth_client.post(
        "/api/ai-settings/configs",
        json=_payload(name="B", models=["b-model"], active_model="b-model"),
    ).json()
    b_id = second["configs"][-1]["id"]

    switched = auth_client.patch(
        "/api/ai-settings/active", json={"config_id": a_id}
    ).json()
    assert switched["active_config_id"] == a_id
    assert switched["active_label"] == "A"

    # 清空选择后回落到自动挑选
    auto = auth_client.patch("/api/ai-settings/active", json={}).json()
    assert auto["active_source"] == "user"

    auth_client.delete(f"/api/ai-settings/configs/{a_id}")
    auth_client.delete(f"/api/ai-settings/configs/{b_id}")


def test_delete_active_config_falls_back(auth_client):
    body = auth_client.post("/api/ai-settings/configs", json=_payload()).json()
    config_id = body["configs"][-1]["id"]

    after = auth_client.delete(f"/api/ai-settings/configs/{config_id}").json()
    assert after["configs"] == []
    assert after["active_source"] == "mock"


def test_delete_missing_config_404(auth_client):
    assert auth_client.delete("/api/ai-settings/configs/999999").status_code == 404


def test_active_config_rejected_when_incomplete(auth_client):
    """没有可用的 Key/模型时不能切过去。"""
    body = auth_client.post("/api/ai-settings/configs", json=_payload()).json()
    config_id = body["configs"][-1]["id"]

    # 人为把模型列表清空，模拟配置失效
    from app.core.database import SessionLocal
    from app.models.ai_config import AiProviderConfig

    db = SessionLocal()
    try:
        row = db.get(AiProviderConfig, config_id)
        row.models = "[]"
        row.active_model = ""
        db.commit()
    finally:
        db.close()

    assert (
        auth_client.patch(
            "/api/ai-settings/active", json={"config_id": config_id}
        ).status_code
        == 400
    )


# ------------------------------------------------------------------ 解析优先级


def select_user_query():
    from sqlalchemy import select

    from app.core.config import settings
    from app.models.user import User

    return select(User).where(User.email == settings.admin_email)


def test_resolve_uses_selected_config():
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.execute(select_user_query()).scalar_one()

        first = ai_config_service.create_config(
            db,
            user,
            name="A",
            base_url="https://api.a.example/v1",
            api_key="sk-a",
            models=["a-model"],
        )
        second = ai_config_service.create_config(
            db,
            user,
            name="B",
            base_url="https://api.b.example/v1",
            api_key="sk-b",
            models=["b-model"],
        )
        db.commit()

        # 没选过：用第一条
        resolved = ai_config_service.resolve_provider(db, user)
        assert resolved.source == "user"
        assert resolved.provider.model == "a-model"

        # 选第二条
        ai_config_service.set_active_config(db, user, second)
        db.commit()
        resolved = ai_config_service.resolve_provider(db, user)
        assert resolved.provider.model == "b-model"

        # 收尾
        for config in (first, second):
            ai_config_service.delete_config(db, config)
        user.ai_active_config_id = None
        db.commit()
    finally:
        db.close()


def test_resolve_falls_back_to_mock_without_any_config():
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        resolved = ai_config_service.resolve_provider(db, None)
        # 测试环境 AI_PROVIDER=mock
        assert isinstance(resolved.provider, MockAIProvider)
        assert resolved.source == "mock"
    finally:
        db.close()


def test_resolve_skips_incomplete_config():
    """模型列表为空的配置不该被当成可用来源。"""
    from app.core.database import SessionLocal
    from app.models.ai_config import AiProviderConfig

    db = SessionLocal()
    try:
        user = db.execute(select_user_query()).scalar_one()
        config = ai_config_service.create_config(
            db,
            user,
            name="空模型",
            base_url="https://api.empty.example/v1",
            api_key="sk-empty",
            models=["m"],
        )
        db.commit()
        assert ai_config_service.resolve_provider(db, user).source == "user"

        config.models = "[]"
        config.active_model = ""
        db.commit()
        assert ai_config_service.resolve_provider(db, user).source == "mock"

        db.delete(config)
        db.commit()
    finally:
        db.close()


def test_models_list_helpers_handle_bad_data():
    assert ai_config_service.load_models(None) == []
    assert ai_config_service.load_models("") == []
    assert ai_config_service.load_models("not json") == []
    assert ai_config_service.load_models('{"a": 1}') == []
    # 库里存的内容一律由 dump_models 写过，读取时只保证"能解析成 list"，
    # 空串/空白项直接丢掉。
    assert ai_config_service.load_models('["m1", "m1", " m2 "]') == [
        "m1",
        "m1",
        " m2 ",
    ]
    assert ai_config_service.load_models('["m1", "  ", ""]') == ["m1"]
    # 写入时统一去重、去首尾空白
    assert ai_config_service.dump_models(["m1", " m1 ", "m2"]) == '["m1", "m2"]'


def test_broken_config_does_not_break_the_chain():
    """一条地址坏掉的供应商只该自己不可用，不能把整站 AI 变成 500。

    回归：坏地址以前会从 config_provider 一路抛到接口层，于是「库里有这么
    一条」的表现是每个 AI 请求都 500，而不是跨过它回落到离线规则引擎。
    保存接口现在会拦住坏地址（见 test_create_config_rejects_unusable_base_url），
    但老数据、手工改过的库仍然可能带进来，所以这条防线要独立成立。
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.execute(select_user_query()).scalar_one()
        config = ai_config_service.create_config(
            db,
            user,
            name="坏的",
            base_url="https://api.live.example/v1",
            api_key="sk-live",
            models=["m1"],
            active_model="m1",
        )
        db.commit()
        assert ai_config_service.config_provider(config) is not None

        # 模拟库里被改坏 / 老数据：归一化看不下去的地址
        config.base_url = "http://[::1/v1"
        db.commit()

        assert ai_config_service.config_provider(config) is None
        assert ai_config_service.resolve_provider(db, user).source == "mock"

        db.delete(config)
        db.commit()
    finally:
        db.close()
