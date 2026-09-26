import io


def test_upload_txt_and_generate_material(auth_client):
    raw = (
        "Artificial intelligence is transforming education. Adaptive systems "
        "personalize practice and help learners make progress faster."
    ).encode("utf-8")

    response = auth_client.post(
        "/api/content/upload",
        files={"file": ("sample.txt", io.BytesIO(raw), "text/plain")},
        data={"title": "AI and Education"},
    )
    assert response.status_code == 201
    content = response.json()
    assert content["title"] == "AI and Education"
    assert content["word_count"] > 10

    material = auth_client.post(
        f"/api/content/{content['id']}/generate-learning-material"
    )
    assert material.status_code == 200
    body = material.json()
    assert body["summary"]
    assert isinstance(body["keywords"], list)


def test_upload_rejects_unsupported_type(auth_client):
    response = auth_client.post(
        "/api/content/upload",
        files={"file": ("virus.exe", io.BytesIO(b"MZ\x00\x00"), "application/octet-stream")},
        data={"title": "bad"},
    )
    assert response.status_code == 400


def test_upload_rejects_empty_content(auth_client):
    response = auth_client.post(
        "/api/content/upload",
        files={"file": ("empty.txt", io.BytesIO(b"   "), "text/plain")},
        data={"title": "empty"},
    )
    assert response.status_code == 400


def test_upload_text_only(auth_client):
    response = auth_client.post(
        "/api/content/upload",
        data={
            "title": "Pasted Text",
            "text": "Practice speaking every day and your fluency will improve.",
        },
    )
    assert response.status_code == 201
    content = response.json()
    assert content["title"] == "Pasted Text"
    assert content["content_type"] == "txt"
    assert content["word_count"] > 5


def test_upload_text_only_to_reading(auth_client):
    response = auth_client.post(
        "/api/reading/materials/upload",
        data={"text": "Reading aloud helps pronunciation and confidence."},
    )
    assert response.status_code == 201
    material = response.json()
    assert material["is_mine"] is True
    assert "Reading aloud" in material["content"]


def test_upload_requires_file_or_text(auth_client):
    response = auth_client.post("/api/content/upload", data={"title": "nothing"})
    assert response.status_code == 400
    assert "上传文件或输入文本" in response.json()["detail"]


def test_list_and_get_user_content(auth_client):
    raw = b"Reading widely is one of the fastest ways to build vocabulary."
    created = auth_client.post(
        "/api/content/upload",
        files={"file": ("reading.txt", io.BytesIO(raw), "text/plain")},
        data={"title": "Reading"},
    ).json()

    listing = auth_client.get("/api/content").json()
    assert any(c["id"] == created["id"] for c in listing)

    detail = auth_client.get(f"/api/content/{created['id']}").json()
    assert "Reading widely" in detail["content"]
