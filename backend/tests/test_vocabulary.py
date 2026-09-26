def test_save_and_list_vocabulary(auth_client):
    response = auth_client.post(
        "/api/vocabulary/save",
        json={
            "word": "Significantly",
            "meaning": "显著地",
            "level": "B1",
            "source": "reading",
        },
    )
    assert response.status_code == 201
    saved = response.json()
    assert saved["word"] == "significantly"  # 统一小写

    listing = auth_client.get("/api/vocabulary").json()
    assert any(item["word"] == "significantly" for item in listing)


def test_duplicate_save_does_not_create_second_entry(auth_client):
    payload = {"word": "adaptive", "meaning": "适应性的", "level": "B2"}
    auth_client.post("/api/vocabulary/save", json=payload)
    auth_client.post("/api/vocabulary/save", json=payload)

    listing = auth_client.get("/api/vocabulary").json()
    matches = [item for item in listing if item["word"] == "adaptive"]
    assert len(matches) == 1


def test_review_updates_mastery(auth_client):
    saved = auth_client.post(
        "/api/vocabulary/save",
        json={"word": "collaborate", "meaning": "协作", "level": "B2"},
    ).json()

    before = saved["mastery"]
    response = auth_client.post(
        f"/api/vocabulary/{saved['id']}/review", json={"quality": 2}
    )
    assert response.status_code == 200
    assert response.json()["mastery"] > before


def test_forgetting_lowers_mastery(auth_client):
    saved = auth_client.post(
        "/api/vocabulary/save",
        json={"word": "leverage", "meaning": "利用", "level": "B2"},
    ).json()

    before = saved["mastery"]
    result = auth_client.post(
        f"/api/vocabulary/{saved['id']}/review", json={"quality": 0}
    ).json()
    assert result["mastery"] < before


def test_review_unknown_word_404(auth_client):
    response = auth_client.post("/api/vocabulary/999999/review", json={"quality": 2})
    assert response.status_code == 404


def test_delete_vocabulary(auth_client):
    saved = auth_client.post(
        "/api/vocabulary/save", json={"word": "sustainable", "meaning": "可持续的"}
    ).json()
    assert auth_client.delete(f"/api/vocabulary/{saved['id']}").status_code == 204

    listing = auth_client.get("/api/vocabulary").json()
    assert not any(item["word"] == "sustainable" for item in listing)


def test_saving_word_awards_xp(auth_client):
    before = auth_client.get("/api/users/me").json()["xp"]
    auth_client.post("/api/vocabulary/save", json={"word": "proficient", "meaning": "熟练的"})
    after = auth_client.get("/api/users/me").json()["xp"]
    assert after > before
