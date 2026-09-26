"""萌宠：每天喂一次，没喂就是 hungry，同一天再喂不涨连续天数。"""

from datetime import datetime, timedelta, timezone

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


def _set_fed(user_id: int, last_fed: str | None, streak: int) -> None:
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one()
        user.pet_last_fed = last_fed
        user.pet_feed_streak = streak
        db.commit()
    finally:
        db.close()


def _day(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d")


def test_pet_requires_login(client):
    assert client.get("/api/pet").status_code == 401
    assert client.post("/api/pet/feed").status_code == 401


def test_unfed_pet_is_hungry_until_fed(auth_client):
    """新用户没喂过：打开首页是 hungry，喂一次变成开心，再喂还是今天喂过。"""
    state = auth_client.get("/api/pet").json()
    assert state["fed_today"] is False
    assert state["mood"] == "hungry"
    assert state["feed_streak"] == 0

    fed = auth_client.post("/api/pet/feed")
    assert fed.status_code == 200, fed.text
    body = fed.json()
    assert body["fed_today"] is True
    assert body["mood"] == "happy"
    assert body["feed_streak"] == 1
    assert body["last_fed_date"] == _day()
    # 喂食也算今天来看过
    assert body["login_streak"] == 1

    again = auth_client.post("/api/pet/feed").json()
    assert again["fed_today"] is True
    assert again["feed_streak"] == 1
    assert again["mood"] == "happy"

    reread = auth_client.get("/api/pet").json()
    assert reread["fed_today"] is True
    assert reread["mood"] == "happy"
    assert reread["feed_streak"] == 1


def test_feed_streak_continues_from_yesterday_and_resets_after_a_gap(auth_client):
    user_id = _me(auth_client)["id"]

    _set_fed(user_id, _day(-1), 3)
    continued = auth_client.post("/api/pet/feed").json()
    assert continued["feed_streak"] == 4
    assert continued["mood"] != "hungry"

    _set_fed(user_id, _day(-3), 4)
    reset = auth_client.post("/api/pet/feed").json()
    assert reset["feed_streak"] == 1

    stored = _user(user_id)
    assert stored.pet_last_fed == _day()
    assert stored.pet_feed_streak == 1


def test_get_does_not_record_a_visit_or_a_meal(auth_client):
    """GET 只读：连读两次也不会把今天记成来过或喂过。"""
    user_id = _me(auth_client)["id"]
    assert auth_client.get("/api/pet").status_code == 200
    assert auth_client.get("/api/pet").json()["fed_today"] is False

    stored = _user(user_id)
    assert stored.last_login_date is None
    assert stored.pet_last_fed is None
