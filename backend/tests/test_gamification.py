def test_profile_starts_at_level_one(auth_client):
    response = auth_client.get("/api/gamification/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["level"] == 1
    assert body["level_name"] == "Beginner"
    assert body["xp"] == 0
    assert body["streak"] == 0


def test_streak_increases_after_finishing_scenario(auth_client):
    coffee = next(
        s for s in auth_client.get("/api/scenarios").json() if s["slug"] == "restaurant"
    )
    conversation_id = auth_client.post(f"/api/scenarios/{coffee['id']}/start").json()["id"]
    auth_client.post(f"/api/conversations/{conversation_id}/finish")

    streak = auth_client.get("/api/gamification/streak").json()
    assert streak["streak"] == 1


def test_daily_quests_reflect_progress(auth_client):
    quests = auth_client.get("/api/gamification/daily-quests").json()
    assert len(quests) == 4
    assert all("progress" in q and "target" in q for q in quests)
    assert all(q["xp"] == 0 for q in quests)


def test_completing_scenario_advances_quest(auth_client):
    coffee = next(
        s
        for s in auth_client.get("/api/scenarios").json()
        if s["slug"] == "hotel-check-in"
    )
    conversation_id = auth_client.post(f"/api/scenarios/{coffee['id']}/start").json()["id"]

    for message in [
        "I have a reservation under Chen.",
        "Is breakfast included?",
        "What time is check-out?",
    ]:
        auth_client.post(
            f"/api/conversations/{conversation_id}/message", json={"message": message}
        )
    auth_client.post(f"/api/conversations/{conversation_id}/finish")

    quests = {q["key"]: q for q in auth_client.get("/api/gamification/daily-quests").json()}
    assert quests["complete_scenario"]["completed"] is True


def test_leaderboard_contains_me(auth_client):
    response = auth_client.get("/api/gamification/leaderboard")
    assert response.status_code == 200
    assert any(entry["is_me"] for entry in response.json())


def test_achievements_list_and_unlock(auth_client):
    achievements = auth_client.get("/api/gamification/achievements").json()
    assert len(achievements) >= 9
    assert all("unlocked" in a for a in achievements)
    assert all("progress" in a and "target" in a for a in achievements)
    assert all(0 <= a["progress"] <= a["target"] for a in achievements)
    first = next(a for a in achievements if a["code"] == "first_scenario")
    assert first["unlocked"] is False
    assert first["progress"] == 0 and first["target"] == 1

    coffee = next(
        s for s in auth_client.get("/api/scenarios").json() if s["slug"] == "airport-check-in"
    )
    conversation_id = auth_client.post(f"/api/scenarios/{coffee['id']}/start").json()["id"]
    auth_client.post(f"/api/conversations/{conversation_id}/finish")

    updated = {a["code"]: a for a in auth_client.get("/api/gamification/achievements").json()}
    assert updated["first_scenario"]["unlocked"] is True


def test_achievement_unlock_notifies_once(auth_client):
    assert auth_client.get("/api/gamification/achievements/pending").json() == []

    scenario = next(
        s for s in auth_client.get("/api/scenarios").json() if s["slug"] == "airport-check-in"
    )
    conversation_id = auth_client.post(
        f"/api/scenarios/{scenario['id']}/start"
    ).json()["id"]
    auth_client.post(f"/api/conversations/{conversation_id}/finish")

    pending = auth_client.get("/api/gamification/achievements/pending").json()
    codes = [a["code"] for a in pending]
    assert "first_scenario" in codes
    assert all(a["unlocked"] for a in pending)

    assert auth_client.post(
        "/api/gamification/achievements/ack", json={"codes": ["first_scenario"]}
    ).json()["updated"] == 1

    remaining = [a["code"] for a in auth_client.get("/api/gamification/achievements/pending").json()]
    assert "first_scenario" not in remaining
    listed = {a["code"]: a for a in auth_client.get("/api/gamification/achievements").json()}
    assert listed["first_scenario"]["unlocked"] is True


def test_collecting_words_unlocks_achievement_without_conversation(auth_client):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.user import User

    cards = auth_client.get("/api/wordbook/cards?limit=2").json()["items"]
    assert auth_client.post(
        f"/api/wordbook/word/{cards[0]['id']}/collect"
    ).status_code == 200

    me = auth_client.get("/api/users/me").json()
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.id == me["id"])).scalar_one()
        user.streak = 30
        db.commit()
    finally:
        db.close()

    auth_client.post(f"/api/wordbook/word/{cards[1]['id']}/collect")
    codes = [a["code"] for a in auth_client.get("/api/gamification/achievements").json()
             if a["unlocked"]]
    assert "streak_30" in codes


