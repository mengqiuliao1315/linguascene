"""登录令牌版本、密码长度与自定义模型地址的安全约束。"""

import pytest

from app.ai import provider as P
from app.core.security import apply_password, create_access_token, hash_password


def test_password_change_revokes_existing_token(auth_client):
    me = auth_client.get("/api/users/me")
    assert me.status_code == 200

    changed = auth_client.post(
        "/api/users/me/password",
        json={"current_password": "tester12345", "new_password": "tester67890"},
    )
    assert changed.status_code == 200
    assert auth_client.get("/api/users/me").status_code == 401

    login = auth_client.post(
        "/api/auth/login",
        json={"email": me.json()["email"], "password": "tester67890"},
    )
    assert login.status_code == 200
    auth_client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    assert auth_client.get("/api/users/me").status_code == 200


def test_admin_reset_revokes_existing_token(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "revokeme",
            "email": "revokeme@example.com",
            "password": "oldpassword1",
        },
    ).json()
    login = admin_client.post(
        "/api/auth/login",
        json={"email": "revokeme@example.com", "password": "oldpassword1"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert admin_client.get("/api/users/me", headers=headers).status_code == 200

    reset = admin_client.post(
        f"/api/admin/users/{created['id']}/reset-password",
        json={"password": "newpassword2"},
    )
    assert reset.status_code == 200
    assert admin_client.get("/api/users/me", headers=headers).status_code == 401


def test_hash_password_rejects_overlong_utf8():
    with pytest.raises(ValueError):
        hash_password("é" * 40)


def test_create_access_token_embeds_version():
    token = create_access_token("12", token_version=3)
    from app.core.security import decode_access_token

    assert decode_access_token(token) == ("12", 3)


def test_assert_public_http_url_blocks_loopback():
    with pytest.raises(P.AIProviderError):
        P.assert_public_http_url("http://127.0.0.1/v1")
    with pytest.raises(P.AIProviderError):
        P.assert_public_http_url("http://localhost/v1")
    with pytest.raises(P.AIProviderError):
        P.assert_public_http_url("http://[::1]/v1")


def test_assert_public_http_url_blocks_private_literal():
    with pytest.raises(P.AIProviderError):
        P.assert_public_http_url("http://10.0.0.8/v1")
    with pytest.raises(P.AIProviderError):
        P.assert_public_http_url("http://192.168.1.2/v1")


def test_assert_public_http_url_blocks_resolved_private(monkeypatch):
    monkeypatch.setattr(
        P.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("10.0.0.8", 443))],
    )
    with pytest.raises(P.AIProviderError):
        P.assert_public_http_url("https://evil.example/v1")


def test_create_config_rejects_loopback(auth_client):
    response = auth_client.post(
        "/api/ai-settings/configs",
        json={
            "name": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "sk-test",
            "api_format": "openai",
            "models": ["local-model"],
            "active_model": "local-model",
        },
    )
    assert response.status_code == 400
    assert "内网" in response.json()["detail"] or "本机" in response.json()["detail"]


def test_apply_password_bumps_token_version():
    class Dummy:
        password_hash = ""
        password_enc = None
        password_updated_at = None
        token_version = 0

    user = Dummy()
    apply_password(user, "password12345")
    assert user.token_version == 1
    apply_password(user, "password67890")
    assert user.token_version == 2
