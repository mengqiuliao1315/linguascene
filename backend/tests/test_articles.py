def test_list_articles(auth_client):
    response = auth_client.get("/api/articles")
    assert response.status_code == 200
    articles = response.json()
    assert len(articles) >= 6
    assert all("title" in a for a in articles)


def test_article_detail_has_content(auth_client):
    article_id = auth_client.get("/api/articles").json()[0]["id"]
    response = auth_client.get(f"/api/articles/{article_id}")
    assert response.status_code == 200
    assert len(response.json()["content"]) > 100


def test_analyze_article_returns_structured_analysis(auth_client):
    articles = auth_client.get("/api/articles").json()
    ai_article = next(a for a in articles if "AI" in a["title"])

    response = auth_client.post(f"/api/articles/{ai_article['id']}/analyze")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]
    assert body["level"]
    assert isinstance(body["keywords"], list)
    assert isinstance(body["reading_questions"], list)
    assert body["reading_questions"]


def test_analysis_is_cached_in_database(auth_client):
    article_id = auth_client.get("/api/articles").json()[0]["id"]
    first = auth_client.post(f"/api/articles/{article_id}/analyze").json()
    second = auth_client.post(f"/api/articles/{article_id}/analyze").json()
    assert first == second


def test_translate_returns_word_explanation(auth_client):
    response = auth_client.post("/api/articles/translate", json={"text": "adaptive"})
    assert response.status_code == 200
    body = response.json()
    assert body["word"] == "adaptive"
    assert body["core_meanings"]


def test_explain_unknown_word_does_not_invent_meaning(auth_client):
    response = auth_client.post(
        "/api/articles/translate", json={"text": "zzzznonexistent"}
    )
    assert response.status_code == 200
    assert response.json()["core_meanings"] == []


def test_sentence_analysis_extracts_structure(auth_client):
    sentence = (
        "The rapid development of artificial intelligence has significantly "
        "changed the way students learn."
    )
    response = auth_client.post(
        "/api/articles/explain-sentence", json={"sentence": sentence}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sentence"] == sentence
    assert body["main_clause"]
    assert isinstance(body["collocations"], list)
    assert isinstance(body["grammar_points"], list)


def test_filter_articles_by_category(auth_client):
    response = auth_client.get("/api/articles", params={"category": "Technology"})
    assert response.status_code == 200
    assert all(a["category"] == "Technology" for a in response.json())
