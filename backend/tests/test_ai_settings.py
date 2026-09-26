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


def test_secret_roundtrip():
    token = encrypt_secret("sk-abc123")
    assert token != "sk-abc123"
    assert decrypt_secret(token) == "sk-abc123"


def test_decrypt_returns_none_on_garbage():
    assert decrypt_secret("not-a-valid-token") is None
    assert decrypt_secret("") is None


def test_status_defaults_to_no_config(auth_client):
    body = auth_client.get("/api/ai-settings").json()
    assert body["configs"] == []
    assert body["active_source"] == "mock"


def test_create_config_never_returns_key(auth_client):
    resp = auth_client.post("/api/ai-settings/configs", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    config = body["configs"][-1]
    assert config["active_model"] == "example-model"
    assert config["models"] == ["example-model"]
    assert "sk-secret-value" not in resp.text
    assert config["key_hint"]
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
    assert second["active_config_id"] == second["configs"][-1]["id"]

    for config in second["configs"]:
        auth_client.delete(f"/api/ai-settings/configs/{config['id']}")


def test_config_holds_multiple_models(auth_client):
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
    body = auth_client.post("/api/ai-settings/configs", json=_payload()).json()
    config_id = body["configs"][-1]["id"]

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

        resolved = ai_config_service.resolve_provider(db, user)
        assert resolved.source == "user"
        assert resolved.provider.model == "a-model"

        ai_config_service.set_active_config(db, user, second)
        db.commit()
        resolved = ai_config_service.resolve_provider(db, user)
        assert resolved.provider.model == "b-model"

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
        assert isinstance(resolved.provider, MockAIProvider)
        assert resolved.source == "mock"
    finally:
        db.close()


def test_resolve_skips_incomplete_config():
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
    assert ai_config_service.load_models('["m1", "m1", " m2 "]') == [
        "m1",
        "m1",
        " m2 ",
    ]
    assert ai_config_service.load_models('["m1", "  ", ""]') == ["m1"]
    assert ai_config_service.dump_models(["m1", " m1 ", "m2"]) == '["m1", "m2"]'


def test_broken_config_does_not_break_the_chain():
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

        config.base_url = "http://[::1/v1"
        db.commit()

        assert ai_config_service.config_provider(config) is None
        assert ai_config_service.resolve_provider(db, user).source == "mock"

        db.delete(config)
        db.commit()
    finally:
        db.close()
