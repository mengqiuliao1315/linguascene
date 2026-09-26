import pytest


def test_non_admin_cannot_access_admin_api(auth_client):
    assert auth_client.get("/api/admin/users").status_code == 403


def test_admin_can_list_users(admin_client):
    response = admin_client.get("/api/admin/users")
    assert response.status_code == 200
    users = response.json()
    assert any(u["role"] == "ADMIN" for u in users)


def test_admin_creates_user_and_new_user_can_login(admin_client):
    response = admin_client.post(
        "/api/admin/users",
        json={
            "username": "student1",
            "email": "student1@example.com",
            "password": "student12345",
            "cefr_level": "A2",
            "role": "USER",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["username"] == "student1"
    assert created["password"] == "student12345"

    login = admin_client.post(
        "/api/auth/login",
        json={"email": "student1@example.com", "password": "student12345"},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_create_user_rejects_duplicate(admin_client):
    payload = {
        "username": "dup1",
        "email": "dup1@example.com",
        "password": "dup12345678",
    }
    assert admin_client.post("/api/admin/users", json=payload).status_code == 201
    assert admin_client.post("/api/admin/users", json=payload).status_code == 400


def test_created_user_starts_at_zero_progress(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "fresh1",
            "email": "fresh1@example.com",
            "password": "fresh1234567",
            "cefr_level": "B2",
        },
    ).json()

    listed = {u["id"]: u for u in admin_client.get("/api/admin/users").json()}
    user = listed[created["id"]]
    assert user["xp"] == 0
    assert user["streak"] == 0
    assert user["cefr_level"] == "B2"
    assert user["role"] == "USER"


def test_admin_reset_password(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "resetme",
            "email": "resetme@example.com",
            "password": "oldpassword1",
        },
    ).json()

    response = admin_client.post(
        f"/api/admin/users/{created['id']}/reset-password",
        json={"password": "newpassword2"},
    )
    assert response.status_code == 200

    assert (
        admin_client.post(
            "/api/auth/login",
            json={"email": "resetme@example.com", "password": "oldpassword1"},
        ).status_code
        == 401
    )
    assert (
        admin_client.post(
            "/api/auth/login",
            json={"email": "resetme@example.com", "password": "newpassword2"},
        ).status_code
        == 200
    )


def test_admin_list_does_not_return_password(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "showme",
            "email": "showme@example.com",
            "password": "showme12345",
        },
    ).json()
    assert created["password"] == "showme12345"

    listed = {u["id"]: u for u in admin_client.get("/api/admin/users").json()}
    assert "password" not in listed[created["id"]]


def test_admin_reset_returns_password_once(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "syncme",
            "email": "syncme@example.com",
            "password": "oldpassword1",
        },
    ).json()

    reset = admin_client.post(
        f"/api/admin/users/{created['id']}/reset-password",
        json={"password": "newpassword2"},
    )
    assert reset.status_code == 200
    assert reset.json()["password"] == "newpassword2"
    listed = {u["id"]: u for u in admin_client.get("/api/admin/users").json()}
    assert "password" not in listed[created["id"]]


