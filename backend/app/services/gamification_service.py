"""游戏化服务：XP、等级、Streak、每日任务、成就、排行榜、商店。"""

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
    # 任何获得经验的学习行为都算当天打卡：热力图与连续打卡天数据此累计，
    # 不再只有完成场景才递增（见 touch_streak）。
    touch_streak(db, user)
    return record


def touch_streak(db: Session, user: User) -> int:
    """记录当天学习活动，跨天连续则 streak +1，中断则重置为 1。

    成就检查放在这里：touch_streak 是所有学习行为（含论坛发帖、每日计划
    打勾这些不发经验的路径）的共同出口，而 award_xp 也一定会走到这里。
    因此成就在达标当下解锁，不必等下一次完成对话。
    """
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

    # 当天重复活动也可能刚好凑够条件（如词库攒到 50 个词），所以放判断之外
    check_achievements(db, user)
    return user.streak


def active_days_this_week(db: Session, user: User) -> list[str]:
    """本周有学习记录的日期（周一为一周起点）。

    手动打勾的每日计划也算——见 social_service.set_quest_checked。
    """
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
    """用今天的 XP 记录数粗略折算学习时长，每条约 2 分钟，作为打卡依据。"""
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
    """成就判定用的当前值。

    check_achievements 与成就列表共用，保证「进度条」和「解锁」永远同源，
    不会出现显示差 1 个却已解锁这类自相矛盾的状态。
    """
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
    """按真实统计解锁成就，返回本次新解锁的成就。"""
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
    """已解锁但还没给用户弹过提示的成就。

    notified_at 由前端确认接口回填，这样即使提示组件挂载时机错过了
    解锁瞬间，下次登录也会补上，不会静默丢失。
    """
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
    """把指定成就标记为已提示；返回实际更新的条数。"""
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
            # 进度给前端展示「离点亮还差多少」，已解锁时封顶到目标值
            "progress": min(stats.get(a.condition_type, 0), a.condition_value),
            "target": a.condition_value,
        }
        for a in all_achievements
    ]


def theme_items() -> list[dict]:
    """所有可切换的皮肤。皮肤免费，返回全量，不再标记拥有或价格。"""
    return [
        {
            "code": item["code"],
            "name": item["name"],
            "colors": item["colors"],
        }
        for item in levels.THEMES
    ]
