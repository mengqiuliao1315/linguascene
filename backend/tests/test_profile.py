import io


def test_plain_fields_still_update_without_password(auth_client):
    response = auth_client.patch("/api/users/me", json={"cefr_level": "B2"})
    assert response.status_code == 200
    assert response.json()["cefr_level"] == "B2"


def test_change_username_and_email(auth_client):
    before = auth_client.get("/api/users/me").json()

    response = auth_client.patch(
        "/api/users/me",
        json={
            "username": "renamed",
            "email": "renamed@example.com",
            "current_password": "tester12345",
        },
    )
    assert response.status_code == 200, response.text

    after = response.json()
    assert after["username"] == "renamed"
    assert after["email"] == "renamed@example.com"
    assert after["id"] == before["id"]

    assert (
        auth_client.post(
            "/api/auth/login",
            json={"email": before["email"], "password": "tester12345"},
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/api/auth/login",
            json={"email": "renamed@example.com", "password": "tester12345"},
        ).status_code
        == 200
    )


def test_change_identifier_requires_current_password(auth_client):
    response = auth_client.patch(
        "/api/users/me", json={"username": "sneaky", "email": "sneaky@example.com"}
    )
    assert response.status_code == 400

    wrong = auth_client.patch(
        "/api/users/me",
        json={
            "username": "sneaky",
            "email": "sneaky@example.com",
            "current_password": "notmypassword",
        },
    )
    assert wrong.status_code == 400


def test_change_identifier_rejects_duplicate(auth_client, admin_client):
    other = admin_client.post(
        "/api/admin/users",
        json={
            "username": "occupied",
            "email": "occupied@example.com",
            "password": "occupied12345",
        },
    ).json()

    clash_name = auth_client.patch(
        "/api/users/me",
        json={"username": other["username"], "current_password": "tester12345"},
    )
    assert clash_name.status_code == 400

    clash_email = auth_client.patch(
        "/api/users/me",
        json={"email": other["email"], "current_password": "tester12345"},
    )
    assert clash_email.status_code == 400


def test_keeping_own_identifier_is_not_a_conflict(auth_client):
    me = auth_client.get("/api/users/me").json()
    response = auth_client.patch(
        "/api/users/me",
        json={
            "username": me["username"],
            "email": me["email"],
            "current_password": "tester12345",
        },
    )
    assert response.status_code == 200
    assert response.json()["username"] == me["username"]


def test_change_password_requires_correct_current(auth_client):
    response = auth_client.post(
        "/api/users/me/password",
        json={"current_password": "wrongpass", "new_password": "brandnew12345"},
    )
    assert response.status_code == 400


def test_change_password_then_login_with_new(auth_client):
    me = auth_client.get("/api/users/me").json()

    response = auth_client.post(
        "/api/users/me/password",
        json={"current_password": "tester12345", "new_password": "brandnew12345"},
    )
    assert response.status_code == 200

    assert (
        auth_client.post(
            "/api/auth/login",
            json={"email": me["email"], "password": "tester12345"},
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/api/auth/login",
            json={"email": me["email"], "password": "brandnew12345"},
        ).status_code
        == 200
    )


def test_avatar_upload_and_remove(auth_client):
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = auth_client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", io.BytesIO(png), "image/png")},
    )
    assert response.status_code == 200, response.text
    url = response.json()["avatar"]
    assert url and url.startswith("/api/users/avatar/")

    served = auth_client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"

    removed = auth_client.delete("/api/users/me/avatar")
    assert removed.status_code == 200
    assert removed.json()["avatar"] is None
    assert auth_client.get(url).status_code == 404


def test_avatar_rejects_non_image(auth_client):
    response = auth_client.post(
        "/api/users/me/avatar",
        files={"file": ("evil.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 400


def test_avatar_filename_cannot_traverse(auth_client):
    assert auth_client.get("/api/users/avatar/..%2F..%2Flinguascene.db").status_code == 404
