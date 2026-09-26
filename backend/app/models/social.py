from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CustomQuest(Base):
    """用户的每日计划。

    列表里的每一条都归用户自己：可以改名、改目标、删除。新用户第一次
    打开面板时，用 levels.DAILY_QUESTS 里的四条默认计划播一次种
    （见 social_service.ensure_default_quests），之后系统不再插手。
    """

    __tablename__ = "custom_quests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(64))
    # 统计口径，取值见 levels.QUEST_METRICS；只用来显示「今天做到多少」，
    # 是否完成由用户自己打勾决定。
    metric: Mapped[str] = mapped_column(String(32), default="words")
    target: Mapped[int] = mapped_column(Integer, default=10)
    xp: Mapped[int] = mapped_column(Integer, default=10)
    icon: Mapped[str] = mapped_column(String(8), default="🎯")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestCheck(Base):
    """用户手动给某条计划打的勾，按天存。

    计划做什么只有用户自己清楚（可能压根不是站内行为），所以完成与否
    不猜，让用户点。一行 = 某条计划在某一天被打了勾，取消打勾就删掉这行，
    当天热力图与连续打卡天数据此计算（见 social_service.activity_by_day）。

    计划被删掉时这一行会保留（quest_id 置空）：那天确实做过这件事，
    不该因为之后删了计划就从热力图上消失。
    """

    __tablename__ = "quest_checks"
    __table_args__ = (
        UniqueConstraint("quest_id", "day", name="uq_quest_check_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    quest_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_quests.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # "YYYY-MM-DD"，与 User.last_active_date 同一口径
    day: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Friendship(Base):
    """好友关系。一行代表一对用户，status 区分待确认与已通过。"""

    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friend_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    addressee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | accepted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ChatMessage(Base):
    """一对一私信。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ForumPost(Base):
    """经验帖。正文支持有限的 Markdown 子集（标题/加粗/链接/图片/列表/代码）。"""

    __tablename__ = "forum_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(160), default="")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    is_pinned: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    comments = relationship(
        "ForumComment", back_populates="post", cascade="all, delete-orphan"
    )


class ForumComment(Base):
    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("forum_posts.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    post = relationship("ForumPost", back_populates="comments")


class ForumLike(Base):
    __tablename__ = "forum_likes"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_forum_like"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("forum_posts.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
