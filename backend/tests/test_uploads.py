from app.core.storage import MAX_AVATAR_BYTES, MAX_FORUM_IMAGE_BYTES, MAX_UPLOAD_BYTES


def test_content_upload_rejects_oversize(auth_client):
    payload = b"x" * (MAX_UPLOAD_BYTES + 1)
    response = auth_client.post(
        "/api/content/upload",
        files={"file": ("huge.txt", payload, "text/plain")},
        data={"title": "too big"},
    )
    assert response.status_code == 400
    assert "10MB" in response.json()["detail"]


def test_reading_upload_rejects_oversize(auth_client):
    payload = b"x" * (MAX_UPLOAD_BYTES + 1)
    response = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("huge.txt", payload, "text/plain")},
        data={"title": "too big"},
    )
    assert response.status_code == 400


def test_avatar_upload_rejects_oversize(auth_client):
    payload = b"\x89PNG\r\n" + b"x" * MAX_AVATAR_BYTES
    response = auth_client.post(
        "/api/users/me/avatar",
        files={"file": ("face.png", payload, "image/png")},
    )
    assert response.status_code == 400
    assert "2MB" in response.json()["detail"]


def test_forum_image_rejects_oversize(auth_client):
    payload = b"\x89PNG\r\n" + b"x" * MAX_FORUM_IMAGE_BYTES
    response = auth_client.post(
        "/api/forum/images",
        files={"file": ("pic.png", payload, "image/png")},
    )
    assert response.status_code == 400
    assert "5MB" in response.json()["detail"]
