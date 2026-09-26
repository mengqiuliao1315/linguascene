import uuid


def _payload(prefix: str = "user") -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "username": f"{prefix}{suffix}",
        "email": f"{prefix}{suffix}@example.com",
        "password": "tester12345",
    }


def test_register_creates_user(client):
    response = client.post("/api/auth/register", json=_payload())
    assert response.status_code == 201
    assert response.json()["access_token"]


def test_register_rejects_duplicate_email(client):
    payload = _payload()
    assert client.post("/api/auth/register", json=payload).status_code == 201

    duplicate = {**_payload(), "email": payload["email"]}
    assert client.post("/api/auth/register", json=duplicate).status_code == 400


def test_register_rejects_duplicate_username(client):
    payload = _payload()
    assert client.post("/api/auth/register", json=payload).status_code == 201

    duplicate = {**_payload(), "username": payload["username"]}
    assert client.post("/api/auth/register", json=duplicate).status_code == 400


def test_login_success(client):
    payload = _payload()
    client.post("/api/auth/register", json=payload)

    response = client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_wrong_password(client):
    payload = _payload()
    client.post("/api/auth/register", json=payload)

    response = client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": "wrongpassword"},
    )
    assert response.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/users/me").status_code == 401


def test_me_returns_profile(auth_client):
    response = auth_client.get("/api/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "USER"
    assert body["cefr_level"]


def test_onboarding_updates_level(auth_client):
    response = auth_client.post(
        "/api/auth/onboarding",
        json={"cefr_level": "B2", "interests": ["Travel", "Workplace"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cefr_level"] == "B2"
    assert "Travel" in body["interests"]


def test_update_me_changes_level(auth_client):
    response = auth_client.patch("/api/users/me", json={"cefr_level": "A2"})
    assert response.status_code == 200
    assert response.json()["cefr_level"] == "A2"
