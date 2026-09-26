from datetime import datetime


def _start_coffee(client) -> dict:
    scenarios = client.get("/api/scenarios").json()
    coffee = next(s for s in scenarios if s["slug"] == "ordering-coffee")
    response = client.post(f"/api/scenarios/{coffee['id']}/start")
    assert response.status_code == 200
    return response.json()


def test_start_conversation_has_opening_line(auth_client):
    data = _start_coffee(auth_client)
    assert data["mode"] == "scenario"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "assistant"
    assert "get for you" in data["messages"][0]["content"]


def test_conversation_progresses_through_tasks(auth_client):
    data = _start_coffee(auth_client)
    conversation_id = data["id"]

    r1 = auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "I'd like a latte, please."},
    )
    assert r1.status_code == 200
    assert "choose_drink" in r1.json()["completed_tasks"]
    assert r1.json()["task_progress"] == 16

    r2 = auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "A large one, please."},
    )
    assert "choose_size" in r2.json()["completed_tasks"]
    assert r2.json()["task_progress"] == 33

    r3 = auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "Can I have it with oat milk?"},
    )
    assert "choose_milk" in r3.json()["completed_tasks"]

    auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "I'd like it iced, please."},
    )
    auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "Could I add some vanilla syrup?"},
    )

    r6 = auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "I'll pay by card."},
    )
    assert r6.json()["task_completed"] is True
    assert r6.json()["task_progress"] == 100


def test_offline_mode_gives_no_correction_or_comment(auth_client):
    data = _start_coffee(auth_client)
    response = auth_client.post(
        f"/api/conversations/{data['id']}/message",
        json={"message": "I am agree with you."},
    )
    body = response.json()
    assert body["correction"] is None
    assert body["natural_expression"] is None
    assert body["coach_note"] is None
    assert body["new_vocabulary"] == []


def test_offline_mode_still_returns_task_hint(auth_client):
    data = _start_coffee(auth_client)
    response = auth_client.post(
        f"/api/conversations/{data['id']}/message",
        json={"message": "Hello."},
    )
    body = response.json()
    assert body["hint"] is not None
    assert body["hint"]["task_key"]
    assert body["ai_message"]["content"]


def test_finish_generates_report_and_xp(auth_client):
    data = _start_coffee(auth_client)
    conversation_id = data["id"]

    for message in [
        "I'd like a latte, please.",
        "Large, please.",
        "With oat milk.",
        "Iced, please.",
        "Add some vanilla syrup.",
        "I'll pay by card.",
    ]:
        auth_client.post(
            f"/api/conversations/{conversation_id}/message", json={"message": message}
        )

    response = auth_client.post(f"/api/conversations/{conversation_id}/finish")
    assert response.status_code == 200
    report = response.json()
    assert report["task_progress"] == 100
    assert report["xp_earned"] > 0
    assert report["streak"] == 1
    assert 1 <= report["scores"]["grammar"] <= 5


def test_finish_is_idempotent(auth_client):
    data = _start_coffee(auth_client)
    first = auth_client.post(f"/api/conversations/{data['id']}/finish").json()
    second = auth_client.post(f"/api/conversations/{data['id']}/finish").json()
    assert first["xp_earned"] == second["xp_earned"]


def test_cannot_send_after_finish(auth_client):
    data = _start_coffee(auth_client)
    auth_client.post(f"/api/conversations/{data['id']}/finish")
    response = auth_client.post(
        f"/api/conversations/{data['id']}/message", json={"message": "Hello again"}
    )
    assert response.status_code == 400


def test_free_talk_mode(auth_client):
    response = auth_client.post("/api/conversations/free-talk/start")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "free_talk"
    assert data["scenario"] is None

    reply = auth_client.post(
        f"/api/conversations/{data['id']}/message",
        json={"message": "I went to the park yesterday."},
    )
    assert reply.status_code == 200
    assert reply.json()["ai_message"]["content"]


def test_hint_starts_on_first_task(auth_client):
    data = _start_coffee(auth_client)
    hint = data["hint"]
    assert hint is not None
    assert hint["task_key"] == "choose_drink"
    assert hint["idea_zh"]
    assert hint["suggested_zh"]
    assert hint["suggested_en"]


def test_hint_advances_with_progress(auth_client):
    data = _start_coffee(auth_client)
    conversation_id = data["id"]

    first = auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "I'd like a latte, please."},
    ).json()
    assert first["hint"]["task_key"] == "choose_size"

    second = auth_client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"message": "A large one, please."},
    ).json()
    assert second["hint"]["task_key"] == "choose_milk"


def test_hint_is_none_when_all_tasks_done(auth_client):
    data = _start_coffee(auth_client)
    conversation_id = data["id"]

    last = None
    for message in [
        "I'd like a latte, please.",
        "Large, please.",
        "With oat milk.",
        "Iced, please.",
        "Add some vanilla syrup.",
        "I'll pay by card.",
    ]:
        last = auth_client.post(
            f"/api/conversations/{conversation_id}/message", json={"message": message}
        ).json()

    assert last["task_completed"] is True
    assert last["hint"] is None


def test_conversation_detail_carries_hint(auth_client):
    data = _start_coffee(auth_client)
    detail = auth_client.get(f"/api/conversations/{data['id']}").json()
    assert detail["hint"]["task_key"] == "choose_drink"


def test_free_talk_has_no_hint(auth_client):
    data = auth_client.post("/api/conversations/free-talk/start").json()
    assert data["hint"] is None


