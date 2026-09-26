from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User


def _me(auth_client) -> dict:
    response = auth_client.get("/api/users/me")
    assert response.status_code == 200, response.text
    return response.json()


def _user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.id == user_id)).scalar_one()
    finally:
        db.close()


def test_pet_requires_login(client):
    assert client.get("/api/pet").status_code == 401
    assert client.post("/api/pet/visit").status_code == 401
    assert client.post("/api/pet/feed").status_code == 404


def test_opening_the_page_projects_a_happy_mood(auth_client):
    state = auth_client.get("/api/pet").json()
    assert state["mood"] == "happy"
    assert state["login_streak"] == 1
    assert "fed_today" not in state
    assert "feed_streak" not in state


def test_visit_records_today_once(auth_client):
    first = auth_client.post("/api/pet/visit")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["login_streak"] == 1
    assert body["mood"] == "happy"

    again = auth_client.post("/api/pet/visit").json()
    assert again["login_streak"] == 1


def test_get_does_not_record_a_visit(auth_client):
    user_id = _me(auth_client)["id"]
    assert auth_client.get("/api/pet").status_code == 200
    assert auth_client.get("/api/pet").status_code == 200

    stored = _user(user_id)
    assert stored.last_login_date is None