def test_themes_are_free_and_switchable(auth_client):
    themes = auth_client.get("/api/gamification/themes").json()
    assert any(item["code"] == "ocean" for item in themes)
    assert all("price" not in item and "owned" not in item for item in themes)

    target = next(item for item in themes if item["code"] == "sakura")
    response = auth_client.patch("/api/users/me", json={"theme": target["code"]})
    assert response.status_code == 200
    assert response.json()["theme"] == "sakura"
    assert auth_client.get("/api/users/me").json()["theme"] == "sakura"


def test_theme_must_exist(auth_client):
    response = auth_client.patch("/api/users/me", json={"theme": "not-a-theme"})
    assert response.status_code == 400


def test_coins_are_gone_and_xp_is_the_only_currency(auth_client):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.user import User

    me = auth_client.get("/api/users/me").json()
    assert "coins" not in me
    assert "coins" not in auth_client.get("/api/gamification/profile").json()
    assert "coins" not in auth_client.get(f"/api/stats/users/{me['id']}").json()

    scenario = next(
        s for s in auth_client.get("/api/scenarios").json() if s["slug"] == "restaurant"
    )
    conversation_id = auth_client.post(f"/api/scenarios/{scenario['id']}/start").json()["id"]
    auth_client.post(f"/api/conversations/{conversation_id}/finish")

    assert auth_client.get("/api/users/me").json()["xp"] > me["xp"]

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.id == me["id"])).scalar_one()
        assert user.coins == 0
    finally:
        db.close()


def test_dashboard_returns_mission_and_quests(auth_client):
    response = auth_client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["greeting"]
    assert body["today_mission"] is not None
    assert len(body["daily_quests"]) == 4
    assert body["recommended_article"] is not None


def test_learning_a_word_touches_streak(auth_client):
    assert auth_client.get("/api/gamification/streak").json()["streak"] == 0
    card = auth_client.get("/api/wordbook/cards?limit=1").json()["items"][0]
    assert auth_client.post(f"/api/wordbook/word/{card['id']}/collect").status_code == 200
    assert auth_client.get("/api/gamification/streak").json()["streak"] == 1


def test_sending_one_chat_message_touches_streak(auth_client):
    scenario = next(
        s for s in auth_client.get("/api/scenarios").json() if s["slug"] == "restaurant"
    )
    conversation_id = auth_client.post(
        f"/api/scenarios/{scenario['id']}/start"
    ).json()["id"]
    auth_client.post(
        f"/api/conversations/{conversation_id}/message", json={"message": "Hi"}
    )
    assert auth_client.get("/api/gamification/streak").json()["streak"] == 1


def test_publishing_a_forum_post_touches_streak_and_heatmap(auth_client):
    assert auth_client.post(
        "/api/forum/posts",
        json={"title": "打卡测试", "content": "正文", "tags": []},
    ).status_code == 201
    assert auth_client.get("/api/gamification/streak").json()["streak"] == 1
    cells = auth_client.get("/api/stats/heatmap?days=30").json()["cells"]
    assert cells[-1]["count"] >= 1


def test_reading_a_material_touches_streak_and_daily_task(auth_client):
    assert auth_client.get("/api/gamification/streak").json()["streak"] == 0

    assert auth_client.get("/api/reading/materials/article/1").status_code == 200

    assert auth_client.get("/api/gamification/streak").json()["streak"] == 1
    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["done"]["articles"] == 1
    cells = auth_client.get("/api/stats/heatmap?days=30").json()["cells"]
    assert cells[-1]["count"] >= 1

    auth_client.get("/api/reading/materials/article/1")
    assert auth_client.get("/api/wordbook/daily-task").json()["done"]["articles"] == 1

    assert auth_client.get("/api/reading/materials/article/2").status_code == 200
    assert auth_client.get("/api/wordbook/daily-task").json()["done"]["articles"] == 2


def test_uploading_a_material_touches_streak_once(auth_client):
    upload = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("t.txt", b"One sentence here.", "text/plain")},
        data={"title": "打卡材料"},
    )
    assert upload.status_code == 201
    content_id = upload.json()["id"]

    assert auth_client.get("/api/gamification/streak").json()["streak"] == 1
    assert auth_client.get("/api/wordbook/daily-task").json()["done"]["articles"] == 1
    assert auth_client.get(
        f"/api/reading/materials/content/{content_id}"
    ).status_code == 200
    assert auth_client.get("/api/wordbook/daily-task").json()["done"]["articles"] == 1

    me = auth_client.get("/api/users/me").json()
    first = auth_client.get(f"/api/stats/users/{me['id']}").json()["contribution"]

    assert auth_client.post(
        f"/api/reading/materials/content/{content_id}/publish?is_public=true"
    ).status_code == 200
    assert auth_client.get(f"/api/stats/users/{me['id']}").json()["contribution"] == first
    assert auth_client.get("/api/gamification/streak").json()["streak"] == 1