def test_admin_sees_identifier_and_password_changes_from_user(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "selfupdate",
            "email": "selfupdate@example.com",
            "password": "oldpassword1",
        },
    ).json()

    token = admin_client.post(
        "/api/auth/login",
        json={"email": "selfupdate@example.com", "password": "oldpassword1"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (
        admin_client.patch(
            "/api/users/me",
            headers=headers,
            json={
                "username": "selfupdated",
                "email": "selfupdated@example.com",
                "current_password": "oldpassword1",
            },
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            "/api/users/me/password",
            headers=headers,
            json={
                "current_password": "oldpassword1",
                "new_password": "brandnew12345",
            },
        ).status_code
        == 200
    )

    listed = {u["id"]: u for u in admin_client.get("/api/admin/users").json()}
    row = listed[created["id"]]
    assert row["username"] == "selfupdated"
    assert row["email"] == "selfupdated@example.com"
    assert "password" not in row
    assert row["password_updated_at"]


def test_admin_can_edit_identifiers_via_patch(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "oldname",
            "email": "oldname@example.com",
            "password": "oldpassword1",
        },
    ).json()

    response = admin_client.patch(
        f"/api/admin/users/{created['id']}",
        json={"username": "newname", "email": "newname@example.com"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == "newname"
    assert body["email"] == "newname@example.com"

    assert (
        admin_client.post(
            "/api/auth/login",
            json={"email": "newname@example.com", "password": "oldpassword1"},
        ).status_code
        == 200
    )


def test_admin_edit_identifier_rejects_duplicate(admin_client):
    first = admin_client.post(
        "/api/admin/users",
        json={
            "username": "takenname",
            "email": "takenname@example.com",
            "password": "password12345",
        },
    ).json()
    second = admin_client.post(
        "/api/admin/users",
        json={
            "username": "othername",
            "email": "othername@example.com",
            "password": "password12345",
        },
    ).json()

    clash = admin_client.patch(
        f"/api/admin/users/{second['id']}", json={"username": first["username"]}
    )
    assert clash.status_code == 400


def test_password_updated_at_tracks_changes(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "stampme",
            "email": "stampme@example.com",
            "password": "password12345",
        },
    ).json()

    listed = {u["id"]: u for u in admin_client.get("/api/admin/users").json()}
    first_stamp = listed[created["id"]]["password_updated_at"]
    assert first_stamp

    admin_client.post(
        f"/api/admin/users/{created['id']}/reset-password",
        json={"password": "anotherpass123"},
    )
    listed = {u["id"]: u for u in admin_client.get("/api/admin/users").json()}
    assert listed[created["id"]]["password_updated_at"] >= first_stamp


def test_admin_can_edit_password_via_patch(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "editme",
            "email": "editme@example.com",
            "password": "oldpassword1",
        },
    ).json()

    response = admin_client.patch(
        f"/api/admin/users/{created['id']}",
        json={"password": "resetbyadmin1", "cefr_level": "C1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "password" not in body
    assert body["cefr_level"] == "C1"

    assert (
        admin_client.post(
            "/api/auth/login",
            json={"email": "editme@example.com", "password": "resetbyadmin1"},
        ).status_code
        == 200
    )


def test_admin_cannot_demote_self_via_patch(admin_client, admin_user):
    response = admin_client.patch(
        f"/api/admin/users/{admin_user.id}", json={"role": "USER"}
    )
    assert response.status_code == 400


def test_admin_can_promote_user(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "promoteme",
            "email": "promoteme@example.com",
            "password": "promote12345",
        },
    ).json()

    response = admin_client.patch(
        f"/api/admin/users/{created['id']}/role", json={"role": "ADMIN"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"


def test_admin_cannot_delete_self(admin_client, admin_user):
    assert admin_client.delete(f"/api/admin/users/{admin_user.id}").status_code == 400


def test_admin_cannot_demote_self(admin_client, admin_user):
    response = admin_client.patch(
        f"/api/admin/users/{admin_user.id}/role", json={"role": "USER"}
    )
    assert response.status_code == 400


def test_admin_deletes_user_and_its_data(admin_client):
    created = admin_client.post(
        "/api/admin/users",
        json={
            "username": "deleteme",
            "email": "deleteme@example.com",
            "password": "deleteme12345",
        },
    ).json()

    assert admin_client.delete(f"/api/admin/users/{created['id']}").status_code == 204

    emails = [u["email"] for u in admin_client.get("/api/admin/users").json()]
    assert "deleteme@example.com" not in emails

    assert (
        admin_client.post(
            "/api/auth/login",
            json={"email": "deleteme@example.com", "password": "deleteme12345"},
        ).status_code
        == 401
    )


def test_registration_returns_403_when_disabled(client, monkeypatch):
    from app.api.routes import auth as auth_route

    monkeypatch.setattr(auth_route.settings, "allow_public_registration", False)
    assert auth_route.settings.allow_public_registration is False

    response = client.post(
        "/api/auth/register",
        json={
            "username": "selfsignup",
            "email": "selfsignup@example.com",
            "password": "selfsignup12345",
        },
    )
    assert response.status_code == 403, response.text


def test_registration_default_is_closed():
    from app.core.config import Settings

    assert Settings.model_fields["allow_public_registration"].default is False


def test_auth_config_reports_registration_flag(client):
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    assert "allow_public_registration" in response.json()
