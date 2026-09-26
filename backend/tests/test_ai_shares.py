"""AI 模型分享：分享、停用、删除、采纳、弹窗关闭、解析优先级。

只验证接口与解析行为，不发起真实模型请求（测试环境 AI_PROVIDER=mock）。
"""

import uuid

from app.core.crypto import decrypt_secret


def _register_and_login(client, prefix: str) -> dict:
    """注册一个普通用户并返回其 Authorization 头。"""
    suffix = uuid.uuid4().hex[:8]
    username = f"{prefix}{suffix}"
    email = f"{username}@example.com"
    password = "sharetest12345"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    token = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_config(
    client,
    headers=None,
    *,
    name="我的供应商",
    model="shared-model",
    api_key="sk-shared-key",
) -> dict:
    """配好一条自己的供应商，返回它。"""
    response = client.post(
        "/api/ai-settings/configs",
        headers=headers,
        json={
            "name": name,
            "base_url": "https://api.shared.example/v1",
            "api_key": api_key,
            "api_format": "openai",
            "models": [model],
            "active_model": model,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["configs"][-1]


def _new_share(client, headers=None, *, title="分享的模型", **extra) -> dict:
    config = _make_config(client, headers, model=extra.pop("model", "shared-model"))
    payload = {"config_id": config["id"], "title": title}
    payload.update(extra)
    response = client.post("/api/ai-shares", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ 分享增删


def test_create_share_never_returns_key(auth_client):
    body = _new_share(auth_client, {}, title="我的 DeepSeek", note="随便用，别刷太多")
    assert body["title"] == "我的 DeepSeek"
    assert body["active_model"] == "shared-model"
    assert body["is_active"] is True
    assert body["is_mine"] is True
    # 明文 Key 绝不能出现在响应里
    assert "sk-shared-key" not in str(body)
    assert body["key_hint"].startswith("••••")


def test_share_stored_encrypted(auth_client):
    _new_share(auth_client, {}, title="加密检查")

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.ai_config import AiShare

    db = SessionLocal()
    try:
        share = db.execute(
            select(AiShare).order_by(AiShare.id.desc())
        ).scalars().first()
        assert share is not None
        assert "sk-shared-key" not in share.api_key_encrypted
        assert decrypt_secret(share.api_key_encrypted) == "sk-shared-key"
    finally:
        db.close()


def test_share_requires_own_config(auth_client):
    """分享的是自己的一条供应商，不存在就 404。"""
    response = auth_client.post(
        "/api/ai-shares", json={"config_id": 999999, "title": "没有这个供应商"}
    )
    assert response.status_code == 404


def test_share_rejected_when_config_has_no_model(auth_client):
    config = _make_config(auth_client, {})

    from app.core.database import SessionLocal
    from app.models.ai_config import AiProviderConfig

    db = SessionLocal()
    try:
        row = db.get(AiProviderConfig, config["id"])
        row.models = "[]"
        row.active_model = ""
        db.commit()
    finally:
        db.close()

    response = auth_client.post(
        "/api/ai-shares", json={"config_id": config["id"], "title": "空模型"}
    )
    assert response.status_code == 400


def test_only_owner_can_toggle_or_delete(auth_client, client):
    share = _new_share(auth_client, {}, title="只有我能改")

    other = _register_and_login(client, "other")
    assert client.patch(
        f"/api/ai-shares/{share['id']}", headers=other, json={"is_active": False}
    ).status_code == 404
    assert client.delete(
        f"/api/ai-shares/{share['id']}", headers=other
    ).status_code == 404


def test_toggle_off_hides_from_others(auth_client, client):
    share = _new_share(auth_client, {}, title="待停用")

    other = _register_and_login(client, "viewer")
    available = client.get("/api/ai-shares", headers=other).json()["available"]
    assert any(s["id"] == share["id"] for s in available)

    auth_client.patch(f"/api/ai-shares/{share['id']}", json={"is_active": False})
    available = client.get("/api/ai-shares", headers=other).json()["available"]
    assert all(s["id"] != share["id"] for s in available)


def test_delete_share_removes_for_everyone(auth_client, client):
    share = _new_share(auth_client, {}, title="待删除")

    other = _register_and_login(client, "delviewer")
    assert any(
        s["id"] == share["id"]
        for s in client.get("/api/ai-shares", headers=other).json()["available"]
    )

    assert auth_client.delete(f"/api/ai-shares/{share['id']}").status_code == 200

    body = client.get("/api/ai-shares", headers=other).json()
    assert all(s["id"] != share["id"] for s in body["available"])
    assert client.post(
        f"/api/ai-shares/{share['id']}/adopt", headers=other
    ).status_code == 404


# ------------------------------------------------------------------ 采纳与解析


def test_adopt_switches_provider_to_share(auth_client, client):
    share = _new_share(auth_client, {}, title="分享的模型")

    adopter = _register_and_login(client, "adopter")
    response = client.post(f"/api/ai-shares/{share['id']}/adopt", headers=adopter)
    assert response.status_code == 200, response.text

    status = client.get("/api/ai-settings", headers=adopter).json()
    assert status["active_source"] == "share"
    assert status["active_label"] == "分享的模型"
    assert status["active_share_id"] == share["id"]
    assert status["adopted_share"]["id"] == share["id"]


def test_cannot_adopt_own_share(auth_client):
    share = _new_share(auth_client, {}, title="自己的")
    response = auth_client.post(f"/api/ai-shares/{share['id']}/adopt")
    assert response.status_code == 400


def test_owner_deleting_share_falls_back_for_adopter(auth_client, client):
    """分享者删除后，采纳者自动回落，不再指向失效分享。"""
    share = _new_share(auth_client, {}, title="会被删掉")

    adopter = _register_and_login(client, "fallback")
    client.post(f"/api/ai-shares/{share['id']}/adopt", headers=adopter)
    assert (
        client.get("/api/ai-settings", headers=adopter).json()["active_source"]
        == "share"
    )

    auth_client.delete(f"/api/ai-shares/{share['id']}")

    status = client.get("/api/ai-settings", headers=adopter).json()
    # 分享没了，测试环境回落到离线规则引擎
    assert status["active_source"] == "mock"
    # 采纳记录被级联清掉，状态里不再有失效分享
    assert status["adopted_share"] is None


def test_own_share_not_in_available_list(auth_client):
    """自己的分享只出现在 mine 里，不出现在 available 里。"""
    share = _new_share(auth_client, {}, title="自己的分享")
    body = auth_client.get("/api/ai-shares").json()
    assert any(s["id"] == share["id"] for s in body["mine"])
    assert all(s["id"] != share["id"] for s in body["available"])


# ------------------------------------------------------------------ 登录弹窗


def test_prompt_shows_share_for_unconfigured_user(auth_client, client):
    _new_share(auth_client, {}, title="新手可用", note="给新同学用")

    newbie = _register_and_login(client, "newbie")
    prompt = client.get("/api/ai-shares/prompt", headers=newbie).json()
    assert prompt["available"] is True
    assert prompt["share"]["active_model"] == "shared-model"
    assert prompt["share"]["owner_name"]


def test_prompt_skipped_when_user_has_own_config(auth_client, client):
    _new_share(auth_client, {}, title="别人分享的")

    configured = _register_and_login(client, "configured")
    _make_config(client, configured, name="我自己的", model="mine")
    prompt = client.get("/api/ai-shares/prompt", headers=configured).json()
    assert prompt["available"] is False


def test_dismissed_share_not_prompted_again(auth_client, client):
    share = _new_share(auth_client, {}, title="会被关掉")

    user = _register_and_login(client, "dismisser")
    first = client.get("/api/ai-shares/prompt", headers=user).json()
    assert first["available"] is True
    assert first["share"]["id"] == share["id"]

    client.post(f"/api/ai-shares/{share['id']}/dismiss", headers=user)

    # 会话级共享测试库，其他用例可能留下别的分享；只断言这条不再出现。
    second = client.get("/api/ai-shares/prompt", headers=user).json()
    assert second["share"] is None or second["share"]["id"] != share["id"]

    available = client.get("/api/ai-shares", headers=user).json()["available"]
    assert all(s["id"] != share["id"] for s in available)


def test_disabled_share_not_prompted(auth_client, client):
    share = _new_share(auth_client, {}, title="停用的")
    auth_client.patch(f"/api/ai-shares/{share['id']}", json={"is_active": False})

    user = _register_and_login(client, "offviewer")
    prompt = client.get("/api/ai-shares/prompt", headers=user).json()
    assert prompt["share"] is None or prompt["share"]["id"] != share["id"]
    assert all(
        s["id"] != share["id"]
        for s in client.get("/api/ai-shares", headers=user).json()["available"]
    )


# ------------------------------------------------------------------ 解析单元测试


def test_explicit_selection_beats_auto_pick():
    """同时有自己的供应商和采纳的分享时，以用户选中的那条为准。"""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.ai_config import AiShare
    from app.models.user import User
    from app.services import ai_config_service

    db = SessionLocal()
    try:
        owner = db.execute(
            select(User).where(User.username.like("tester%")).limit(1)
        ).scalars().first()
        assert owner is not None, "conftest 应已注册 tester 用户"

        share = AiShare(
            owner_id=owner.id,
            title="unit-share",
            base_url="https://api.unit.example/v1",
            api_key_encrypted=ai_config_service.encrypt_secret("sk-unit"),
            models='["unit-shared"]',
            active_model="unit-shared",
            api_format="openai",
            is_active=True,
        )
        db.add(share)
        db.flush()

        suffix = uuid.uuid4().hex[:8]
        adopter = User(
            username=f"unit{suffix}",
            email=f"unit{suffix}@example.com",
            password_hash="x",
        )
        db.add(adopter)
        db.flush()

        # 采纳分享后生效的是分享
        ai_config_service.adopt_share(db, adopter, share)
        db.flush()
        resolved = ai_config_service.resolve_provider(db, adopter)
        assert resolved.source == "share"
        assert resolved.provider.model == "unit-shared"

        # 添了自己的供应商并选中后，改用自己的
        config = ai_config_service.create_config(
            db,
            adopter,
            name="自己的",
            base_url="https://api.self.example/v1",
            api_key="sk-self",
            models=["self-model"],
        )
        ai_config_service.set_active_config(db, adopter, config)
        db.flush()
        resolved = ai_config_service.resolve_provider(db, adopter)
        assert resolved.source == "user"
        assert resolved.provider.model == "self-model"

        db.rollback()
    finally:
        db.close()


def test_disabled_share_provider_is_none():
    """停用的分享不再能构造 provider。"""
    from app.services import ai_config_service
    from app.models.ai_config import AiShare

    share = AiShare(
        owner_id=1,
        title="disabled",
        base_url="https://api.example.com/v1",
        api_key_encrypted=ai_config_service.encrypt_secret("sk-x"),
        models='["m"]',
        active_model="m",
        api_format="openai",
        is_active=False,
    )
    assert ai_config_service.share_provider(None, share) is None
