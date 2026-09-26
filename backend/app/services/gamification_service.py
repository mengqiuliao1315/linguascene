from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.gamification import Achievement, UserAchievement, XpRecord
from app.models.learning import Conversation, UserVocabulary
from app.models.social import QuestCheck
from app.models.user import User
from app.services import levels


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def award_xp(db: Session, user: User, amount: int, source: str) -> XpRecord:
    record = XpRecord(user_id=user.id, amount=amount, source=source)
    db.add(record)
    user.xp += amount
    user.level, _ = levels.level_for_xp(user.xp)
    db.flush()
    touch_streak(db, user)
    return record


def touch_streak(db: Session, user: User) -> int:
    today = _today()
    if user.last_active_date != today:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        if user.last_active_date == yesterday:
            user.streak += 1
        else:
            user.streak = 1

        user.last_active_date = today
        user.longest_streak = max(user.longest_streak, user.streak)
        db.flush()

    check_achievements(db, user)
    return user.streak


def active_days_this_week(db: Session, user: User) -> list[str]:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)

    rows = db.execute(
        select(XpRecord.created_at).where(
            XpRecord.user_id == user.id, XpRecord.created_at >= start
        )
    ).scalars().all()
    checks = db.execute(
        select(QuestCheck.day).where(
            QuestCheck.user_id == user.id,
            QuestCheck.day >= start.strftime("%Y-%m-%d"),
        )
    ).scalars().all()
    return sorted({r.strftime("%Y-%m-%d") for r in rows} | set(checks))


def weekly_xp(db: Session, user: User) -> int:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)
    total = db.execute(
        select(func.coalesce(func.sum(XpRecord.amount), 0)).where(
            XpRecord.user_id == user.id, XpRecord.created_at >= start
        )
    ).scalar_one()
    return int(total)


def today_minutes(db: Session, user: User) -> int:
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    count = db.execute(
        select(func.count(XpRecord.id)).where(
            XpRecord.user_id == user.id, XpRecord.created_at >= start
        )
    ).scalar_one()
    return int(count) * 2


def daily_quests(db: Session, user: User) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

    today_xp = db.execute(
        select(XpRecord).where(XpRecord.user_id == user.id, XpRecord.created_at >= start)
    ).scalars().all()

    scenarios_done = len([r for r in today_xp if r.source == "scenario"])
    words_learned = db.execute(
        select(func.count(UserVocabulary.id)).where(
            UserVocabulary.user_id == user.id, UserVocabulary.created_at >= start
        )
    ).scalar_one()
    articles_read = len([r for r in today_xp if r.source == "article"])
    chat_records = len([r for r in today_xp if r.source == "free_talk"])
    chat_minutes = chat_records * 2

    progress_map = {
        "complete_scenario": scenarios_done,
        "learn_words": int(words_learned),
        "read_article": articles_read,
        "chat_minutes": chat_minutes,
    }

    result = []
    for quest in levels.DAILY_QUESTS:
        progress = progress_map.get(quest["key"], 0)
        result.append(
            {
                "key": quest["key"],
                "label": quest["label"],
                "target": quest["target"],
                "progress": min(progress, quest["target"]),
                "xp": quest["xp"],
                "completed": progress >= quest["target"],
            }
        )
    return result


def weekly_leaderboard(db: Session, me: User, limit: int = 20) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)

    rows = db.execute(
        select(User.id, User.username, User.avatar, func.sum(XpRecord.amount).label("xp"))
        .join(XpRecord, XpRecord.user_id == User.id)
        .where(XpRecord.created_at >= start)
        .group_by(User.id)
        .order_by(func.sum(XpRecord.amount).desc())
        .limit(limit)
    ).all()

    entries = [
        {
            "rank": index + 1,
            "user_id": row.id,
            "username": row.username,
            "avatar": row.avatar,
            "xp": int(row.xp),
            "is_me": row.id == me.id,
        }
        for index, row in enumerate(rows)
    ]

    if not any(e["is_me"] for e in entries):
        my_xp = weekly_xp(db, me)
        entries.append(
            {
                "rank": len(entries) + 1,
                "user_id": me.id,
                "username": me.username,
                "avatar": me.avatar,
                "xp": my_xp,
                "is_me": True,
            }
        )
    return entries


def achievement_stats(db: Session, user: User) -> dict[str, int]:
    scenarios_done = db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.user_id == user.id,
            Conversation.is_completed.is_(True),
            Conversation.mode == "scenario",
        )
    ).scalar_one()
    words_saved = db.execute(
        select(func.count(UserVocabulary.id)).where(UserVocabulary.user_id == user.id)
    ).scalar_one()
    articles_done = db.execute(
        select(func.count(XpRecord.id)).where(
            XpRecord.user_id == user.id, XpRecord.source == "article"
        )
    ).scalar_one()

    return {
        "scenarios": int(scenarios_done),
        "streak": user.streak,
        "words": int(words_saved),
        "xp": user.xp,
        "articles": int(articles_done),
    }


def check_achievements(db: Session, user: User) -> list[Achievement]:
    all_achievements = db.execute(select(Achievement)).scalars().all()
    unlocked_ids = {
        row.achievement_id
        for row in db.execute(
            select(UserAchievement).where(UserAchievement.user_id == user.id)
        ).scalars().all()
    }

    stats = achievement_stats(db, user)

    newly: list[Achievement] = []
    for achievement in all_achievements:
        if achievement.id in unlocked_ids:
            continue
        if stats.get(achievement.condition_type, 0) >= achievement.condition_value:
            db.add(
                UserAchievement(user_id=user.id, achievement_id=achievement.id)
            )
            newly.append(achievement)

    if newly:
        db.flush()
    return newly


def pending_achievements(db: Session, user: User) -> list[Achievement]:
    rows = db.execute(
        select(Achievement)
        .join(UserAchievement, UserAchievement.achievement_id == Achievement.id)
        .where(
            UserAchievement.user_id == user.id,
            UserAchievement.notified_at.is_(None),
        )
        .order_by(UserAchievement.unlocked_at)
    ).scalars().all()
    return list(rows)


def mark_achievements_notified(db: Session, user: User, codes: list[str]) -> int:
    if not codes:
        return 0
    rows = db.execute(
        select(UserAchievement)
        .join(Achievement, Achievement.id == UserAchievement.achievement_id)
        .where(
            UserAchievement.user_id == user.id,
            UserAchievement.notified_at.is_(None),
            Achievement.code.in_(codes),
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.notified_at = now
    if rows:
        db.flush()
    return len(rows)


def achievements_with_state(db: Session, user: User) -> list[dict]:
    all_achievements = db.execute(
        select(Achievement).order_by(Achievement.id)
    ).scalars().all()
    unlocks = {
        row.achievement_id: row.unlocked_at
        for row in db.execute(
            select(UserAchievement).where(UserAchievement.user_id == user.id)
        ).scalars().all()
    }
    stats = achievement_stats(db, user)
    return [
        {
            "code": a.code,
            "name": a.name,
            "description": a.description,
            "icon": a.icon,
            "unlocked": a.id in unlocks,
            "unlocked_at": unlocks.get(a.id),
            "progress": min(stats.get(a.condition_type, 0), a.condition_value),
            "target": a.condition_value,
        }
        for a in all_achievements
    ]


def theme_items() -> list[dict]:
    return [
        {
            "code": item["code"],
            "name": item["name"],
            "colors": item["colors"],
        }
        for item in levels.THEMES
    ]
