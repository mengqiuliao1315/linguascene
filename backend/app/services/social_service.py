"""社交服务：每日计划、打卡热力图、个人主页、好友、私信、论坛。

统计口径集中在这里，页面只负责展示。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.content import UserContent
from app.models.gamification import XpRecord
from app.models.learning import Conversation, UserVocabulary
from app.models.social import (
    ChatMessage,
    CustomQuest,
    ForumComment,
    ForumLike,
    ForumPost,
    Friendship,
    QuestCheck,
)
from app.models.user import User
from app.models.wordbook import ContributionRecord
from app.services import gamification_service, levels

HEATMAP_DAYS = 182
CHAT_MINUTES_PER_RECORD = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _day_start(day: datetime | None = None) -> datetime:
    base = day or _now()
    return datetime.combine(base.date(), datetime.min.time(), tzinfo=timezone.utc)


# ------------------------------------------------------------------ 每日统计


def daily_stats(db: Session, user: User, day: datetime | None = None) -> dict:
    """当天的各项学习量。自建计划的可选口径都从这里取。"""
    start = _day_start(day)
    end = start + timedelta(days=1)

    records = db.execute(
        select(XpRecord).where(
            XpRecord.user_id == user.id,
            XpRecord.created_at >= start,
            XpRecord.created_at < end,
        )
    ).scalars().all()

    by_source: dict[str, int] = {}
    for record in records:
        by_source[record.source] = by_source.get(record.source, 0) + 1

    words = db.execute(
        select(func.count(UserVocabulary.id)).where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.created_at >= start,
            UserVocabulary.created_at < end,
        )
    ).scalar_one()

    forum_posts = db.execute(
        select(func.count(ForumPost.id)).where(
            ForumPost.user_id == user.id,
            ForumPost.created_at >= start,
            ForumPost.created_at < end,
        )
    ).scalar_one()

    return {
        "words": int(words),
        "articles": by_source.get("article", 0),
        "scenarios": by_source.get("scenario", 0),
        "reviews": by_source.get("review", 0),
        "chat_minutes": by_source.get("free_talk", 0) * CHAT_MINUTES_PER_RECORD,
        "forum_posts": int(forum_posts),
    }


# ------------------------------------------------------------------ 每日计划


def ensure_default_quests(db: Session, user: User) -> None:
    """首次打开面板时，把四条默认计划落成用户自己的计划，只播一次。

    播完置 user.quests_seeded；之后用户改名、改目标、删光都不会再长出来。
    """
    if user.quests_seeded:
        return

    for index, quest in enumerate(levels.DAILY_QUESTS):
        db.add(
            CustomQuest(
                user_id=user.id,
                label=quest["label"],
                metric=quest.get("metric", "words"),
                target=quest["target"],
                xp=quest["xp"],
                icon=quest.get("icon", "🎯"),
                sort_order=index,
            )
        )
    user.quests_seeded = 1
    db.flush()


def _quest_payload(quest: CustomQuest, stats: dict, checked: bool) -> dict:
    """一条计划的接口形状。

    progress 是按 metric 自动统计出来的提示（「今天做到多少了」）；
    completed 只看用户当天有没有打勾——计划做什么只有用户自己清楚，
    系统不替用户判定完成。
    """
    progress = stats.get(quest.metric, 0)
    return {
        "id": quest.id,
        "key": f"custom-{quest.id}",
        "label": quest.label,
        "icon": quest.icon,
        "target": quest.target,
        "progress": min(progress, quest.target),
        "xp": quest.xp,
        "completed": checked,
        "custom": True,
        "metric": quest.metric,
    }


def _checked_quest_ids(db: Session, user: User, day: str | None = None) -> set[int]:
    """当天已打勾的计划 id 集合。"""
    rows = db.execute(
        select(QuestCheck.quest_id).where(
            QuestCheck.user_id == user.id, QuestCheck.day == (day or _today())
        )
    ).scalars().all()
    return set(rows)


def merged_quests(db: Session, user: User) -> list[dict]:
    """用户自己的全部每日计划，带当天进度与打勾状态。"""
    ensure_default_quests(db, user)
    stats = daily_stats(db, user)
    checked = _checked_quest_ids(db, user)

    quests = db.execute(
        select(CustomQuest)
        .where(CustomQuest.user_id == user.id, CustomQuest.is_active.is_(True))
        .order_by(CustomQuest.sort_order, CustomQuest.id)
    ).scalars().all()

    return [_quest_payload(quest, stats, quest.id in checked) for quest in quests]


def quest_payload(db: Session, user: User, quest: CustomQuest) -> dict:
    """单条计划的最新状态，创建/修改/打勾后回给前端。"""
    checked = quest.id in _checked_quest_ids(db, user)
    return _quest_payload(quest, daily_stats(db, user), checked)


def set_quest_checked(db: Session, user: User, quest: CustomQuest, completed: bool) -> dict:
    """给一条计划打勾 / 取消打勾。

    打勾算当天一次学习活动：热力图会多一格，连续打卡天数也会跟着走
    （见 activity_by_day 与 gamification_service.touch_streak）。
    """
    day = _today()
    existing = db.execute(
        select(QuestCheck).where(
            QuestCheck.user_id == user.id,
            QuestCheck.quest_id == quest.id,
            QuestCheck.day == day,
        )
    ).scalar_one_or_none()

    if completed and existing is None:
        db.add(QuestCheck(user_id=user.id, quest_id=quest.id, day=day))
        db.flush()
        gamification_service.touch_streak(db, user)
    elif not completed and existing is not None:
        db.delete(existing)
        db.flush()

    return quest_payload(db, user, quest)


def create_quest(db: Session, user: User, payload) -> CustomQuest:
    # 先补默认计划，保证用户自己加的那条排在四条默认计划后面
    ensure_default_quests(db, user)
    count = db.execute(
        select(func.count(CustomQuest.id)).where(CustomQuest.user_id == user.id)
    ).scalar_one()
    quest = CustomQuest(
        user_id=user.id,
        label=payload.label.strip(),
        metric=payload.metric,
        target=payload.target,
        xp=payload.xp,
        icon=payload.icon or "🎯",
        sort_order=int(count),
    )
    db.add(quest)
    db.flush()
    return quest


def get_quest(db: Session, user: User, quest_id: int) -> CustomQuest | None:
    return db.execute(
        select(CustomQuest).where(
            CustomQuest.id == quest_id, CustomQuest.user_id == user.id
        )
    ).scalar_one_or_none()


def update_quest(db: Session, quest: CustomQuest, payload) -> CustomQuest:
    data = payload.model_dump(exclude_unset=True)
    for field in ("label", "metric", "target", "xp", "icon"):
        if data.get(field) is not None:
            setattr(quest, field, data[field])
    if data.get("is_active") is not None:
        quest.is_active = 1 if data["is_active"] else 0
    db.flush()
    return quest


def delete_quest(db: Session, quest: CustomQuest) -> None:
    db.delete(quest)
    db.flush()


# ------------------------------------------------------------------ 打卡热力图


def activity_by_day(db: Session, user: User, days: int = HEATMAP_DAYS) -> dict[str, int]:
    """按天汇总学习活动次数，用于热力图与活跃天数。

    三个来源：XpRecord（背单词、场景、复习等）、ContributionRecord
    （发帖、评论、上传内容——这些只记贡献值，不发经验）、QuestCheck
    （用户手动打勾的每日计划——站内统计不到的行为靠它补上）。少了后两者，
    连续打卡天数涨了、热力图却还是空的。
    """
    since = _day_start() - timedelta(days=days - 1)
    rows = db.execute(
        select(XpRecord.created_at).where(
            XpRecord.user_id == user.id, XpRecord.created_at >= since
        )
    ).scalars().all()
    contributions = db.execute(
        select(ContributionRecord.created_at).where(
            ContributionRecord.user_id == user.id,
            ContributionRecord.created_at >= since,
        )
    ).scalars().all()
    checks = db.execute(
        select(QuestCheck.day).where(
            QuestCheck.user_id == user.id,
            QuestCheck.day >= since.strftime("%Y-%m-%d"),
        )
    ).scalars().all()

    counts: dict[str, int] = {}
    for created in [*rows, *contributions]:
        key = created.strftime("%Y-%m-%d")
        counts[key] = counts.get(key, 0) + 1
    for day in checks:
        counts[day] = counts.get(day, 0) + 1
    return counts


def _heat_level(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 9:
        return 3
    return 4


def heatmap(db: Session, user: User, days: int = HEATMAP_DAYS) -> dict:
    counts = activity_by_day(db, user, days)
    today = _now().date()
    cells = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.strftime("%Y-%m-%d")
        count = counts.get(key, 0)
        cells.append({"date": key, "count": count, "level": _heat_level(count)})

    return {
        "cells": cells,
        "total_days": days,
        "current_streak": user.streak,
        "longest_streak": user.longest_streak,
        "total_active_days": len(counts),
    }


# ------------------------------------------------------------------ 用户数据


def contribution_total(db: Session, user_id: int) -> int:
    """单个用户的累计贡献值，取自贡献值流水。"""
    return int(
        db.execute(
            select(func.coalesce(func.sum(ContributionRecord.amount), 0)).where(
                ContributionRecord.user_id == user_id
            )
        ).scalar_one()
    )


def contribution_of(db: Session, user_id: int) -> dict:
    """个人主页的贡献数据。

    分数取自贡献值流水，与排行榜同源，两处不会各算一个数；下面四项是活动明细，
    按实际记录数展示，不参与计分。
    """
    published = db.execute(
        select(func.count(UserContent.id)).where(
            UserContent.user_id == user_id, UserContent.is_public.is_(True)
        )
    ).scalar_one()
    posts = db.execute(
        select(func.count(ForumPost.id)).where(ForumPost.user_id == user_id)
    ).scalar_one()
    comments = db.execute(
        select(func.count(ForumComment.id)).where(ForumComment.user_id == user_id)
    ).scalar_one()
    likes = db.execute(
        select(func.coalesce(func.sum(ForumPost.like_count), 0)).where(
            ForumPost.user_id == user_id
        )
    ).scalar_one()

    return {
        "published_articles": int(published),
        "forum_posts": int(posts),
        "forum_comments": int(comments),
        "likes_received": int(likes),
        "contribution": contribution_total(db, user_id),
    }


def public_stats(db: Session, user: User) -> dict:
    """个人主页展示的数据，任何人都能看。"""
    level, level_name = levels.level_for_xp(user.xp)
    contrib = contribution_of(db, user.id)

    words_total = db.execute(
        select(func.count(UserVocabulary.id)).where(UserVocabulary.user_id == user.id)
    ).scalar_one()
    scenarios_done = db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.user_id == user.id,
            Conversation.is_completed.is_(True),
            Conversation.mode == "scenario",
        )
    ).scalar_one()
    active_days = len(activity_by_day(db, user))

    return {
        "user_id": user.id,
        "username": user.username,
        "avatar": user.avatar,
        "role": user.role,
        "cefr_level": user.cefr_level,
        "level": level,
        "level_name": level_name,
        "xp": user.xp,
        "streak": user.streak,
        "longest_streak": user.longest_streak,
        "created_at": user.created_at,
        **contrib,
        "words_total": int(words_total),
        "scenarios_done": int(scenarios_done),
        "active_days": active_days,
        **{f"{k}_today" if k in ("words", "articles") else k: v
           for k, v in daily_stats(db, user).items()
           if k in ("words", "articles")},
    }


def contribution_totals(db: Session) -> dict[int, int]:
    """每个用户的累计贡献值。没有记录的用户不在返回结果里。"""
    rows = db.execute(
        select(
            ContributionRecord.user_id,
            func.coalesce(func.sum(ContributionRecord.amount), 0).label("total"),
        ).group_by(ContributionRecord.user_id)
    ).all()
    return {row.user_id: int(row.total or 0) for row in rows}


def leaderboard(db: Session, me: User, metric: str = "xp", limit: int = 20) -> dict:
    """排行榜：柱状图 + 列表共用同一份数据。

    metric 支持 xp（累计经验）、streak（连续打卡天数）、contribution（贡献值）。
    """
    users = db.execute(select(User)).scalars().all()
    contributions = contribution_totals(db) if metric == "contribution" else {}

    rows = []
    for user in users:
        if metric == "streak":
            value = user.streak
        elif metric == "contribution":
            value = contributions.get(user.id, 0)
        else:
            value = user.xp
        rows.append(
            {
                "user_id": user.id,
                "username": user.username,
                "avatar": user.avatar,
                "value": int(value),
                "is_me": user.id == me.id,
            }
        )

    rows.sort(key=lambda r: (-r["value"], r["username"]))
    top = rows[:limit]
    if not any(r["is_me"] for r in top):
        mine = next(r for r in rows if r["is_me"])
        top.append(mine)

    entries = []
    for index, row in enumerate(top):
        user = next(u for u in users if u.id == row["user_id"])
        level, level_name = levels.level_for_xp(user.xp)
        entries.append(
            {
                **row,
                "rank": index + 1,
                "level": level,
                "level_name": level_name,
                "streak": user.streak,
            }
        )

    return {"bars": top, "entries": entries}


# ------------------------------------------------------------------ 好友


def _pair(db: Session, a: int, b: int) -> Friendship | None:
    return db.execute(
        select(Friendship).where(
            or_(
                (Friendship.requester_id == a) & (Friendship.addressee_id == b),
                (Friendship.requester_id == b) & (Friendship.addressee_id == a),
            )
        )
    ).scalar_one_or_none()


def friend_state(db: Session, me: User, other_id: int) -> dict:
    if me.id == other_id:
        return {"state": "self", "friendship_id": None}
    link = _pair(db, me.id, other_id)
    if not link:
        return {"state": "none", "friendship_id": None}
    if link.status == "accepted":
        return {"state": "friends", "friendship_id": link.id}
    if link.requester_id == me.id:
        return {"state": "outgoing", "friendship_id": link.id}
    return {"state": "incoming", "friendship_id": link.id}


def request_friend(db: Session, me: User, other_id: int) -> Friendship:
    if me.id == other_id:
        raise ValueError("不能加自己为好友")
    other = db.get(User, other_id)
    if not other:
        raise ValueError("用户不存在")

    link = _pair(db, me.id, other_id)
    if link:
        if link.status == "accepted":
            raise ValueError("你们已经是好友")
        if link.requester_id == me.id:
            raise ValueError("已发送过申请")
        # 对方先发过申请，这里直接互相通过
        link.status = "accepted"
        db.flush()
        return link

    link = Friendship(requester_id=me.id, addressee_id=other_id, status="pending")
    db.add(link)
    db.flush()
    return link


def respond_friend(db: Session, me: User, friendship_id: int, accept: bool) -> None:
    link = db.get(Friendship, friendship_id)
    if not link or link.addressee_id != me.id:
        raise ValueError("申请不存在")
    if accept:
        link.status = "accepted"
        db.flush()
    else:
        db.delete(link)
        db.flush()


def remove_friend(db: Session, me: User, other_id: int) -> None:
    link = _pair(db, me.id, other_id)
    if not link:
        raise ValueError("你们不是好友")
    db.delete(link)
    db.flush()


def _friend_payload(db: Session, user: User, friendship_id: int | None = None) -> dict:
    level, level_name = levels.level_for_xp(user.xp)
    return {
        "user_id": user.id,
        "username": user.username,
        "avatar": user.avatar,
        "level": level,
        "level_name": level_name,
        "xp": user.xp,
        "streak": user.streak,
        "online_today": user.last_active_date == _today(),
        "friendship_id": friendship_id,
    }


def list_friends(db: Session, me: User) -> list[dict]:
    links = db.execute(
        select(Friendship).where(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == me.id, Friendship.addressee_id == me.id),
        )
    ).scalars().all()

    result = []
    for link in links:
        other_id = link.addressee_id if link.requester_id == me.id else link.requester_id
        other = db.get(User, other_id)
        if other:
            result.append(_friend_payload(db, other, link.id))
    result.sort(key=lambda f: (-f["xp"], f["username"]))
    return result


def list_friend_requests(db: Session, me: User) -> tuple[list[dict], list[dict]]:
    incoming_rows = db.execute(
        select(Friendship).where(
            Friendship.addressee_id == me.id, Friendship.status == "pending"
        )
    ).scalars().all()
    outgoing_rows = db.execute(
        select(Friendship).where(
            Friendship.requester_id == me.id, Friendship.status == "pending"
        )
    ).scalars().all()

    def build(rows, incoming: bool):
        out = []
        for link in rows:
            other_id = link.requester_id if incoming else link.addressee_id
            other = db.get(User, other_id)
            if other:
                out.append(
                    {
                        "friendship_id": link.id,
                        "user_id": other.id,
                        "username": other.username,
                        "avatar": other.avatar,
                        "created_at": link.created_at,
                        "incoming": incoming,
                    }
                )
        return out

    return build(incoming_rows, True), build(outgoing_rows, False)


def are_friends(db: Session, a: int, b: int) -> bool:
    link = _pair(db, a, b)
    return bool(link and link.status == "accepted")


# ------------------------------------------------------------------ 私信


def send_message(db: Session, me: User, other_id: int, content: str) -> ChatMessage:
    if not are_friends(db, me.id, other_id):
        raise ValueError("只有好友之间可以聊天")
    message = ChatMessage(
        sender_id=me.id, recipient_id=other_id, content=content.strip()
    )
    db.add(message)
    db.flush()
    return message


def list_messages(
    db: Session, me: User, other_id: int, limit: int = 100
) -> list[ChatMessage]:
    if not are_friends(db, me.id, other_id):
        raise ValueError("只有好友之间可以聊天")

    rows = db.execute(
        select(ChatMessage)
        .where(
            or_(
                (ChatMessage.sender_id == me.id) & (ChatMessage.recipient_id == other_id),
                (ChatMessage.sender_id == other_id) & (ChatMessage.recipient_id == me.id),
            )
        )
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    ).scalars().all()

    # 打开对话即视为已读
    changed = False
    for row in rows:
        if row.recipient_id == me.id and row.read_at is None:
            row.read_at = _now()
            changed = True
    if changed:
        db.flush()

    return list(reversed(rows))


def chat_threads(db: Session, me: User) -> list[dict]:
    """按好友聚合最近一条消息，附未读数。"""
    friends = list_friends(db, me)
    result = []
    for friend in friends:
        other_id = friend["user_id"]
        last = db.execute(
            select(ChatMessage)
            .where(
                or_(
                    (ChatMessage.sender_id == me.id) & (ChatMessage.recipient_id == other_id),
                    (ChatMessage.sender_id == other_id) & (ChatMessage.recipient_id == me.id),
                )
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).scalar_one_or_none()

        unread = db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.sender_id == other_id,
                ChatMessage.recipient_id == me.id,
                ChatMessage.read_at.is_(None),
            )
        ).scalar_one()

        result.append(
            {
                "user_id": other_id,
                "username": friend["username"],
                "avatar": friend["avatar"],
                "last_message": last.content if last else "",
                "last_at": last.created_at if last else None,
                "unread": int(unread),
            }
        )

    result.sort(key=lambda t: (t["last_at"] is None, -(t["last_at"].timestamp() if t["last_at"] else 0)))
    return result


def unread_total(db: Session, me: User) -> int:
    return int(
        db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.recipient_id == me.id, ChatMessage.read_at.is_(None)
            )
        ).scalar_one()
    )


# ------------------------------------------------------------------ 论坛


def _author(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    if not user:
        return {
            "user_id": user_id,
            "username": "已注销",
            "avatar": None,
            "level": 1,
            "level_name": "Beginner",
        }
    level, level_name = levels.level_for_xp(user.xp)
    return {
        "user_id": user.id,
        "username": user.username,
        "avatar": user.avatar,
        "level": level,
        "level_name": level_name,
    }


def _tags(raw: str) -> list[str]:
    return [t for t in (raw or "").split(",") if t]


def _plain(content: str) -> str:
    """去掉 Markdown 标记，压成一行。"""
    import re

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#*`>\-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _summary(content: str, limit: int = 120) -> str:
    """列表页摘要：截断到 limit 字，卡片折叠时展示。"""
    return _plain(content)[:limit]


def _cover(content: str) -> str | None:
    """取正文第一张图片作为卡片封面，没有就返回 None。"""
    import re

    match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", content or "")
    return match.group(1).strip() if match else None


def _truncated(content: str, limit: int = 120) -> bool:
    """正文是否长到需要折叠，前端据此显示「展开全文」。"""
    return len(_plain(content)) > limit


# 排序方式：最新 / 最热 / 讨论最多。前端选项卡与之一一对应。
POST_SORTS = ("new", "hot", "active")
_POST_ORDER = {
    "new": (ForumPost.created_at.desc(), ForumPost.id.desc()),
    "hot": (ForumPost.like_count.desc(), ForumPost.comment_count.desc(), ForumPost.id.desc()),
    "active": (ForumPost.comment_count.desc(), ForumPost.id.desc()),
}


def _tag_clause(tag: str):
    """精确匹配逗号分隔的标签，避免 "口语" 命中 "口语练习"。"""
    return or_(
        ForumPost.tags == tag,
        ForumPost.tags.like(f"{tag},%"),
        ForumPost.tags.like(f"%,{tag}"),
        ForumPost.tags.like(f"%,{tag},%"),
    )


def list_posts(
    db: Session,
    me: User,
    *,
    tag: str = "",
    keyword: str = "",
    sort: str = "new",
    offset: int = 0,
    limit: int = 20,
) -> list[dict]:
    query = select(ForumPost)
    if tag:
        query = query.where(_tag_clause(tag))
    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            or_(ForumPost.title.ilike(like), ForumPost.content.ilike(like))
        )

    order = _POST_ORDER.get(sort, _POST_ORDER["new"])
    posts = db.execute(
        query.order_by(ForumPost.is_pinned.desc(), *order)
        .offset(max(0, offset))
        .limit(limit)
    ).scalars().all()

    post_ids = [post.id for post in posts]
    liked_ids: set[int] = set()
    if post_ids:
        liked_ids = {
            row.post_id
            for row in db.execute(
                select(ForumLike).where(
                    ForumLike.user_id == me.id, ForumLike.post_id.in_(post_ids)
                )
            ).scalars().all()
        }

    return [
        {
            "id": post.id,
            "title": post.title,
            "summary": _summary(post.content),
            "truncated": _truncated(post.content),
            "cover": _cover(post.content),
            "tags": _tags(post.tags),
            "author": _author(db, post.user_id),
            "view_count": post.view_count,
            "like_count": post.like_count,
            "comment_count": post.comment_count,
            "liked": post.id in liked_ids,
            "is_pinned": bool(post.is_pinned),
            "is_mine": post.user_id == me.id,
            "created_at": post.created_at,
            "updated_at": post.updated_at,
        }
        for post in posts
    ]


def get_post(db: Session, me: User, post_id: int, count_view: bool = True) -> ForumPost | None:
    post = db.get(ForumPost, post_id)
    if not post:
        return None
    # 作者自己反复打开不算阅读量，避免刷数据
    if count_view and post.user_id != me.id:
        post.view_count += 1
        db.flush()
    return post


def post_detail(db: Session, me: User, post: ForumPost) -> dict:
    liked = db.execute(
        select(ForumLike).where(
            ForumLike.post_id == post.id, ForumLike.user_id == me.id
        )
    ).scalar_one_or_none()
    return {
        "id": post.id,
        "title": post.title,
        "summary": _summary(post.content),
        "truncated": _truncated(post.content),
        "content": post.content,
        "tags": _tags(post.tags),
        "author": _author(db, post.user_id),
        "view_count": post.view_count,
        "like_count": post.like_count,
        "comment_count": post.comment_count,
        "liked": liked is not None,
        "is_pinned": bool(post.is_pinned),
        "is_mine": post.user_id == me.id,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }


def create_post(db: Session, me: User, payload) -> ForumPost:
    post = ForumPost(
        user_id=me.id,
        title=payload.title.strip(),
        content=payload.content,
        tags=",".join(t.strip() for t in payload.tags if t.strip()),
    )
    db.add(post)
    gamification_service.touch_streak(db, me)
    db.flush()
    return post


def update_post(db: Session, post: ForumPost, payload) -> ForumPost:
    data = payload.model_dump(exclude_unset=True)
    if data.get("title"):
        post.title = data["title"].strip()
    if data.get("content"):
        post.content = data["content"]
    if data.get("tags") is not None:
        post.tags = ",".join(t.strip() for t in data["tags"] if t.strip())
    db.flush()
    return post


def delete_post(db: Session, post: ForumPost) -> None:
    db.delete(post)
    db.flush()


def toggle_like(db: Session, me: User, post: ForumPost) -> bool:
    existing = db.execute(
        select(ForumLike).where(
            ForumLike.post_id == post.id, ForumLike.user_id == me.id
        )
    ).scalar_one_or_none()

    if existing:
        db.delete(existing)
        post.like_count = max(0, post.like_count - 1)
        db.flush()
        return False

    db.add(ForumLike(post_id=post.id, user_id=me.id))
    post.like_count += 1
    db.flush()
    return True


def list_comments(db: Session, me: User, post_id: int) -> list[dict]:
    rows = db.execute(
        select(ForumComment)
        .where(ForumComment.post_id == post_id)
        .order_by(ForumComment.id)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "content": row.content,
            "author": _author(db, row.user_id),
            "is_mine": row.user_id == me.id,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def add_comment(db: Session, me: User, post: ForumPost, content: str) -> ForumComment:
    comment = ForumComment(post_id=post.id, user_id=me.id, content=content.strip())
    db.add(comment)
    post.comment_count += 1
    gamification_service.touch_streak(db, me)
    db.flush()
    return comment


def delete_comment(db: Session, comment: ForumComment) -> None:
    post = db.get(ForumPost, comment.post_id)
    if post:
        post.comment_count = max(0, post.comment_count - 1)
    db.delete(comment)
    db.flush()


def count_posts(db: Session, *, tag: str = "", keyword: str = "") -> int:
    """与 list_posts 同口径的过滤条件下，帖子总数，用于分页。"""
    query = select(func.count(ForumPost.id))
    if tag:
        query = query.where(_tag_clause(tag))
    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            or_(ForumPost.title.ilike(like), ForumPost.content.ilike(like))
        )
    return int(db.execute(query).scalar_one())


def popular_tags(db: Session, limit: int = 12) -> list[dict]:
    """按帖子数统计热门标签，给列表页做快捷筛选。"""
    counts: dict[str, int] = {}
    rows = db.execute(select(ForumPost.tags)).scalars().all()
    for raw in rows:
        for tag in _tags(raw):
            counts[tag] = counts.get(tag, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"tag": tag, "count": count} for tag, count in ranked]
