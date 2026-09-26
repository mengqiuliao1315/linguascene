from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user import User

PET_SPECIES: tuple[str, ...] = ("hedgehog",)
DEFAULT_SPECIES = "hedgehog"
MAX_NAME_LENGTH = 12

DELIGHTED_DAYS = 2
EXCITED_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(offset: int = 0) -> str:
    return (_now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _days_between(start: str, end: str) -> int:
    try:
        first = datetime.strptime(start, "%Y-%m-%d").date()
        second = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return 0
    return max((second - first).days, 0)


def normalize_species(value: str | None) -> str:
    return value if value in PET_SPECIES else DEFAULT_SPECIES


def record_visit(db: Session, user: User) -> None:
    today = _day()
    if user.last_login_date == today:
        return

    if user.last_login_date == _day(-1):
        user.login_streak += 1
    else:
        user.login_streak = 1

    user.last_login_date = today
    user.best_login_streak = max(user.best_login_streak, user.login_streak)
    db.flush()


def mood_for(streak: int) -> str:
    if streak >= EXCITED_DAYS:
        return "excited"
    if streak >= DELIGHTED_DAYS:
        return "delighted"
    return "happy"


def snapshot(user: User) -> dict:
    today = _day()
    previous = user.last_login_date

    if not previous or previous == today:
        return {"previous_mood": None, "days_away": 0}

    away = _days_between(previous, today)
    if away <= 1:
        return {"previous_mood": "waiting", "days_away": 0}

    return {"previous_mood": "sad", "days_away": max(away - 1, 1)}


def projected_streak(user: User) -> int:
    today = _day()
    if user.last_login_date == today:
        return user.login_streak
    if user.last_login_date == _day(-1):
        return user.login_streak + 1
    return 1


def payload(user: User, previous: dict | None = None) -> dict:
    state = previous if previous is not None else {"previous_mood": None, "days_away": 0}
    streak = projected_streak(user)
    return {
        "species": normalize_species(user.pet_species),
        "name": user.pet_name or "",
        "mood": mood_for(streak),
        "previous_mood": state["previous_mood"],
        "days_away": state["days_away"],
        "login_streak": streak,
        "best_login_streak": max(user.best_login_streak, streak),
        "study_streak": user.streak,
        "last_login_date": user.last_login_date,
    }