def test_conversation_list(auth_client):
    _start_coffee(auth_client)
    response = auth_client.get("/api/conversations")
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_free_talk_history_keeps_one_row(auth_client):
    auth_client.post("/api/conversations/free-talk/start")
    second = auth_client.post("/api/conversations/free-talk/start").json()
    auth_client.post(
        f"/api/conversations/{second['id']}/message",
        json={"message": "I'd like to talk about my weekend trip."},
    )

    rows = [
        item
        for item in auth_client.get("/api/conversations").json()
        if item["mode"] == "free_talk"
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == second["id"]
    assert rows[0]["scenario_title"] == "Free Talk"
    assert rows[0]["preview"] == "I'd like to talk about my weekend trip."
    assert datetime.fromisoformat(rows[0]["last_message_at"]) > datetime.fromisoformat(
        rows[0]["started_at"]
    )


def _stored_conversation_ids(user_id: int, *, scenario_id: int | None) -> list[int]:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.learning import Conversation

    stmt = select(Conversation.id).where(Conversation.user_id == user_id)
    stmt = stmt.where(
        Conversation.scenario_id == scenario_id
        if scenario_id is not None
        else Conversation.scenario_id.is_(None)
    )
    db = SessionLocal()
    try:
        return list(db.execute(stmt).scalars().all())
    finally:
        db.close()


def _coffee_scenario_id(client) -> int:
    return next(
        s for s in client.get("/api/scenarios").json() if s["slug"] == "ordering-coffee"
    )["id"]


def test_restart_replaces_scenario_history(auth_client):
    user_id = auth_client.get("/api/users/me").json()["id"]
    scenario_id = _coffee_scenario_id(auth_client)

    older = _start_coffee(auth_client)
    auth_client.post(
        f"/api/conversations/{older['id']}/message",
        json={"message": "I'd like a latte, please."},
    )

    newer = auth_client.post(
        f"/api/scenarios/{scenario_id}/start?restart=true"
    ).json()

    assert _stored_conversation_ids(user_id, scenario_id=scenario_id) == [newer["id"]]
    assert newer["task_progress"] == 0
    assert len(newer["messages"]) == 1

    rows = [
        item
        for item in auth_client.get("/api/conversations").json()
        if item["scenario_title"] == "Ordering Coffee"
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == newer["id"]


def test_restart_replaces_free_talk_history(auth_client):
    user_id = auth_client.get("/api/users/me").json()["id"]

    auth_client.post("/api/conversations/free-talk/start")
    newer = auth_client.post(
        "/api/conversations/free-talk/start?restart=true"
    ).json()

    assert _stored_conversation_ids(user_id, scenario_id=None) == [newer["id"]]


def test_delete_conversation(auth_client):
    data = _start_coffee(auth_client)
    auth_client.post(
        f"/api/conversations/{data['id']}/message", json={"message": "Hello."}
    )

    assert auth_client.delete(f"/api/conversations/{data['id']}").status_code == 204
    assert auth_client.get(f"/api/conversations/{data['id']}").status_code == 404
    assert all(
        item["id"] != data["id"]
        for item in auth_client.get("/api/conversations").json()
    )


def test_scenario_history_keeps_one_row_per_scenario(auth_client):
    older = _start_coffee(auth_client)
    auth_client.post(
        f"/api/conversations/{older['id']}/message",
        json={"message": "I'd like a latte, please."},
    )
    newer = _start_coffee(auth_client)

    rows = [
        item
        for item in auth_client.get("/api/conversations").json()
        if item["scenario_title"] == "Ordering Coffee"
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == newer["id"]
    assert rows[0]["task_progress"] == 16
    assert rows[0]["is_completed"] is False


def test_cannot_access_others_conversation(client):
    import uuid

    def register() -> str:
        suffix = uuid.uuid4().hex[:8]
        res = client.post(
            "/api/auth/register",
            json={
                "username": f"u{suffix}",
                "email": f"u{suffix}@example.com",
                "password": "password123",
            },
        )
        return res.json()["access_token"]

    token_a, token_b = register(), register()

    client.headers.update({"Authorization": f"Bearer {token_a}"})
    coffee = next(
        s for s in client.get("/api/scenarios").json() if s["slug"] == "ordering-coffee"
    )
    conversation_id = client.post(f"/api/scenarios/{coffee['id']}/start").json()["id"]

    client.headers.update({"Authorization": f"Bearer {token_b}"})
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def _start_interview(client) -> dict:
    scenarios = client.get("/api/scenarios").json()
    interview = next(s for s in scenarios if s["slug"] == "job-interview")
    response = client.post(f"/api/scenarios/{interview['id']}/start")
    assert response.status_code == 200
    return response.json()


def test_number_word_completes_task(auth_client):
    data = _start_interview(auth_client)
    body = auth_client.post(
        f"/api/conversations/{data['id']}/message",
        json={"message": "I have three years of backend development experience."},
    ).json()
    assert "self_intro" in body["completed_tasks"]


def test_hint_advances_after_number_word_answer(auth_client):
    data = _start_interview(auth_client)
    assert data["hint"]["task_key"] == "self_intro"

    body = auth_client.post(
        f"/api/conversations/{data['id']}/message",
        json={"message": "I have three years of backend development experience."},
    ).json()
    assert body["hint"]["task_key"] == "describe_skills"


def test_every_task_accepts_its_own_suggested_en():
    from app.ai import rule_engine
    from app.data.scenario_content import TASKS

    broken = [
        key
        for key, item in TASKS.items()
        if item.get("suggested_en")
        and key
        not in rule_engine.detect_completed_tasks(item["suggested_en"], [key], set())
    ]
    assert broken == []
